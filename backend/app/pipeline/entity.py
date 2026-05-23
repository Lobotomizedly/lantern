"""
Entity Extraction Stage

Extracts and resolves named entities:
- Extract named entities using Claude
- Resolve against Entity table (alias matching + embedding similarity)
- Create new entities when unresolved
- Link Item to subjects and entities
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import anthropic
import redis.asyncio as redis
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    RetryableError,
    NonRetryableError,
)


# Entity types recognized by the system
ENTITY_TYPES = [
    "PERSON",
    "ORGANIZATION",
    "COMPANY",
    "GOVERNMENT_AGENCY",
    "POLITICAL_PARTY",
    "LOCATION",
    "PRODUCT",
    "EVENT",
    "LAW",
    "REGULATION",
]


ENTITY_EXTRACTION_PROMPT = """You are an expert entity extraction system for a narrative intelligence platform.

Extract all named entities from the following text. For each entity, provide:
1. name: The canonical name of the entity
2. type: One of {entity_types}
3. aliases: Any alternative names or abbreviations mentioned
4. description: A brief description based on context (1-2 sentences)
5. mentions: List of exact text spans where this entity appears

Focus on entities that are:
- Central to the narrative (people, organizations involved in the story)
- Mentioned multiple times or with significant context
- Relevant for tracking across news and documents

Skip generic references like "the company" unless tied to a specific entity.

<text>
{text}
</text>

Respond with a JSON array of entities:
```json
[
  {{
    "name": "Entity Name",
    "type": "ENTITY_TYPE",
    "aliases": ["Alias 1", "Alias 2"],
    "description": "Brief description based on context",
    "mentions": ["exact text span 1", "exact text span 2"]
  }}
]
```

