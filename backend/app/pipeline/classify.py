"""
Classify Stage

Performs classification and scoring:
- Sentiment analysis toward each linked subject
- Salience scoring (is subject central or incidental?)
- Topic tagging
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import anthropic
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


CLASSIFICATION_PROMPT = """You are an expert content classification system for a narrative intelligence platform.

Analyze the following text and provide:

1. **Sentiment Analysis**: For each entity mentioned, determine the sentiment of the content toward that entity.
   - Score from -1 (very negative) to 1 (very positive)
   - Consider both explicit statements and implicit tone

2. **Salience Scoring**: For each entity, determine how central they are to the content.
   - Score from 0 (incidental mention) to 1 (central focus)
   - Consider: frequency of mention, role in main narrative, headline presence

3. **Topic Classification**: Identify the main topics covered.
   - Use specific, hierarchical topics (e.g., "Technology > AI > Large Language Models")
   - Include both primary and secondary topics

<text>
{text}
</text>

<entities>
{entities}
</entities>

Respond with a JSON object:
```json
{{
  "entity_sentiments": {{
    "Entity Name": {{
      "sentiment": 0.5,
      "explanation": "Brief explanation of sentiment"
    }}
  }},
  "entity_salience": {{
    "Entity Name": {{
      "salience": 0.8,
      "role": "primary|secondary|mentioned"
    }}
  }},
  "topics": [
    {{
      "topic": "Category > Subcategory > Specific Topic",
      "confidence": 0.9,
      "is_primary": true
    }}
  ],
  "overall_sentiment": 0.2,
  "content_type": "news|analysis|opinion|press_release|report"
}}
```

