"""
Claim Extraction Stage

Extracts atomic claims from content:
- Extract atomic Claims using Claude
- Each claim has: subject (who), predicate, object (what)
- Determine stance (supports|contradicts|neutral)
- Assign polarity (-1 to 1) and confidence
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional, Literal
from uuid import UUID, uuid4

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


StanceType = Literal["supports", "contradicts", "neutral"]


CLAIM_EXTRACTION_PROMPT = """You are an expert claim extraction system for a narrative intelligence platform.

Extract all discrete, atomic claims from the following text. A claim is a single assertion that can be verified or disputed.

For each claim, provide:
1. subject: Who or what is making or is the subject of the claim (entity name)
2. predicate: The action or relationship (verb phrase)
3. object: What the claim is about (the assertion itself)
4. quote: The exact text from which this claim was extracted
5. stance: How this source treats the claim:
   - "supports" - The source presents this as true or agrees with it
   - "contradicts" - The source disputes or argues against this
   - "neutral" - The source reports without taking a position
6. polarity: Sentiment of the claim from -1 (very negative) to 1 (very positive)
7. confidence: Your confidence in this extraction from 0 to 1

Focus on:
- Factual assertions that can be verified
- Statements of position, policy, or intent
- Predictions or forward-looking statements
- Accusations, allegations, or denials
- Statistics, figures, or quantitative claims

Skip:
- General background information
- Definitions or explanations
- Hypotheticals clearly labeled as such

<text>
{text}
</text>

<entities>
{entities}
</entities>

Respond with a JSON array of claims:
```json
[
  {{
    "subject": "Entity making or subject of claim",
    "predicate": "action or relationship",
    "object": "what is being claimed",
    "quote": "exact supporting text",
    "stance": "supports|contradicts|neutral",
    "polarity": 0.0,
    "confidence": 0.9
  }}
]
```

