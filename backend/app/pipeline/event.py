"""
Event Detection Stage

Detects and clusters events from items:
- Cluster Items describing the same occurrence
- Create or update Event with cluster as evidence
- Extract event time, location, entities involved
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


EVENT_EXTRACTION_PROMPT = """You are an expert event extraction system for a narrative intelligence platform.

Analyze the following text and identify the primary event being described.

For the main event, provide:
1. summary: A concise summary of what happened (1-2 sentences)
2. event_type: Type of event (announcement, acquisition, lawsuit, earnings, appointment, resignation, partnership, product_launch, regulatory_action, other)
3. event_date: When the event occurred (ISO format if extractable, otherwise "unknown")
4. location: Where the event occurred (if applicable)
5. entities_involved: Key entities involved in the event
6. significance: How significant is this event (high, medium, low)
7. keywords: Key terms for matching similar events

<text>
{text}
</text>

<metadata>
Title: {title}
Published: {published_at}
Entities: {entities}
</metadata>

Respond with a JSON object:
```json
{{
  "has_event": true,
  "summary": "Brief summary of the event",
  "event_type": "announcement",
  "event_date": "2024-01-15T10:00:00Z",
  "location": "New York, USA",
  "entities_involved": ["Entity 1", "Entity 2"],
  "significance": "high",
  "keywords": ["keyword1", "keyword2"]
}}
```

If no specific event is being described (e.g., general analysis, opinion piece), set "has_event": false.