Analyze now:"""


# Pre-defined topic taxonomy for consistency
TOPIC_TAXONOMY = {
    "Business": [
        "Mergers & Acquisitions",
        "Earnings & Financial Results",
        "Corporate Governance",
        "Executive Changes",
        "Strategy & Operations",
        "Bankruptcy & Restructuring",
    ],
    "Technology": [
        "Artificial Intelligence",
        "Cloud Computing",
        "Cybersecurity",
        "Software",
        "Hardware",
        "Semiconductors",
        "Internet & Social Media",
    ],
    "Finance": [
        "Banking",
        "Investment",
        "Markets",
        "Cryptocurrency",
        "Insurance",
        "Real Estate",
    ],
    "Politics": [
        "Elections",
        "Legislation",
        "International Relations",
        "Regulation",
        "Policy",
    ],
    "Legal": [
        "Litigation",
        "Regulatory Actions",
        "Compliance",
        "Intellectual Property",
    ],
    "Healthcare": [
        "Pharmaceuticals",
        "Biotechnology",
        "Healthcare Services",
        "Medical Devices",
    ],
    "Energy": [
        "Oil & Gas",
        "Renewable Energy",
        "Utilities",
        "Climate & Environment",
    ],
    "Economy": [
        "Macroeconomics",
        "Employment",
        "Inflation",
        "Trade",
    ],
}


class ClaudeClassifier:
    """
    Performs classification using Claude.
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

    async def classify(
        self,
        text: str,
        entities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Classify content for sentiment, salience, and topics.

        Args:
            text: Text to classify
            entities: Previously extracted entities

        Returns:
            Classification results
        """
        # Truncate text if too long
        max_input = 30000
        if len(text) > max_input:
            text = text[:max_input] + "\n\n[Text truncated...]"

        # Format entities for context
        entity_names = [e.get("name", "") for e in entities[:30]]
        entity_context = "\n".join([f"- {name}" for name in entity_names if name])

        prompt = CLASSIFICATION_PROMPT.format(
            text=text,
            entities=entity_context or "No entities extracted",
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_classification(content)

        except anthropic.RateLimitError as e:
            raise RetryableError(
                f"Claude rate limit: {e}",
                "classify",
                retry_after=60,
            )
        except anthropic.APIConnectionError as e:
            raise RetryableError(f"Claude connection error: {e}", "classify")
        except anthropic.APIError as e:
            raise NonRetryableError(f"Claude API error: {e}", "classify")

    def _parse_classification(self, response: str) -> dict[str, Any]:
        """
        Parse classification JSON from Claude response.

        Args:
            response: Raw response text

        Returns:
            Classification dictionary
        """
        # Extract JSON from markdown code block if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\{[\s\S]*\}", response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return self._default_classification()

        try:
            result = json.loads(json_str)
            return self._validate_classification(result)
        except json.JSONDecodeError:
            return self._default_classification()

    def _validate_classification(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize classification data."""
        # Validate sentiment scores
        sentiments = data.get("entity_sentiments", {})
        for entity, scores in sentiments.items():
            if isinstance(scores, dict):
                score = scores.get("sentiment", 0)
                scores["sentiment"] = max(-1, min(1, float(score)))

        # Validate salience scores
        salience = data.get("entity_salience", {})
        for entity, scores in salience.items():
            if isinstance(scores, dict):
                score = scores.get("salience", 0.5)
                scores["salience"] = max(0, min(1, float(score)))

        # Validate topics
        topics = data.get("topics", [])
        validated_topics = []
        for topic in topics:
            if isinstance(topic, dict) and topic.get("topic"):
                conf = topic.get("confidence", 0.5)
                topic["confidence"] = max(0, min(1, float(conf)))
                validated_topics.append(topic)
        data["topics"] = validated_topics

        # Validate overall sentiment
        overall = data.get("overall_sentiment", 0)
        data["overall_sentiment"] = max(-1, min(1, float(overall)))

        return data

    def _default_classification(self) -> dict[str, Any]:
        """Return default classification when parsing fails."""
        return {
            "entity_sentiments": {},
            "entity_salience": {},
            "topics": [],
            "overall_sentiment": 0,
            "content_type": "unknown",
        }


class ClassifyStage(PipelineStage):
    """
    Pipeline stage for content classification.

    Performs sentiment analysis, salience scoring, and topic tagging.
    """

    stage_name = "classify"
    next_stage = "event"

    def __init__(
        self,
        redis_client: redis.Redis,
        db_session: AsyncSession,
        config: Optional[dict[str, Any]] = None,
    ):
        super().__init__(redis_client, db_session, config)

        # Initialize Claude classifier
        api_key = self.config.get("anthropic_api_key")
        if not api_key and settings.anthropic_api_key:
            api_key = settings.anthropic_api_key.get_secret_value()

        if not api_key:
            raise ValueError("Anthropic API key required for classification")

        self.classifier = ClaudeClassifier(
            api_key=api_key,
            model=self.config.get("model", settings.anthropic_model),
        )

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Classify item content.

        Args:
            context: Pipeline context with clean_text and entities

        Returns:
            Updated context with classification data
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for classification",
                self.stage_name,
                context.item_id,
            )

        # Perform classification
        try:
            classification = await self.classifier.classify(
                context.clean_text,
                context.entities,
            )
        except RetryableError:
            raise
        except NonRetryableError:
            raise
        except Exception as e:
            raise RetryableError(
                f"Classification failed: {e}",
                self.stage_name,
                context.item_id,
            )

        # Update context with classification results
        context.sentiment_scores = {
            entity: scores.get("sentiment", 0)
            for entity, scores in classification.get("entity_sentiments", {}).items()
        }

        context.salience_scores = {
            entity: scores.get("salience", 0.5)
            for entity, scores in classification.get("entity_salience", {}).items()
        }

        context.topics = [
            t.get("topic", "")
            for t in classification.get("topics", [])
            if t.get("topic")
        ]

        # Store classification in database
        await self._store_classification(context, classification)

        # Update entity links with sentiment/salience
        await self._update_entity_links(context, classification)

        self.logger.info(
            f"Classified item {context.item_id}: "
            f"topics={len(context.topics)}, "
            f"sentiment={classification.get('overall_sentiment', 0):.2f}"
        )

        return context

    async def _store_classification(
        self,
        context: PipelineContext,
        classification: dict[str, Any],
    ) -> None:
        """
        Store classification results in the database.

        Args:
            context: Pipeline context
            classification: Classification results
        """
        try:
            # Update item with classification data
            topics_json = json.dumps(context.topics)

            query = text("""
                UPDATE items
                SET topics = :topics,
                    overall_sentiment = :sentiment,
                    content_type = :content_type,
                    updated_at = :updated_at
                WHERE id = :item_id
            """)

            await self.db.execute(
                query,
                {
                    "item_id": str(context.item_id),
                    "topics": topics_json,
                    "sentiment": classification.get("overall_sentiment", 0),
                    "content_type": classification.get("content_type", "unknown"),
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            await self.db.commit()

        except Exception as e:
            self.logger.error(f"Failed to store classification: {e}")
            await self.db.rollback()

    async def _update_entity_links(
        self,
        context: PipelineContext,
        classification: dict[str, Any],
    ) -> None:
        """
        Update entity links with sentiment and salience scores.

        Args:
            context: Pipeline context
            classification: Classification results
        """
        try:
            sentiments = classification.get("entity_sentiments", {})
            salience = classification.get("entity_salience", {})

            for entity in context.entities:
                entity_name = entity.get("name", "")
                entity_id = entity.get("entity_id")

                if not entity_id:
                    continue

                # Get scores for this entity (try exact match first, then fuzzy)
                sentiment_score = self._get_score_for_entity(
                    entity_name, sentiments, "sentiment"
                )
                salience_score = self._get_score_for_entity(
                    entity_name, salience, "salience"
                )

                if sentiment_score is not None or salience_score is not None:
                    query = text("""
                        UPDATE item_entities
                        SET sentiment = COALESCE(:sentiment, sentiment),
                            salience = COALESCE(:salience, salience)
                        WHERE item_id = :item_id AND entity_id = :entity_id
                    """)

                    await self.db.execute(
                        query,
                        {
                            "item_id": str(context.item_id),
                            "entity_id": entity_id,
                            "sentiment": sentiment_score,
                            "salience": salience_score,
                        },
                    )

            await self.db.commit()

        except Exception as e:
            self.logger.error(f"Failed to update entity links: {e}")
            await self.db.rollback()

    def _get_score_for_entity(
        self,
        entity_name: str,
        scores: dict[str, Any],
        score_key: str,
    ) -> Optional[float]:
        """
        Get a score for an entity, handling fuzzy matching.

        Args:
            entity_name: Entity name to look up
            scores: Score dictionary
            score_key: Key within score dict to extract

        Returns:
            Score value or None
        """
        # Try exact match
        if entity_name in scores:
            entry = scores[entity_name]
            if isinstance(entry, dict):
                return entry.get(score_key)
            return entry

        # Try case-insensitive match
        entity_lower = entity_name.lower()
        for name, entry in scores.items():
            if name.lower() == entity_lower:
                if isinstance(entry, dict):
                    return entry.get(score_key)
                return entry

        # Try partial match
        for name, entry in scores.items():
            if entity_lower in name.lower() or name.lower() in entity_lower:
                if isinstance(entry, dict):
                    return entry.get(score_key)
                return entry

        return None

    def normalize_topic(self, topic: str) -> str:
        """
        Normalize a topic to match the taxonomy.

        Args:
            topic: Raw topic string

        Returns:
            Normalized topic string
        """
        # Split hierarchical topic
        parts = [p.strip() for p in topic.split(">")]

        if not parts:
            return topic

        # Check if top-level matches taxonomy
        top_level = parts[0]
        for category in TOPIC_TAXONOMY:
            if category.lower() == top_level.lower():
                parts[0] = category
                break

        return " > ".join(parts)
