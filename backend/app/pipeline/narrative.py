"""
Narrative Assignment Stage

Assigns items to narratives:
- Assign Claims/Events to existing Narratives
- Detect candidate new Narratives via claim embedding clustering
- Generate thesis statement for new narratives using Claude
"""

import json
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import UUID, uuid4

import anthropic
import numpy as np
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.pipeline.base import (
    PipelineStage,
    PipelineContext,
    RetryableError,
    NonRetryableError,
)


NARRATIVE_GENERATION_PROMPT = """You are an expert narrative analyst for a narrative intelligence platform.

Based on the following cluster of claims and events, identify and describe the emerging narrative.

A narrative is a coherent story or frame that:
- Connects multiple events or claims
- Has a central thesis or argument
- Involves key actors or subjects
- Evolves over time

<claims>
{claims}
</claims>

<events>
{events}
</events>

<entities>
{entities}
</entities>

Generate a narrative description:

```json
{{
  "thesis": "A single sentence describing the core argument or story (the narrative thesis)",
  "title": "A short, memorable title for this narrative",
  "description": "2-3 sentences expanding on the thesis",
  "key_actors": ["Entity 1", "Entity 2"],
  "narrative_type": "controversy|trend|crisis|development|campaign|investigation",
  "sentiment": "positive|negative|mixed|neutral",
  "confidence": 0.85
}}
```

Generate the narrative:"""


NARRATIVE_MATCH_PROMPT = """You are an expert narrative analyst.

Determine if the following item (claims and entities) fits into any of the existing narratives.

<item_claims>
{item_claims}
</item_claims>

<item_entities>
{item_entities}
</item_entities>

<existing_narratives>
{narratives}
</existing_narratives>

For each narrative that this item relates to, provide:
- narrative_id: The ID of the matching narrative
- relevance: How relevant (0-1)
- relationship: How this item relates ("supports", "contradicts", "develops", "related")

Respond with JSON:
```json
{{
  "matches": [
    {{
      "narrative_id": "uuid-here",
      "relevance": 0.85,
      "relationship": "develops"
    }}
  ],
  "suggests_new_narrative": false,
  "new_narrative_reason": ""
}}
```

Analyze now:"""