Analyze now:"""


class ClaudeEventExtractor:
    """
    Extracts event information from text using Claude.
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

    async def extract(
        self,
        text: str,
        title: Optional[str],
        published_at: Optional[datetime],
        entities: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """
        Extract event information from text.

        Args:
            text: Text to analyze
            title: Article title
            published_at: Publication date
            entities: Extracted entities

        Returns:
            Event data or None if no event found
        """
        # Truncate text if too long
        max_input = 20000
        if len(text) > max_input:
            text = text[:max_input] + "\n\n[Text truncated...]"

        entity_names = [e.get("name", "") for e in entities[:20]]

        prompt = EVENT_EXTRACTION_PROMPT.format(
            text=text,
            title=title or "Unknown",
            published_at=published_at.isoformat() if published_at else "Unknown",
            entities=", ".join(entity_names) or "None extracted",
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_event(content)

        except anthropic.RateLimitError as e:
            raise RetryableError(
                f"Claude rate limit: {e}",
                "event",
                retry_after=60,
            )
        except anthropic.APIConnectionError as e:
            raise RetryableError(f"Claude connection error: {e}", "event")
        except anthropic.APIError as e:
            raise NonRetryableError(f"Claude API error: {e}", "event")

    def _parse_event(self, response: str) -> Optional[dict[str, Any]]:
        """Parse event JSON from Claude response."""
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

            if not data.get("has_event", False):
                return None

            return self._validate_event(data)

        except json.JSONDecodeError:
            return None

    def _validate_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize event data."""
        # Parse event date
        event_date = data.get("event_date")
        if event_date and event_date != "unknown":
            try:
                if isinstance(event_date, str):
                    # Try various date formats
                    for fmt in [
                        "%Y-%m-%dT%H:%M:%SZ",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d",
                    ]:
                        try:
                            data["event_date"] = datetime.strptime(event_date, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        data["event_date"] = None
            except Exception:
                data["event_date"] = None
        else:
            data["event_date"] = None

        # Ensure entities is a list
        if not isinstance(data.get("entities_involved"), list):
            data["entities_involved"] = []

        # Ensure keywords is a list
        if not isinstance(data.get("keywords"), list):
            data["keywords"] = []

        return data


class EventClusterer:
    """
    Clusters items into events based on similarity.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        redis_client: redis.Redis,
        similarity_threshold: float = 0.85,
        time_window_hours: int = 72,
    ):
        self.db = db_session
        self.redis = redis_client
        self.similarity_threshold = similarity_threshold
        self.time_window = timedelta(hours=time_window_hours)

    async def find_matching_event(
        self,
        event_data: dict[str, Any],
        embedding: Optional[list[float]],
        published_at: Optional[datetime],
    ) -> Optional[UUID]:
        """
        Find an existing event that matches this item.

        Args:
            event_data: Extracted event data
            embedding: Item embedding
            published_at: Publication date

        Returns:
            Event ID if match found, None otherwise
        """
        if not embedding:
            return await self._match_by_keywords(event_data, published_at)

        # Calculate time bounds
        if published_at:
            start_time = published_at - self.time_window
            end_time = published_at + self.time_window
        else:
            now = datetime.now(timezone.utc)
            start_time = now - self.time_window
            end_time = now + self.time_window

        # Find similar events by embedding
        query = text("""
            SELECT e.id, e.summary, 1 - (e.embedding <=> :embedding) as similarity
            FROM events e
            WHERE e.embedding IS NOT NULL
            AND e.event_date >= :start_time
            AND e.event_date <= :end_time
            AND e.event_type = :event_type
            ORDER BY e.embedding <=> :embedding
            LIMIT 5
        """)

        result = await self.db.execute(
            query,
            {
                "embedding": embedding,
                "start_time": start_time,
                "end_time": end_time,
                "event_type": event_data.get("event_type", "other"),
            },
        )

        rows = result.fetchall()

        for row in rows:
            event_id, summary, similarity = row
            if similarity >= self.similarity_threshold:
                # Verify keyword overlap
                if await self._verify_keyword_match(event_id, event_data):
                    return UUID(str(event_id))

        return None

    async def _match_by_keywords(
        self,
        event_data: dict[str, Any],
        published_at: Optional[datetime],
    ) -> Optional[UUID]:
        """
        Match event by keywords when no embedding available.

        Args:
            event_data: Extracted event data
            published_at: Publication date

        Returns:
            Event ID if match found
        """
        keywords = event_data.get("keywords", [])
        if not keywords:
            return None

        # Calculate time bounds
        if published_at:
            start_time = published_at - self.time_window
            end_time = published_at + self.time_window
        else:
            now = datetime.now(timezone.utc)
            start_time = now - self.time_window
            end_time = now + self.time_window

        # Search for events with matching keywords
        query = text("""
            SELECT id, keywords
            FROM events
            WHERE event_date >= :start_time
            AND event_date <= :end_time
            AND event_type = :event_type
        """)

        result = await self.db.execute(
            query,
            {
                "start_time": start_time,
                "end_time": end_time,
                "event_type": event_data.get("event_type", "other"),
            },
        )

        rows = result.fetchall()

        keywords_set = set(k.lower() for k in keywords)

        for row in rows:
            event_id, event_keywords = row
            if event_keywords:
                event_keywords_set = set(k.lower() for k in event_keywords)
                overlap = len(keywords_set & event_keywords_set)
                if overlap >= 2:  # At least 2 matching keywords
                    return UUID(str(event_id))

        return None

    async def _verify_keyword_match(
        self,
        event_id: UUID,
        event_data: dict[str, Any],
    ) -> bool:
        """
        Verify that keywords match sufficiently.

        Args:
            event_id: Candidate event ID
            event_data: New event data

        Returns:
            True if keywords match sufficiently
        """
        query = text("SELECT keywords FROM events WHERE id = :event_id")
        result = await self.db.execute(query, {"event_id": str(event_id)})
        row = result.fetchone()

        if not row or not row[0]:
            return True  # No keywords to compare, accept based on embedding

        existing_keywords = set(k.lower() for k in row[0])
        new_keywords = set(k.lower() for k in event_data.get("keywords", []))

        # Require at least some overlap
        overlap = len(existing_keywords & new_keywords)
        return overlap >= 1


class EventDetectionStage(PipelineStage):
    """
    Pipeline stage for event detection and clustering.

    Detects events from content, clusters related items,
    and maintains event records.
    """

    stage_name = "event"
    next_stage = "narrative"

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
            raise ValueError("Anthropic API key required for event detection")

        self.extractor = ClaudeEventExtractor(
            api_key=api_key,
            model=self.config.get("model", settings.anthropic_model),
        )

        # Initialize clusterer
        self.clusterer = EventClusterer(
            db_session=db_session,
            redis_client=redis_client,
            similarity_threshold=self.config.get("similarity_threshold", 0.85),
            time_window_hours=self.config.get("time_window_hours", 72),
        )

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Detect and cluster events from item content.

        Args:
            context: Pipeline context with clean_text, entities, embedding

        Returns:
            Updated context with event_id
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for event detection",
                self.stage_name,
                context.item_id,
            )

        # Extract event information
        try:
            event_data = await self.extractor.extract(
                context.clean_text,
                context.title,
                context.published_at,
                context.entities,
            )
        except RetryableError:
            raise
        except NonRetryableError:
            raise
        except Exception as e:
            raise RetryableError(
                f"Event extraction failed: {e}",
                self.stage_name,
                context.item_id,
            )

        if not event_data:
            self.logger.debug(f"No event detected in item {context.item_id}")
            return context

        # Try to find matching existing event
        matching_event = await self.clusterer.find_matching_event(
            event_data,
            context.embedding,
            context.published_at,
        )

        if matching_event:
            # Add item to existing event
            context.event_id = matching_event
            await self._add_item_to_event(context, matching_event)
            self.logger.info(
                f"Added item {context.item_id} to existing event {matching_event}"
            )
        else:
            # Create new event
            event_id = await self._create_event(context, event_data)
            context.event_id = event_id
            self.logger.info(
                f"Created new event {event_id} from item {context.item_id}"
            )

        return context

    async def _create_event(
        self,
        context: PipelineContext,
        event_data: dict[str, Any],
    ) -> UUID:
        """
        Create a new event record.

        Args:
            context: Pipeline context
            event_data: Extracted event data

        Returns:
            New event ID
        """
        event_id = uuid4()
        now = datetime.now(timezone.utc)

        # Determine event date
        event_date = event_data.get("event_date")
        if not event_date:
            event_date = context.published_at or now

        # Link entities to event
        entities_involved = event_data.get("entities_involved", [])
        entity_ids = await self._resolve_entity_ids(entities_involved, context.entities)

        query = text("""
            INSERT INTO events (
                id, summary, event_type, event_date, location,
                keywords, significance, embedding, created_at, updated_at
            )
            VALUES (
                :id, :summary, :event_type, :event_date, :location,
                :keywords, :significance, :embedding, :created_at, :updated_at
            )
            RETURNING id
        """)

        await self.db.execute(
            query,
            {
                "id": str(event_id),
                "summary": event_data.get("summary", ""),
                "event_type": event_data.get("event_type", "other"),
                "event_date": event_date,
                "location": event_data.get("location"),
                "keywords": event_data.get("keywords", []),
                "significance": event_data.get("significance", "medium"),
                "embedding": context.embedding,
                "created_at": now,
                "updated_at": now,
            },
        )

        # Link item to event
        await self._add_item_to_event(context, event_id)

        # Link entities to event
        for entity_id in entity_ids:
            await self._link_entity_to_event(event_id, entity_id)

        await self.db.commit()

        return event_id

    async def _add_item_to_event(
        self,
        context: PipelineContext,
        event_id: UUID,
    ) -> None:
        """
        Add an item as evidence for an event.

        Args:
            context: Pipeline context
            event_id: Event ID
        """
        query = text("""
            INSERT INTO event_items (event_id, item_id, created_at)
            VALUES (:event_id, :item_id, :created_at)
            ON CONFLICT (event_id, item_id) DO NOTHING
        """)

        await self.db.execute(
            query,
            {
                "event_id": str(event_id),
                "item_id": str(context.item_id),
                "created_at": datetime.now(timezone.utc),
            },
        )

        # Update event with new evidence count
        update_query = text("""
            UPDATE events
            SET evidence_count = (
                SELECT COUNT(*) FROM event_items WHERE event_id = :event_id
            ),
            updated_at = :updated_at
            WHERE id = :event_id
        """)

        await self.db.execute(
            update_query,
            {
                "event_id": str(event_id),
                "updated_at": datetime.now(timezone.utc),
            },
        )

    async def _link_entity_to_event(
        self,
        event_id: UUID,
        entity_id: str,
    ) -> None:
        """
        Link an entity to an event.

        Args:
            event_id: Event ID
            entity_id: Entity ID
        """
        query = text("""
            INSERT INTO event_entities (event_id, entity_id, created_at)
            VALUES (:event_id, :entity_id, :created_at)
            ON CONFLICT (event_id, entity_id) DO NOTHING
        """)

        await self.db.execute(
            query,
            {
                "event_id": str(event_id),
                "entity_id": entity_id,
                "created_at": datetime.now(timezone.utc),
            },
        )

    async def _resolve_entity_ids(
        self,
        entity_names: list[str],
        context_entities: list[dict[str, Any]],
    ) -> list[str]:
        """
        Resolve entity names to IDs from context.

        Args:
            entity_names: Names from event extraction
            context_entities: Entities from context

        Returns:
            List of entity IDs
        """
        # Build lookup from context entities
        lookup: dict[str, str] = {}
        for entity in context_entities:
            name = entity.get("name", "").lower()
            entity_id = entity.get("entity_id")
            if name and entity_id:
                lookup[name] = entity_id

        # Resolve names to IDs
        resolved = []
        for name in entity_names:
            name_lower = name.lower()

            # Try exact match
            if name_lower in lookup:
                resolved.append(lookup[name_lower])
                continue

            # Try partial match
            for key, entity_id in lookup.items():
                if name_lower in key or key in name_lower:
                    resolved.append(entity_id)
                    break

        return resolved