Extract claims now:"""


class ClaudeClaimExtractor:
    """
    Extracts claims from text using Claude.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 8192,
    ):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    async def extract(
        self,
        text: str,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Extract claims from text.

        Args:
            text: Text to extract claims from
            entities: Previously extracted entities for context

        Returns:
            List of claim dictionaries
        """
        # Truncate text if too long
        max_input = 40000
        if len(text) > max_input:
            text = text[:max_input] + "\n\n[Text truncated...]"

        # Format entities for context
        entity_context = "\n".join([
            f"- {e.get('name')} ({e.get('type', 'UNKNOWN')})"
            for e in entities[:30]  # Limit entity context
        ]) or "No entities extracted"

        prompt = CLAIM_EXTRACTION_PROMPT.format(
            text=text,
            entities=entity_context,
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text
            return self._parse_claims(content)

        except anthropic.RateLimitError as e:
            raise RetryableError(
                f"Claude rate limit: {e}",
                "claim",
                retry_after=60,
            )
        except anthropic.APIConnectionError as e:
            raise RetryableError(f"Claude connection error: {e}", "claim")
        except anthropic.APIError as e:
            raise NonRetryableError(f"Claude API error: {e}", "claim")

    def _parse_claims(self, response: str) -> list[dict[str, Any]]:
        """
        Parse claim JSON from Claude response.

        Args:
            response: Raw response text

        Returns:
            List of claim dictionaries
        """
        # Extract JSON from markdown code block if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r"\[[\s\S]*\]", response)
            if json_match:
                json_str = json_match.group(0)
            else:
                return []

        try:
            claims = json.loads(json_str)
            if not isinstance(claims, list):
                return []

            # Validate and normalize claims
            validated = []
            for claim in claims:
                if self._validate_claim(claim):
                    validated.append(self._normalize_claim(claim))

            return validated

        except json.JSONDecodeError:
            return []

    def _validate_claim(self, claim: dict[str, Any]) -> bool:
        """Check if claim has required fields."""
        required = ["subject", "predicate", "object"]
        return all(claim.get(field) for field in required)

    def _normalize_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        """Normalize claim values."""
        # Ensure stance is valid
        stance = claim.get("stance", "neutral").lower()
        if stance not in ("supports", "contradicts", "neutral"):
            stance = "neutral"

        # Clamp polarity to [-1, 1]
        polarity = claim.get("polarity", 0)
        try:
            polarity = max(-1, min(1, float(polarity)))
        except (TypeError, ValueError):
            polarity = 0

        # Clamp confidence to [0, 1]
        confidence = claim.get("confidence", 0.8)
        try:
            confidence = max(0, min(1, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.8

        return {
            "subject": str(claim["subject"]).strip(),
            "predicate": str(claim["predicate"]).strip(),
            "object": str(claim["object"]).strip(),
            "quote": str(claim.get("quote", "")).strip(),
            "stance": stance,
            "polarity": polarity,
            "confidence": confidence,
        }


class ClaimExtractionStage(PipelineStage):
    """
    Pipeline stage for claim extraction.

    Extracts atomic claims from content using Claude,
    with subject-predicate-object structure.
    """

    stage_name = "claim"
    next_stage = "classify"

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
            raise ValueError("Anthropic API key required for claim extraction")

        self.extractor = ClaudeClaimExtractor(
            api_key=api_key,
            model=self.config.get("model", settings.anthropic_model),
        )

        # Configuration
        self.min_confidence = self.config.get("min_confidence", 0.5)
        self.max_claims = self.config.get("max_claims", 100)

    async def process(self, context: PipelineContext) -> PipelineContext:
        """
        Extract claims from item content.

        Args:
            context: Pipeline context with clean_text and entities

        Returns:
            Updated context with claims
        """
        if not context.clean_text:
            raise NonRetryableError(
                "No clean text for claim extraction",
                self.stage_name,
                context.item_id,
            )

        # Extract claims using Claude
        try:
            raw_claims = await self.extractor.extract(
                context.clean_text,
                context.entities,
            )
        except RetryableError:
            raise
        except NonRetryableError:
            raise
        except Exception as e:
            raise RetryableError(
                f"Claim extraction failed: {e}",
                self.stage_name,
                context.item_id,
            )

        # Filter claims by confidence
        filtered_claims = [
            c for c in raw_claims
            if c.get("confidence", 0) >= self.min_confidence
        ][:self.max_claims]

        # Link claims to entities
        linked_claims = await self._link_claims_to_entities(
            filtered_claims,
            context.entities,
        )

        # Store claims in database
        stored_claims = await self._store_claims(context, linked_claims)

        context.claims = stored_claims

        self.logger.info(
            f"Extracted {len(stored_claims)} claims from item {context.item_id}"
        )

        return context

    async def _link_claims_to_entities(
        self,
        claims: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Link claim subjects to extracted entities.

        Args:
            claims: Extracted claims
            entities: Extracted entities

        Returns:
            Claims with entity_id links
        """
        # Build entity lookup by name (case-insensitive)
        entity_lookup: dict[str, str] = {}
        for entity in entities:
            name = entity.get("name", "").lower()
            entity_id = entity.get("entity_id")
            if name and entity_id:
                entity_lookup[name] = entity_id
                # Also add aliases
                for alias in entity.get("aliases", []):
                    entity_lookup[alias.lower()] = entity_id

        # Link claims to entities
        for claim in claims:
            subject = claim.get("subject", "").lower()

            # Try exact match first
            if subject in entity_lookup:
                claim["subject_entity_id"] = entity_lookup[subject]
            else:
                # Try partial match
                for name, entity_id in entity_lookup.items():
                    if name in subject or subject in name:
                        claim["subject_entity_id"] = entity_id
                        break

        return claims

    async def _store_claims(
        self,
        context: PipelineContext,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Store claims in the database.

        Args:
            context: Pipeline context
            claims: Claims to store

        Returns:
            Claims with assigned IDs
        """
        stored = []

        for claim in claims:
            try:
                claim_id = uuid4()

                query = text("""
                    INSERT INTO claims (
                        id, item_id, subject, predicate, object,
                        quote, stance, polarity, confidence,
                        subject_entity_id, created_at, updated_at
                    )
                    VALUES (
                        :id, :item_id, :subject, :predicate, :object,
                        :quote, :stance, :polarity, :confidence,
                        :subject_entity_id, :created_at, :updated_at
                    )
                    RETURNING id
                """)

                now = datetime.now(timezone.utc)
                await self.db.execute(
                    query,
                    {
                        "id": str(claim_id),
                        "item_id": str(context.item_id),
                        "subject": claim["subject"],
                        "predicate": claim["predicate"],
                        "object": claim["object"],
                        "quote": claim.get("quote", ""),
                        "stance": claim["stance"],
                        "polarity": claim["polarity"],
                        "confidence": claim["confidence"],
                        "subject_entity_id": claim.get("subject_entity_id"),
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                claim["claim_id"] = str(claim_id)
                stored.append(claim)

            except Exception as e:
                self.logger.warning(f"Failed to store claim: {e}")
                continue

        await self.db.commit()
        return stored

    async def analyze_claim_relationships(
        self,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Analyze relationships between claims (supports/contradicts).

        This can be called as a post-processing step to find
        claims that support or contradict each other.

        Args:
            claims: List of claims to analyze

        Returns:
            Claims with relationship metadata
        """
        # Group claims by subject
        by_subject: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            subject = claim.get("subject", "").lower()
            if subject not in by_subject:
                by_subject[subject] = []
            by_subject[subject].append(claim)

        # Find potential contradictions within same subject
        for subject, subject_claims in by_subject.items():
            if len(subject_claims) < 2:
                continue

            for i, claim1 in enumerate(subject_claims):
                for claim2 in subject_claims[i + 1:]:
                    # Check for opposing polarities
                    pol1 = claim1.get("polarity", 0)
                    pol2 = claim2.get("polarity", 0)

                    if pol1 * pol2 < 0:  # Opposite signs
                        # Mark as potentially contradictory
                        if "contradicts" not in claim1:
                            claim1["contradicts"] = []
                        if "contradicts" not in claim2:
                            claim2["contradicts"] = []

                        claim1["contradicts"].append(claim2.get("claim_id"))
                        claim2["contradicts"].append(claim1.get("claim_id"))

        return claims
