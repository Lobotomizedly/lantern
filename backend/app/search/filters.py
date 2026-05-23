"""
Search filters for the Lantern search system.

This module provides filter classes for narrowing search results by
various criteria including subject, source, date, reliability, sentiment,
narrative, and entity filters.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class SentimentValue(str, Enum):
    """Sentiment filter values."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class ReliabilityTier(str, Enum):
    """Source reliability tiers."""

    T1 = "T1"  # Most reliable (e.g., official documents, major wire services)
    T2 = "T2"  # Reliable (e.g., established news organizations)
    T3 = "T3"  # Generally reliable (e.g., regional media)
    T4 = "T4"  # Less reliable (e.g., blogs, opinion sites)
    T5 = "T5"  # Unverified (e.g., social media, anonymous sources)


@dataclass
class SubjectFilter:
    """Filter by subject (investigation target)."""

    subject_ids: list[UUID] = field(default_factory=list)

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return len(self.subject_ids) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"subject_ids": [str(sid) for sid in self.subject_ids]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubjectFilter":
        """Create from dictionary."""
        return cls(
            subject_ids=[UUID(sid) for sid in data.get("subject_ids", [])]
        )


@dataclass
class SourceFilter:
    """Filter by content source."""

    source_ids: list[UUID] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)  # Alternative: filter by name

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return len(self.source_ids) > 0 or len(self.source_names) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_ids": [str(sid) for sid in self.source_ids],
            "source_names": self.source_names,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceFilter":
        """Create from dictionary."""
        return cls(
            source_ids=[UUID(sid) for sid in data.get("source_ids", [])],
            source_names=data.get("source_names", []),
        )


@dataclass
class DateRangeFilter:
    """Filter by date range."""

    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return self.date_from is not None or self.date_to is not None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DateRangeFilter":
        """Create from dictionary."""
        date_from = None
        date_to = None

        if data.get("date_from"):
            date_from = datetime.fromisoformat(data["date_from"].replace("Z", "+00:00"))
        if data.get("date_to"):
            date_to = datetime.fromisoformat(data["date_to"].replace("Z", "+00:00"))

        return cls(date_from=date_from, date_to=date_to)

    @classmethod
    def last_n_days(cls, days: int) -> "DateRangeFilter":
        """Create a filter for the last N days."""
        return cls(
            date_from=datetime.utcnow() - timedelta(days=days),
            date_to=datetime.utcnow(),
        )

    @classmethod
    def last_week(cls) -> "DateRangeFilter":
        """Create a filter for the last week."""
        return cls.last_n_days(7)

    @classmethod
    def last_month(cls) -> "DateRangeFilter":
        """Create a filter for the last month."""
        return cls.last_n_days(30)

    @classmethod
    def last_year(cls) -> "DateRangeFilter":
        """Create a filter for the last year."""
        return cls.last_n_days(365)


@dataclass
class ReliabilityTierFilter:
    """Filter by source reliability tier."""

    tiers: list[str] = field(default_factory=list)
    minimum_tier: Optional[str] = None  # e.g., "T2" means T1 and T2

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return len(self.tiers) > 0 or self.minimum_tier is not None

    def get_effective_tiers(self) -> list[str]:
        """Get the list of tiers to filter by, considering minimum_tier."""
        if self.tiers:
            return self.tiers

        if self.minimum_tier:
            tier_order = ["T1", "T2", "T3", "T4", "T5"]
            try:
                idx = tier_order.index(self.minimum_tier)
                return tier_order[: idx + 1]
            except ValueError:
                logger.warning(f"Unknown tier: {self.minimum_tier}")
                return []

        return []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tiers": self.tiers,
            "minimum_tier": self.minimum_tier,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReliabilityTierFilter":
        """Create from dictionary."""
        return cls(
            tiers=data.get("tiers", []),
            minimum_tier=data.get("minimum_tier"),
        )