class ClaudeNarrativeAnalyzer:
    """
    Analyzes and generates narratives using Claude.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 2048,
    ):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def generate_narrative(
        self,
        claims: list[dict[str, Any]],
        events: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """
        Generate a narrative from clustered claims and events.

        Args:
            claims: Related claims
            events: Related events
            entities: Involved entities

        Returns:
            Narrative data or None
        """
        claims_text = "\n".join([
            f"- {c.get('subject', 'Unknown')}: {c.get('object', '')}"
            for c in claims[:20]
        ])

        events_text = "\n".join([
            f"- {e.get('summary', 'Unknown event')}"
            for e in events[:10]
        ])

        entities_text = ", ".join([
            e.get("name", "") for e in entities[:15]
        ])

        prompt = NARRATIVE_GENERATION_PROMPT.format(
            claims=claims_text or "No claims",
            events=events_text or "No events",
            entities=entities_text or "No entities",
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_narrative(content)

        except anthropic.RateLimitError as e:
            raise RetryableError(
                f"Claude rate limit: {e}",
                "narrative",
                retry_after=60,
            )
        except anthropic.APIConnectionError as e:
            raise RetryableError(f"Claude connection error: {e}", "narrative")
        except anthropic.APIError as e:
            raise NonRetryableError(f"Claude API error: {e}", "narrative")

    async def match_narratives(
        self,
        item_claims: list[dict[str, Any]],
        item_entities: list[dict[str, Any]],
        narratives: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Match item claims/entities to existing narratives.

        Args:
            item_claims: Claims from the item
            item_entities: Entities from the item
            narratives: Candidate narratives to match

        Returns:
            Match results with narrative IDs and relevance
        """
        if not narratives:
            return {"matches": [], "suggests_new_narrative": True}

        claims_text = "\n".join([
            f"- {c.get('subject', 'Unknown')}: {c.get('object', '')}"
            for c in item_claims[:15]
        ])

        entities_text = ", ".join([
            e.get("name", "") for e in item_entities[:10]
        ])

        narratives_text = "\n\n".join([
            f"ID: {n['id']}\nTitle: {n.get('title', 'Untitled')}\n"
            f"Thesis: {n.get('thesis', 'No thesis')}\n"
            f"Actors: {', '.join(n.get('key_actors', []))}"
            for n in narratives[:10]
        ])

        prompt = NARRATIVE_MATCH_PROMPT.format(
            item_claims=claims_text or "No claims",
            item_entities=entities_text or "No entities",
            narratives=narratives_text,
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_matches(content)

        except Exception as e:
            # On error, return empty matches
            return {"matches": [], "suggests_new_narrative": False}

    def _parse_narrative(self, response: str) -> Optional[dict[str, Any]]:
        """Parse narrative JSON from Claude response."""
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return None

        try:
            data = json.loads(json_str)
            return self._validate_narrative(data)
        except json.JSONDecodeError:
            return None

    def _parse_matches(self, response: str) -> dict[str, Any]:
        """Parse narrative match JSON from Claude response."""
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return {"matches": [], "suggests_new_narrative": False}

        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError:
            return {"matches": [], "suggests_new_narrative": False}

    def _validate_narrative(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize narrative data."""
        # Ensure required fields
        if not data.get("thesis"):
            return None

        # Normalize confidence
        confidence = data.get("confidence", 0.5)
        data["confidence"] = max(0, min(1, float(confidence)))

        # Ensure key_actors is a list
        if not isinstance(data.get("key_actors"), list):
            data["key_actors"] = []

        return data


class NarrativeClusterer:
    """
    Clusters claims to detect emerging narratives.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        similarity_threshold: float = 0.75,
        min_cluster_size: int = 3,
    ):
        self.db = db_session
        self.redis = redis_client
        self.similarity_threshold = similarity_threshold
        self.min_cluster_size = min_cluster_size

    async def find_candidate_narratives(
        self,
        embedding: list[float],
        entities: list[dict[str, Any]],
        lookback_days: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Find existing narratives that might match this item.

        Args:
            embedding: Item embedding
            entities: Item entities
            lookback_days: How far back to look

        Returns:
            List of candidate narratives
        """
        start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Get entity IDs for filtering
        entity_ids = [e.get("entity_id") for e in entities if e.get("entity_id")]

        if embedding:
            # Find narratives by embedding similarity
            query = text("""
                SELECT n.id, n.title, n.thesis, n.key_actors,
                       1 - (n.embedding <=> :embedding) as similarity
                FROM narratives n
                WHERE n.embedding IS NOT NULL
                AND n.created_at >= :start_time
                AND n.status = 'active'
                ORDER BY n.embedding <=> :embedding
                LIMIT 20
            """)

            result = await self.db.execute(
                query,
                {
                    "embedding": embedding,
                    "start_time": start_time,
                },
            )
        else:
            # Fallback to entity-based lookup
            if not entity_ids:
                return []

            query = text("""
                SELECT DISTINCT n.id, n.title, n.thesis, n.key_actors, 0.5 as similarity
                FROM narratives n
                JOIN narrative_entities ne ON n.id = ne.narrative_id
                WHERE ne.entity_id = ANY(:entity_ids)
                AND n.created_at >= :start_time
                AND n.status = 'active'
                LIMIT 20
            """)

            result = await self.db.execute(
                query,
                {
                    "entity_ids": entity_ids,
                    "start_time": start_time,
                },
            )

        rows = result.fetchall()

        narratives = []
        for row in rows:
            narratives.append({
                "id": str(row[0]),
                "title": row[1],
                "thesis": row[2],
                "key_actors": row[3] or [],
                "similarity": row[4],
            })

        return narratives

    async def find_unclustered_claims(
        self,
        entity_ids: list[str],
        lookback_days: int = 14,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Find claims that haven't been assigned to narratives.

        Args:
            entity_ids: Entity IDs to filter by
            lookback_days: How far back to look
            limit: Maximum claims to return

        Returns:
            List of unclustered claims
        """
        start_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        query = text("""
            SELECT c.id, c.subject, c.predicate, c.object, c.polarity, c.confidence
            FROM claims c
            LEFT JOIN narrative_claims nc ON c.id = nc.claim_id
            WHERE nc.claim_id IS NULL
            AND c.created_at >= :start_time
            AND (
                :no_entity_filter
                OR c.subject_entity_id = ANY(:entity_ids)
            )
            ORDER BY c.confidence DESC
            LIMIT :limit
        """)

        result = await self.db.execute(
            query,
            {
                "start_time": start_time,
                "entity_ids": entity_ids,
                "no_entity_filter": len(entity_ids) == 0,
                "limit": limit,
            },
        )

        rows = result.fetchall()

        claims = []
        for row in rows:
            claims.append({
                "id": str(row[0]),
                "subject": row[1],
                "predicate": row[2],
                "object": row[3],
                "polarity": row[4],
                "confidence": row[5],
            })

        return claims


class NarrativeAssignmentStage(PipelineStage):
    """
    Pipeline stage for narrative assignment.

    Assigns items to existing narratives or detects new ones.
    """

    stage_name = "narrative"
    next_stage = None  # Final stage

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)

        # Initialize Claude analyzer
        api_key = self.config.get("anthropic_api_key")
        if not api_key and settings.anthropic_api_key:
            api_key = settings.anthropic_api_key.get_secret_value()

        if not api_key:
            raise ValueError("Anthropic API key required for narrative assignment")

        self.analyzer = ClaudeNarrativeAnalyzer(
            api_key=api_key,
            model=self.config.get("model", settings.anthropic_model),
        )

        # Initialize clusterer
        self.clusterer = NarrativeClusterer(
            db_session=db_session,
            redis_client=redis_client,
            similarity_threshold=self.config.get("similarity_threshold", 0.75),
            min_cluster_size=self.config.get("min_cluster_size", 3),
        )

        # Configuration
        self.min_relevance = self.config.get("min_relevance", 0.6)
        self.auto_create_narratives = self.config.get("auto_create_narratives", True)

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Assign item to narratives.

        Args:
            context: Pipeline context with claims, entities, embedding

        Returns:
            Updated context with narrative_ids
        """
        if not context.claims and not context.entities:
            self.logger.debug(f"No claims or entities for narrative assignment: {context.item_id}")
            return context

        # Find candidate narratives
        candidates = await self.clusterer.find_candidate_narratives(
            context.embedding,
            context.entities,
        )

        if candidates:
            # Match item to existing narratives
            match_result = await self.analyzer.match_narratives(
                context.claims,
                context.entities,
                candidates,
            )

            # Assign to matching narratives
            for match in match_result.get("matches", []):
                if match.get("relevance", 0) >= self.min_relevance:
                    narrative_id = UUID(match["narrative_id"])
                    await self._assign_to_narrative(
                        context,
                        narrative_id,
                        match.get("relevance", 0),
                        match.get("relationship", "related"),
                    )
                    context.narrative_ids.append(narrative_id)

            # Check if new narrative suggested
            if match_result.get("suggests_new_narrative") and self.auto_create_narratives:
                new_narrative = await self._create_narrative_if_warranted(context)
                if new_narrative:
                    context.narrative_ids.append(new_narrative)

        elif self.auto_create_narratives:
            # No candidates found, check if we should create new narrative
            new_narrative = await self._create_narrative_if_warranted(context)
            if new_narrative:
                context.narrative_ids.append(new_narrative)

        self.logger.info(
            f"Assigned item {context.item_id} to {len(context.narrative_ids)} narratives"
        )

        return context

    async def _assign_to_narrative(
        self,
        context: PipelineContext,
        narrative_id: UUID,
        relevance: float,
        relationship: str,
    ) -> None:
        """
        Assign item to a narrative.

        Args:
            context: Pipeline context
            narrative_id: Narrative to assign to
            relevance: Relevance score
            relationship: Type of relationship
        """
        now = datetime.now(timezone.utc)

        # Link item to narrative
        query = text("""
            INSERT INTO narrative_items (narrative_id, item_id, relevance, relationship, created_at)
            VALUES (:narrative_id, :item_id, :relevance, :relationship, :created_at)
            ON CONFLICT (narrative_id, item_id) DO UPDATE
            SET relevance = :relevance, relationship = :relationship
        """)

        await self.db.execute(
            query,
            {
                "narrative_id": str(narrative_id),
                "item_id": str(context.item_id),
                "relevance": relevance,
                "relationship": relationship,
                "created_at": now,
            },
        )

        # Link claims to narrative
        for claim in context.claims:
            claim_id = claim.get("claim_id")
            if claim_id:
                claim_query = text("""
                    INSERT INTO narrative_claims (narrative_id, claim_id, created_at)
                    VALUES (:narrative_id, :claim_id, :created_at)
                    ON CONFLICT (narrative_id, claim_id) DO NOTHING
                """)

                await self.db.execute(
                    claim_query,
                    {
                        "narrative_id": str(narrative_id),
                        "claim_id": claim_id,
                        "created_at": now,
                    },
                )

        # Link event if present
        if context.event_id:
            event_query = text("""
                INSERT INTO narrative_events (narrative_id, event_id, created_at)
                VALUES (:narrative_id, :event_id, :created_at)
                ON CONFLICT (narrative_id, event_id) DO NOTHING
            """)

            await self.db.execute(
                event_query,
                {
                    "narrative_id": str(narrative_id),
                    "event_id": str(context.event_id),
                    "created_at": now,
                },
            )

        # Update narrative item count
        update_query = text("""
            UPDATE narratives
            SET item_count = (
                SELECT COUNT(*) FROM narrative_items WHERE narrative_id = :narrative_id
            ),
            updated_at = :updated_at
            WHERE id = :narrative_id
        """)

        await self.db.execute(
            update_query,
            {
                "narrative_id": str(narrative_id),
                "updated_at": now,
            },
        )

        await self.db.commit()

    async def _create_narrative_if_warranted(
        self,
        context: PipelineContext,
    ) -> Optional[UUID]:
        """
        Create a new narrative if there are enough related unclustered claims.

        Args:
            context: Pipeline context

        Returns:
            New narrative ID or None
        """
        entity_ids = [e.get("entity_id") for e in context.entities if e.get("entity_id")]

        # Find unclustered claims for these entities
        unclustered = await self.clusterer.find_unclustered_claims(
            entity_ids,
            lookback_days=14,
            limit=30,
        )

        # Add current claims
        all_claims = context.claims + unclustered

        if len(all_claims) < self.clusterer.min_cluster_size:
            return None

        # Generate narrative from claims
        events = []
        if context.event_id:
            # Fetch event details
            event_query = text("SELECT summary FROM events WHERE id = :event_id")
            result = await self.db.execute(event_query, {"event_id": str(context.event_id)})
            row = result.fetchone()
            if row:
                events = [{"summary": row[0]}]

        narrative_data = await self.analyzer.generate_narrative(
            all_claims,
            events,
            context.entities,
        )

        if not narrative_data or narrative_data.get("confidence", 0) < 0.7:
            return None

        # Create narrative
        narrative_id = await self._create_narrative(context, narrative_data)

        # Assign unclustered claims to new narrative
        for claim in unclustered:
            claim_query = text("""
                INSERT INTO narrative_claims (narrative_id, claim_id, created_at)
                VALUES (:narrative_id, :claim_id, :created_at)
                ON CONFLICT (narrative_id, claim_id) DO NOTHING
            """)

            await self.db.execute(
                claim_query,
                {
                    "narrative_id": str(narrative_id),
                    "claim_id": claim["id"],
                    "created_at": datetime.now(timezone.utc),
                },
            )

        await self.db.commit()

        return narrative_id

    async def _create_narrative(
        self,
        context: PipelineContext,
        narrative_data: dict[str, Any],
    ) -> UUID:
        """
        Create a new narrative record.

        Args:
            context: Pipeline context
            narrative_data: Generated narrative data

        Returns:
            New narrative ID
        """
        narrative_id = uuid4()
        now = datetime.now(timezone.utc)

        query = text("""
            INSERT INTO narratives (
                id, title, thesis, description, narrative_type,
                sentiment, key_actors, embedding, status,
                item_count, created_at, updated_at
            )
            VALUES (
                :id, :title, :thesis, :description, :narrative_type,
                :sentiment, :key_actors, :embedding, 'active',
                1, :created_at, :updated_at
            )
            RETURNING id
        """)

        await self.db.execute(
            query,
            {
                "id": str(narrative_id),
                "title": narrative_data.get("title", "Untitled Narrative"),
                "thesis": narrative_data.get("thesis", ""),
                "description": narrative_data.get("description", ""),
                "narrative_type": narrative_data.get("narrative_type", "development"),
                "sentiment": narrative_data.get("sentiment", "neutral"),
                "key_actors": narrative_data.get("key_actors", []),
                "embedding": context.embedding,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Link entities to narrative
        for entity in context.entities:
            entity_id = entity.get("entity_id")
            if entity_id:
                entity_query = text("""
                    INSERT INTO narrative_entities (narrative_id, entity_id, role, created_at)
                    VALUES (:narrative_id, :entity_id, 'involved', :created_at)
                    ON CONFLICT (narrative_id, entity_id) DO NOTHING
                """)

                await self.db.execute(
                    entity_query,
                    {
                        "narrative_id": str(narrative_id),
                        "entity_id": entity_id,
                        "created_at": now,
                    },
                )

        # Link item to narrative
        await self._assign_to_narrative(
            context,
            narrative_id,
            relevance=1.0,
            relationship="origin",
        )

        self.logger.info(
            f"Created new narrative {narrative_id}: {narrative_data.get('title', 'Untitled')}"
        )

        return narrative_id