Extract entities now:"""


class ClaudeEntityExtractor:
    """
    Extracts entities from text using Claude.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def extract(self, text: str) -> list[dict[str, Any]]:
        """
        Extract entities from text.

        Args:
            text: Text to extract entities from

        Returns:
            List of entity dictionaries
        """
        # Truncate text if too long
        max_input = 50000
        if len(text) > max_input:
            text = text[:max_input] + "\n\n[Text truncated...]"

        prompt = ENTITY_EXTRACTION_PROMPT.format(
            entity_types=", ".join(ENTITY_TYPES),
            text=text,
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse JSON from response
            content = response.content[0].text
            return self._parse_entities(content)

        except anthropic.RateLimitError as e:
            raise RetryableError(
                f"Claude rate limit: {e}",
                "entity",
                retry_after=60,
            )
        except anthropic.APIConnectionError as e:
            raise RetryableError(f"Claude connection error: {e}", "entity")
        except anthropic.APIError as e:
            raise NonRetryableError(f"Claude API error: {e}", "entity")

    def _parse_entities(self, response: str) -> list[dict[str, Any]]:
        """
        Parse entity JSON from Claude response.

        Args:
            response: Raw response text

        Returns:
            List of entity dictionaries
        """
        # Extract JSON from markdown code block if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON array directly
            json_match = re.search(r"\[[\s\S]*\]", response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return []

        try:
            entities = json.loads(json_str)
            if not isinstance(entities, list):
                return []
            return entities
        except json.JSONDecodeError:
            return []


class EntityResolver:
    """
    Resolves extracted entities against existing Entity records.

    Uses multiple matching strategies:
    1. Exact name match
    2. Alias matching
    3. Embedding similarity for fuzzy matching
    """

    def __init__(
        self,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        similarity_threshold: float = 0.85,
    ):
        self.db = db_session
        self.redis = redis_client
        self.similarity_threshold = similarity_threshold

    async def resolve(
        self,
        entity: dict[str, Any],
        embedding: Optional[list[float]] = None,
    ) -> Optional[UUID]:
        """
        Resolve an extracted entity to an existing Entity record.

        Args:
            entity: Extracted entity data
            embedding: Optional embedding for similarity search

        Returns:
            Entity ID if resolved, None if new entity needed
        """
        name = entity.get("name", "").strip()
        entity_type = entity.get("type", "").upper()
        aliases = entity.get("aliases", [])

        if not name:
            return None

        # Strategy 1: Exact name match
        resolved = await self._match_exact_name(name, entity_type)
        if resolved:
            return resolved

        # Strategy 2: Alias matching
        all_names = [name] + aliases
        for alias in all_names:
            resolved = await self._match_alias(alias, entity_type)
            if resolved:
                return resolved

        # Strategy 3: Embedding similarity (if available)
        if embedding:
            resolved = await self._match_embedding(embedding, entity_type)
            if resolved:
                return resolved

        return None

    async def _match_exact_name(
        self, name: str, entity_type: str
    ) -> Optional[UUID]:
        """Match by exact canonical name."""
        query = text("""
            SELECT id FROM entities
            WHERE LOWER(name) = LOWER(:name)
            AND (:entity_type = '' OR entity_type = :entity_type)
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"name": name, "entity_type": entity_type},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def _match_alias(
        self, alias: str, entity_type: str
    ) -> Optional[UUID]:
        """Match by alias in the aliases array."""
        # PostgreSQL array contains query
        query = text("""
            SELECT id FROM entities
            WHERE :alias = ANY(aliases)
            AND (:entity_type = '' OR entity_type = :entity_type)
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"alias": alias.lower(), "entity_type": entity_type},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def _match_embedding(
        self, embedding: list[float], entity_type: str
    ) -> Optional[UUID]:
        """Match by embedding similarity using pgvector."""
        query = text("""
            SELECT id, name, 1 - (embedding <=> :embedding) as similarity
            FROM entities
            WHERE embedding IS NOT NULL
            AND (:entity_type = '' OR entity_type = :entity_type)
            ORDER BY embedding <=> :embedding
            LIMIT 1
        """)

        result = await self.db.execute(
            query,
            {"embedding": embedding, "entity_type": entity_type},
        )
        row = result.fetchone()

        if row and row[2] >= self.similarity_threshold:
            return UUID(str(row[0]))

        return None

    async def create_entity(
        self,
        entity: dict[str, Any],
        embedding: Optional[list[float]] = None,
    ) -> UUID:
        """
        Create a new Entity record.

        Args:
            entity: Extracted entity data
            embedding: Optional embedding vector

        Returns:
            New entity ID
        """
        entity_id = uuid4()
        name = entity.get("name", "").strip()
        entity_type = entity.get("type", "ORGANIZATION").upper()
        aliases = [a.lower() for a in entity.get("aliases", [])]
        description = entity.get("description", "")

        # Ensure entity type is valid
        if entity_type not in ENTITY_TYPES:
            entity_type = "ORGANIZATION"

        query = text("""
            INSERT INTO entities (id, name, entity_type, aliases, description, embedding, created_at, updated_at)
            VALUES (:id, :name, :entity_type, :aliases, :description, :embedding, :created_at, :updated_at)
            RETURNING id
        """)

        now = datetime.now(timezone.utc)
        await self.db.execute(
            query,
            {
                "id": str(entity_id),
                "name": name,
                "entity_type": entity_type,
                "aliases": aliases,
                "description": description,
                "embedding": embedding,
                "created_at": now,
                "updated_at": now,
            },
        )
        await self.db.commit()

        return entity_id


class EntityExtractionStage(PipelineStage):
    """
    Pipeline stage for entity extraction and resolution.

    Extracts named entities using Claude, resolves them against
    existing Entity records, and creates new entities as needed.
    """

    stage_name = "entity"
    next_stage = "claim"

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)

        # Initialize Claude extractor
        api_key = self.config.get("anthropic_api_key")
        if not api_key and settings.anthropic_api_key:
            api_key = settings.anthropic_api_key.get_secret_value()

        if not api_key:
            raise ValueError("Anthropic API key required for entity extraction")

        self.extractor = ClaudeEntityExtractor(
            api_key=api_key,
            model=self.config.get("model", settings.anthropic_model),
        )

        # Initialize resolver
        self.resolver = EntityResolver(
            db_session=db_session,
            redis_client=redis_client,
            similarity_threshold=self.config.get("similarity_threshold", 0.85),
        )

        # Configuration
        self.min_mentions = self.config.get("min_mentions", 1)
        self.max_entities = self.config.get("max_entities", 50)

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Extract and resolve entities from item content.

        Args:
            context: Pipeline context with clean_text

        Returns:
            Updated context with entities
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for entity extraction",
                self.stage_name,
                context.item_id,
            )

        # Extract entities using Claude
        try:
            raw_entities = await self.extractor.extract(context.clean_text)
        except RetryableError:
            raise
        except NonRetryableError:
            raise
        except Exception as e:
            raise RetryableError(
                f"Entity extraction failed: {e}",
                self.stage_name,
                context.item_id,
            )

        # Filter entities by mention count
        filtered_entities = [
            e for e in raw_entities
            if len(e.get("mentions", [])) >= self.min_mentions
        ][:self.max_entities]

        # Resolve or create entities
        resolved_entities: list[dict[str, Any]] = []

        for entity_data in filtered_entities:
            try:
                # Try to resolve to existing entity
                entity_id = await self.resolver.resolve(
                    entity_data,
                    embedding=context.embedding,
                )

                if entity_id is None:
                    # Create new entity
                    entity_id = await self.resolver.create_entity(
                        entity_data,
                        embedding=None,  # Entity embedding generated separately
                    )
                    is_new = True
                else:
                    is_new = False

                resolved_entities.append({
                    "entity_id": str(entity_id),
                    "name": entity_data.get("name"),
                    "type": entity_data.get("type"),
                    "mentions": entity_data.get("mentions", []),
                    "is_new": is_new,
                })

            except Exception as e:
                self.logger.warning(
                    f"Failed to resolve entity '{entity_data.get('name')}': {e}"
                )
                continue

        context.entities = resolved_entities

        # Link entities to item
        await self._link_entities_to_item(context)

        self.logger.info(
            f"Extracted {len(resolved_entities)} entities from item {context.item_id}"
        )

        return context

    async def _link_entities_to_item(self, context: PipelineContext) -> None:
        """
        Create item-entity associations in the database.

        Args:
            context: Pipeline context with resolved entities
        """
        if not context.entities:
            return

        try:
            # Insert item-entity links
            for entity in context.entities:
                query = text("""
                    INSERT INTO item_entities (item_id, entity_id, mention_count, created_at)
                    VALUES (:item_id, :entity_id, :mention_count, :created_at)
                    ON CONFLICT (item_id, entity_id) DO UPDATE
                    SET mention_count = :mention_count
                """)

                await self.db.execute(
                    query,
                    {
                        "item_id": str(context.item_id),
                        "entity_id": entity["entity_id"],
                        "mention_count": len(entity.get("mentions", [])),
                        "created_at": datetime.now(timezone.utc),
                    },
                )

            await self.db.commit()

        except Exception as e:
            self.logger.error(f"Failed to link entities to item: {e}")
            await self.db.rollback()

    async def _link_subjects_to_item(
        self,
        context: PipelineContext,
        subject_entities: list[dict[str, Any]],
    ) -> None:
        """
        Link subjects (tracked entities) to the item.

        Args:
            context: Pipeline context
            subject_entities: Entities that are also subjects
        """
        if not subject_entities:
            return

        try:
            for entity in subject_entities:
                # Find subject ID for this entity
                query = text("""
                    SELECT s.id FROM subjects s
                    JOIN subject_entities se ON s.id = se.subject_id
                    WHERE se.entity_id = :entity_id
                    LIMIT 1
                """)

                result = await self.db.execute(
                    query,
                    {"entity_id": entity["entity_id"]},
                )
                row = result.fetchone()

                if row:
                    subject_id = row[0]

                    # Link item to subject
                    link_query = text("""
                        INSERT INTO item_subjects (item_id, subject_id, created_at)
                        VALUES (:item_id, :subject_id, :created_at)
                        ON CONFLICT (item_id, subject_id) DO NOTHING
                    """)

                    await self.db.execute(
                        link_query,
                        {
                            "item_id": str(context.item_id),
                            "subject_id": str(subject_id),
                            "created_at": datetime.now(timezone.utc),
                        },
                    )

            await self.db.commit()

        except Exception as e:
            self.logger.error(f"Failed to link subjects to item: {e}")
            await self.db.rollback()