@dataclass
class SentimentFilter:
    """Filter by sentiment analysis results."""

    sentiments: list[SentimentValue] = field(default_factory=list)
    min_score: Optional[float] = None  # Minimum sentiment score (0-1)
    max_score: Optional[float] = None  # Maximum sentiment score (0-1)

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return (
            len(self.sentiments) > 0
            or self.min_score is not None
            or self.max_score is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "sentiments": [s.value for s in self.sentiments],
            "min_score": self.min_score,
            "max_score": self.max_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SentimentFilter":
        """Create from dictionary."""
        return cls(
            sentiments=[SentimentValue(s) for s in data.get("sentiments", [])],
            min_score=data.get("min_score"),
            max_score=data.get("max_score"),
        )


@dataclass
class NarrativeFilter:
    """Filter by narrative membership."""

    narrative_ids: list[UUID] = field(default_factory=list)
    exclude_narrative_ids: list[UUID] = field(default_factory=list)

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return len(self.narrative_ids) > 0 or len(self.exclude_narrative_ids) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "narrative_ids": [str(nid) for nid in self.narrative_ids],
            "exclude_narrative_ids": [str(nid) for nid in self.exclude_narrative_ids],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NarrativeFilter":
        """Create from dictionary."""
        return cls(
            narrative_ids=[UUID(nid) for nid in data.get("narrative_ids", [])],
            exclude_narrative_ids=[UUID(nid) for nid in data.get("exclude_narrative_ids", [])],
        )


@dataclass
class EntityFilter:
    """Filter by entity mentions."""

    entity_ids: list[UUID] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)  # Alternative: filter by name
    entity_types: list[str] = field(default_factory=list)  # e.g., ["person", "organization"]
    require_all: bool = False  # If True, require all entities to be present

    def is_active(self) -> bool:
        """Check if this filter is active."""
        return (
            len(self.entity_ids) > 0
            or len(self.entity_names) > 0
            or len(self.entity_types) > 0
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "entity_ids": [str(eid) for eid in self.entity_ids],
            "entity_names": self.entity_names,
            "entity_types": self.entity_types,
            "require_all": self.require_all,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityFilter":
        """Create from dictionary."""
        return cls(
            entity_ids=[UUID(eid) for eid in data.get("entity_ids", [])],
            entity_names=data.get("entity_names", []),
            entity_types=data.get("entity_types", []),
            require_all=data.get("require_all", False),
        )


class SearchFilters(BaseModel):
    """
    Combined search filters.

    This class aggregates all filter types and provides methods for
    combining them with AND logic.
    """

    # Subject filter
    subject_ids: Optional[list[UUID]] = Field(default=None, description="Filter by subject IDs")

    # Source filter
    source_ids: Optional[list[UUID]] = Field(default=None, description="Filter by source IDs")
    source_names: Optional[list[str]] = Field(default=None, description="Filter by source names")

    # Date filter
    date_from: Optional[datetime] = Field(default=None, description="Filter by date (from)")
    date_to: Optional[datetime] = Field(default=None, description="Filter by date (to)")

    # Reliability filter
    reliability_tiers: Optional[list[str]] = Field(
        default=None, description="Filter by reliability tiers"
    )
    min_reliability_tier: Optional[str] = Field(
        default=None, description="Minimum reliability tier"
    )

    # Sentiment filter
    sentiments: Optional[list[str]] = Field(default=None, description="Filter by sentiments")

    # Narrative filter
    narrative_ids: Optional[list[UUID]] = Field(
        default=None, description="Filter by narrative IDs"
    )

    # Entity filter
    entity_ids: Optional[list[UUID]] = Field(default=None, description="Filter by entity IDs")
    entity_names: Optional[list[str]] = Field(default=None, description="Filter by entity names")
    entity_types: Optional[list[str]] = Field(default=None, description="Filter by entity types")

    @field_validator("reliability_tiers", mode="before")
    @classmethod
    def validate_reliability_tiers(cls, v):
        """Validate reliability tier values."""
        if v is None:
            return v
        valid_tiers = {"T1", "T2", "T3", "T4", "T5"}
        for tier in v:
            if tier not in valid_tiers:
                raise ValueError(f"Invalid reliability tier: {tier}. Must be one of {valid_tiers}")
        return v

    def get_effective_reliability_tiers(self) -> Optional[list[str]]:
        """Get effective reliability tiers, considering min_reliability_tier."""
        if self.reliability_tiers:
            return self.reliability_tiers

        if self.min_reliability_tier:
            tier_order = ["T1", "T2", "T3", "T4", "T5"]
            try:
                idx = tier_order.index(self.min_reliability_tier)
                return tier_order[: idx + 1]
            except ValueError:
                return None

        return None

    def is_empty(self) -> bool:
        """Check if no filters are active."""
        return (
            not self.subject_ids
            and not self.source_ids
            and not self.source_names
            and not self.date_from
            and not self.date_to
            and not self.reliability_tiers
            and not self.min_reliability_tier
            and not self.sentiments
            and not self.narrative_ids
            and not self.entity_ids
            and not self.entity_names
            and not self.entity_types
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "subject_ids": [str(sid) for sid in self.subject_ids] if self.subject_ids else None,
            "source_ids": [str(sid) for sid in self.source_ids] if self.source_ids else None,
            "source_names": self.source_names,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "reliability_tiers": self.reliability_tiers,
            "min_reliability_tier": self.min_reliability_tier,
            "sentiments": self.sentiments,
            "narrative_ids": [str(nid) for nid in self.narrative_ids] if self.narrative_ids else None,
            "entity_ids": [str(eid) for eid in self.entity_ids] if self.entity_ids else None,
            "entity_names": self.entity_names,
            "entity_types": self.entity_types,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchFilters":
        """Create from dictionary."""
        return cls(
            subject_ids=[UUID(sid) for sid in data.get("subject_ids", [])] if data.get("subject_ids") else None,
            source_ids=[UUID(sid) for sid in data.get("source_ids", [])] if data.get("source_ids") else None,
            source_names=data.get("source_names"),
            date_from=datetime.fromisoformat(data["date_from"].replace("Z", "+00:00")) if data.get("date_from") else None,
            date_to=datetime.fromisoformat(data["date_to"].replace("Z", "+00:00")) if data.get("date_to") else None,
            reliability_tiers=data.get("reliability_tiers"),
            min_reliability_tier=data.get("min_reliability_tier"),
            sentiments=data.get("sentiments"),
            narrative_ids=[UUID(nid) for nid in data.get("narrative_ids", [])] if data.get("narrative_ids") else None,
            entity_ids=[UUID(eid) for eid in data.get("entity_ids", [])] if data.get("entity_ids") else None,
            entity_names=data.get("entity_names"),
            entity_types=data.get("entity_types"),
        )

    def merge(self, other: "SearchFilters") -> "SearchFilters":
        """
        Merge two filter sets with AND logic.

        For list fields, uses intersection if both have values.
        For date fields, takes the more restrictive range.
        """
        def merge_lists(a: Optional[list], b: Optional[list]) -> Optional[list]:
            if not a:
                return b
            if not b:
                return a
            # Return intersection
            return list(set(a) & set(b)) or a  # Fallback to a if intersection is empty

        return SearchFilters(
            subject_ids=merge_lists(self.subject_ids, other.subject_ids),
            source_ids=merge_lists(self.source_ids, other.source_ids),
            source_names=merge_lists(self.source_names, other.source_names),
            date_from=max(filter(None, [self.date_from, other.date_from]), default=None),
            date_to=min(filter(None, [self.date_to, other.date_to]), default=None),
            reliability_tiers=merge_lists(self.reliability_tiers, other.reliability_tiers),
            sentiments=merge_lists(self.sentiments, other.sentiments),
            narrative_ids=merge_lists(self.narrative_ids, other.narrative_ids),
            entity_ids=merge_lists(self.entity_ids, other.entity_ids),
            entity_names=merge_lists(self.entity_names, other.entity_names),
            entity_types=merge_lists(self.entity_types, other.entity_types),
        )


def parse_date_expression(expression: str) -> Optional[DateRangeFilter]:
    """
    Parse natural language date expressions into DateRangeFilter.

    Examples:
        - "last 7 days"
        - "past week"
        - "last month"
        - "since 2024-01-01"
        - "between 2024-01-01 and 2024-06-30"

    Args:
        expression: Natural language date expression.

    Returns:
        DateRangeFilter or None if expression couldn't be parsed.
    """
    expression = expression.lower().strip()

    # "last N days/weeks/months"
    match = re.match(r"(?:last|past)\s+(\d+)\s+(day|week|month|year)s?", expression)
    if match:
        num = int(match.group(1))
        unit = match.group(2)
        days = {
            "day": num,
            "week": num * 7,
            "month": num * 30,
            "year": num * 365,
        }.get(unit, num)
        return DateRangeFilter.last_n_days(days)

    # "last week/month/year"
    if expression in ("last week", "past week"):
        return DateRangeFilter.last_week()
    if expression in ("last month", "past month"):
        return DateRangeFilter.last_month()
    if expression in ("last year", "past year"):
        return DateRangeFilter.last_year()

    # "since YYYY-MM-DD"
    match = re.match(r"since\s+(\d{4}-\d{2}-\d{2})", expression)
    if match:
        try:
            date_from = datetime.fromisoformat(match.group(1))
            return DateRangeFilter(date_from=date_from, date_to=datetime.utcnow())
        except ValueError:
            pass

    # "between YYYY-MM-DD and YYYY-MM-DD"
    match = re.match(
        r"between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})",
        expression
    )
    if match:
        try:
            date_from = datetime.fromisoformat(match.group(1))
            date_to = datetime.fromisoformat(match.group(2))
            return DateRangeFilter(date_from=date_from, date_to=date_to)
        except ValueError:
            pass

    return None
