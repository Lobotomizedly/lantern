"""
SQLAlchemy ORM models for the Lantern Narrative Intelligence Platform.

This module defines all database tables using SQLAlchemy 2.0 async-compatible
ORM models with support for pgvector embeddings and JSONB columns.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.config import settings


# =============================================================================
# Base Model
# =============================================================================


class Base(DeclarativeBase):
    """
    Base class for all ORM models.

    Provides common configuration and type annotations for SQLAlchemy models.
    """

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[str]: ARRAY(String),
    }


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at columns.

    Automatically sets created_at on insert and updates updated_at on every change.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Timestamp when the record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Timestamp when the record was last updated",
    )


# =============================================================================
# Subject Model
# =============================================================================


class Subject(Base, TimestampMixin):
    """
    A subject being tracked in the platform.

    Subjects can be people, organizations, or topics that users want to monitor
    for narrative intelligence. Each subject has a watchlist configuration
    that defines how content is gathered and analyzed.
    """

    __tablename__ = "subjects"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the subject",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Name of the subject",
    )
    subject_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of subject: person, org, or topic",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the subject",
    )
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="ID of the user who owns this subject",
    )
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="ID of the organization this subject belongs to",
    )
    watchlist_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Watchlist monitoring configuration (sources, queries, cadence, lookback)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether the subject is actively being monitored",
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Whether the subject has been archived (soft deleted)",
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the subject was archived",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact",
        secondary="artifact_subjects",
        back_populates="subjects",
    )
    config: Mapped[Optional["SubjectConfig"]] = relationship(
        "SubjectConfig",
        back_populates="subject",
        uselist=False,
    )
    sentinel_flags: Mapped[list["SentinelFlag"]] = relationship(
        "SentinelFlag",
        back_populates="subject",
    )

    __table_args__ = (
        Index("ix_subjects_name_type", "name", "subject_type"),
        Index("ix_subjects_org_archived", "organization_id", "is_archived"),
        {"comment": "Subjects being tracked for narrative intelligence"},
    )

    def __repr__(self) -> str:
        return f"<Subject(id={self.id}, name='{self.name}', type='{self.subject_type}')>"


# =============================================================================
# Entity Model
# =============================================================================


class Entity(Base, TimestampMixin):
    """
    An entity extracted from content.

    Entities represent real-world things like people, organizations, places,
    or products that are mentioned in content items. They include vector
    embeddings for similarity search and can have multiple aliases.
    """

    __tablename__ = "entities"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the entity",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Primary name of the entity",
    )
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of entity: person, org, place, or product",
    )
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)),
        nullable=False,
        default=list,
        doc="Alternative names for the entity",
    )
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="External identifiers (wikidata_id, linkedin_url, etc.)",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the entity",
    )
    embedding: Mapped[Optional[Any]] = mapped_column(
        Vector(settings.embedding_dimensions),
        nullable=True,
        doc=f"Vector embedding ({settings.embedding_dimensions} dimensions)",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    items: Mapped[list["Item"]] = relationship(
        "Item",
        secondary="item_entities",
        back_populates="entities",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        secondary="document_entities",
        back_populates="entities",
    )
    subject_claims: Mapped[list["Claim"]] = relationship(
        "Claim",
        foreign_keys="Claim.subject_entity_id",
        back_populates="subject_entity",
    )
    object_claims: Mapped[list["Claim"]] = relationship(
        "Claim",
        foreign_keys="Claim.object_entity_id",
        back_populates="object_entity",
    )
    events: Mapped[list["Event"]] = relationship(
        "Event",
        secondary="event_entities",
        back_populates="entities",
    )

    __table_args__ = (
        Index("ix_entities_name_type", "name", "entity_type"),
        Index(
            "ix_entities_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"comment": "Entities extracted from content"},
    )

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, name='{self.name}', type='{self.entity_type}')>"


# =============================================================================
# Source Model
# =============================================================================


class Source(Base, TimestampMixin):
    """
    A content source in the platform.

    Sources represent where content comes from, such as news outlets, social
    media platforms, SEC filings, podcasts, etc. Each source has a reliability
    tier and configuration for fetching content.
    """

    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the source",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Name of the source",
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type: news, social, filing, podcast, video, blog, press_release",
    )
    url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
        doc="Base URL of the source",
    )
    reliability_tier: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        index=True,
        doc="Reliability tier (1-4, 1 being highest)",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the source",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether the source is active",
    )
    fetch_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Configuration for fetching from this source",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    items: Mapped[list["Item"]] = relationship(
        "Item",
        back_populates="source",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("name", "source_type", name="uq_sources_name_type"),
        Index("ix_sources_type_reliability", "source_type", "reliability_tier"),
        {"comment": "Content sources for the platform"},
    )

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type='{self.source_type}')>"


# =============================================================================
# Item Model
# =============================================================================


class Item(Base, TimestampMixin):
    """
    A content item from a source.

    Items represent individual pieces of content (articles, posts, filings, etc.)
    that have been ingested and processed. They include normalized text,
    embeddings for similarity search, and sentiment/salience scores.
    """

    __tablename__ = "items"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the item",
    )
    source_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the source this item came from",
    )
    raw_ref: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        unique=True,
        doc="Original URL or reference to the content",
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        index=True,
        doc="Title of the content",
    )
    normalized_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Cleaned and normalized text content",
    )
    raw_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Original raw text before normalization",
    )
    embedding: Mapped[Optional[Any]] = mapped_column(
        Vector(settings.embedding_dimensions),
        nullable=True,
        doc=f"Vector embedding ({settings.embedding_dimensions} dimensions)",
    )
    sentiment: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Sentiment score (-1 to 1)",
    )
    salience: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Salience/importance score (0 to 1)",
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="When the content was originally published",
    )
    author: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Author of the content",
    )
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
        doc="Language code",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    source: Mapped["Source"] = relationship(
        "Source",
        back_populates="items",
    )
    entities: Mapped[list["Entity"]] = relationship(
        "Entity",
        secondary="item_entities",
        back_populates="items",
    )
    claims: Mapped[list["Claim"]] = relationship(
        "Claim",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_items_source_published", "source_id", "published_at"),
        Index("ix_items_published_at", "published_at"),
        Index(
            "ix_items_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"comment": "Content items ingested from sources"},
    )

    def __repr__(self) -> str:
        return f"<Item(id={self.id}, title='{self.title}', source_id={self.source_id})>"


# =============================================================================
# Item-Entity Association Table
# =============================================================================


class ItemEntity(Base):
    """Association table linking items to entities."""

    __tablename__ = "item_entities"

    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mention_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Number of times the entity is mentioned in the item",
    )
    salience: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        doc="Salience of the entity in this item",
    )

    __table_args__ = (
        {"comment": "Association between items and entities"},
    )


# =============================================================================
# Claim Model
# =============================================================================


class Claim(Base, TimestampMixin):
    """
    A claim extracted from content.

    Claims are structured statements extracted from content items, representing
    assertions, denials, or other statements about entities or topics.
    """

    __tablename__ = "claims"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the claim",
    )
    item_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the item this claim was extracted from",
    )
    subject_who: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        doc="Who the claim is about (subject)",
    )
    predicate: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="The action or relationship",
    )
    object_what: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        doc="What the claim states (object)",
    )
    stance: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="neutral",
        index=True,
        doc="Stance: positive, negative, neutral, mixed",
    )
    polarity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="assertion",
        doc="Polarity: assertion, denial, speculation, question",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        doc="Confidence score for this claim extraction",
    )
    evidence_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="The exact text that supports this claim",
    )
    subject_entity_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Linked entity ID for the subject",
    )
    object_entity_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Linked entity ID for the object",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="claims",
    )
    subject_entity: Mapped[Optional["Entity"]] = relationship(
        "Entity",
        foreign_keys=[subject_entity_id],
        back_populates="subject_claims",
    )
    object_entity: Mapped[Optional["Entity"]] = relationship(
        "Entity",
        foreign_keys=[object_entity_id],
        back_populates="object_claims",
    )

    __table_args__ = (
        Index("ix_claims_item_stance", "item_id", "stance"),
        Index("ix_claims_confidence", "confidence"),
        {"comment": "Claims extracted from content items"},
    )

    def __repr__(self) -> str:
        return f"<Claim(id={self.id}, subject='{self.subject_who}', stance='{self.stance}')>"


# =============================================================================
# Event Model
# =============================================================================


class Event(Base, TimestampMixin):
    """
    A detected event or happening.

    Events represent significant occurrences detected from analyzing multiple
    content items, with temporal and spatial information.
    """

    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the event",
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        doc="Title of the event",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the event",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="When the event occurred",
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Location of the event",
    )
    location_geo: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Geographic coordinates (lat, lon)",
    )
    evidence_item_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        doc="IDs of items that provide evidence for this event",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        doc="Confidence score for this event detection",
    )
    event_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Type/category of event",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    entities: Mapped[list["Entity"]] = relationship(
        "Entity",
        secondary="event_entities",
        back_populates="events",
    )

    __table_args__ = (
        Index("ix_events_occurred_type", "occurred_at", "event_type"),
        {"comment": "Detected events and happenings"},
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, title='{self.title}', occurred_at={self.occurred_at})>"


# =============================================================================
# Event-Entity Association Table
# =============================================================================


class EventEntity(Base):
    """Association table linking events to entities."""

    __tablename__ = "event_entities"

    event_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Role of the entity in the event",
    )

    __table_args__ = (
        {"comment": "Association between events and entities"},
    )


# =============================================================================
# Narrative Model
# =============================================================================


class Narrative(Base, TimestampMixin):
    """
    A detected narrative pattern.

    Narratives represent coherent storylines or themes that emerge from
    analyzing multiple claims and content items over time.
    """

    __tablename__ = "narratives"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the narrative",
    )
    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        doc="Name/title of the narrative",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the narrative",
    )
    thesis: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Core thesis/claim of the narrative",
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed summary of the narrative",
    )
    subject_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the related subject",
    )
    lifecycle: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="emerging",
        index=True,
        doc="Lifecycle stage: emerging, growing, peaking, declining, dormant",
    )
    lifecycle_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="emerging",
        index=True,
        doc="Current lifecycle status",
    )
    prevalence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        index=True,
        doc="How prevalent/widespread the narrative is (0-1)",
    )
    velocity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Rate of change in prevalence",
    )
    velocity_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        index=True,
        doc="Velocity score for ranking",
    )
    document_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of documents related to this narrative",
    )
    amplifiers_json: Mapped[dict[str, Any]] = mapped_column(
        "amplifiers",
        JSONB,
        nullable=False,
        default=list,
        doc="Entities amplifying this narrative (JSON)",
    )
    supporting_claim_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        doc="IDs of claims that support this narrative",
    )
    opposing_claim_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        doc="IDs of claims that oppose this narrative",
    )
    related_narrative_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        doc="IDs of related narratives",
    )
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="When the narrative was first detected",
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the narrative was last seen",
    )
    peak_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the narrative peaked",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)),
        nullable=False,
        default=list,
        doc="Tags/categories for the narrative",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether the narrative is active",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    subject: Mapped[Optional["Subject"]] = relationship(
        "Subject",
        foreign_keys=[subject_id],
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact",
        secondary="artifact_narratives",
        back_populates="narratives",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document",
        secondary="document_narratives",
        back_populates="narratives",
    )
    lifecycle_events: Mapped[list["NarrativeLifecycleEvent"]] = relationship(
        "NarrativeLifecycleEvent",
        back_populates="narrative",
    )
    amplifiers: Mapped[list["NarrativeAmplifier"]] = relationship(
        "NarrativeAmplifier",
        back_populates="narrative",
    )
    claims: Mapped[list["NarrativeClaim"]] = relationship(
        "NarrativeClaim",
        back_populates="narrative",
    )

    __table_args__ = (
        Index("ix_narratives_lifecycle_prevalence", "lifecycle", "prevalence_score"),
        Index("ix_narratives_subject_active", "subject_id", "is_active"),
        {"comment": "Detected narrative patterns"},
    )

    def __repr__(self) -> str:
        return f"<Narrative(id={self.id}, name='{self.name}', lifecycle='{self.lifecycle}')>"


# =============================================================================
# Artifact Model
# =============================================================================


class Artifact(Base, TimestampMixin):
    """
    A generated artifact (report, memo, timeline, newsletter).

    Artifacts are documents generated by the platform that synthesize
    information from various sources into actionable intelligence.
    """

    __tablename__ = "artifacts"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the artifact",
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the user who requested this artifact",
    )
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="ID of the organization",
    )
    subject_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the primary subject",
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        doc="Title of the artifact",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of the artifact",
    )
    artifact_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type: report, memo, timeline, newsletter",
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Main content body (markdown supported)",
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Executive summary",
    )
    content: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Structured content data",
    )
    citations: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        doc="Citations/references used",
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Generation parameters",
    )
    schedule: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Recurring schedule configuration",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="draft",
        index=True,
        doc="Status: pending, queued, generating, completed, failed, draft, review, published, archived",
    )
    queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the artifact was queued",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When generation started",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When generation completed",
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if failed",
    )
    revision_feedback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Feedback for revision requests",
    )
    s3_key: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="S3 key for the stored artifact file",
    )
    file_format: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="md",
        doc="File format (md, pdf, docx, html)",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc="Version number",
    )
    token_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Token count for generation",
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the artifact was published",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    subject: Mapped[Optional["Subject"]] = relationship(
        "Subject",
        foreign_keys=[subject_id],
    )
    subjects: Mapped[list["Subject"]] = relationship(
        "Subject",
        secondary="artifact_subjects",
        back_populates="artifacts",
    )
    narratives: Mapped[list["Narrative"]] = relationship(
        "Narrative",
        secondary="artifact_narratives",
        back_populates="artifacts",
    )

    __table_args__ = (
        Index("ix_artifacts_type_status", "artifact_type", "status"),
        Index("ix_artifacts_org_status", "organization_id", "status"),
        {"comment": "Generated artifacts (reports, memos, etc.)"},
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, title='{self.title}', type='{self.artifact_type}')>"


# =============================================================================
# Artifact Association Tables
# =============================================================================


class ArtifactSubject(Base):
    """Association table linking artifacts to subjects."""

    __tablename__ = "artifact_subjects"

    artifact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        {"comment": "Association between artifacts and subjects"},
    )


class ArtifactNarrative(Base):
    """Association table linking artifacts to narratives."""

    __tablename__ = "artifact_narratives"

    artifact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    narrative_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        {"comment": "Association between artifacts and narratives"},
    )


class ArtifactEvent(Base):
    """Association table linking artifacts to events."""

    __tablename__ = "artifact_events"

    artifact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        {"comment": "Association between artifacts and events"},
    )


# =============================================================================
# Agent Run Tracking Models
# =============================================================================


class AgentRun(Base, TimestampMixin):
    """
    Tracks agent execution runs.

    Records metadata about agent runs including input/output data,
    token usage, costs, and timing information.
    """

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the agent run",
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the user who initiated this run",
    )
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="ID of the organization",
    )
    subject_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the related subject",
    )
    agent_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="investigator",
        index=True,
        doc="Type of agent: investigator, summarizer, etc.",
    )
    agent_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Name of the agent",
    )
    query: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Investigation query or question",
    )
    task_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Description of the task being performed",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Agent configuration (depth, focus_areas, etc.)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        doc="Status: pending, queued, running, completed, failed, cancelled",
    )
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Input data for the agent",
    )
    output_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Output data from the agent",
    )
    output: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Final output from the agent",
    )
    error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if failed",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed error message if failed",
    )
    queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the run was queued",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the run started",
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the run completed",
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total tokens used",
    )
    total_cost_usd: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Total cost in USD",
    )
    model_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Model used for this run",
    )
    parent_run_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Parent run ID if this is a sub-run",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    subject: Mapped[Optional["Subject"]] = relationship(
        "Subject",
        foreign_keys=[subject_id],
    )
    steps: Mapped[list["AgentStep"]] = relationship(
        "AgentStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_number",
    )
    traces: Mapped[list["AgentTrace"]] = relationship(
        "AgentTrace",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentTrace.sequence_number",
    )
    child_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="parent_run",
        remote_side=[id],
    )
    parent_run: Mapped[Optional["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="child_runs",
        remote_side=[parent_run_id],
    )

    __table_args__ = (
        Index("ix_agent_runs_agent_status", "agent_name", "status"),
        Index("ix_agent_runs_started_at", "started_at"),
        Index("ix_agent_runs_org_status", "organization_id", "status"),
        {"comment": "Agent execution tracking"},
    )

    def __repr__(self) -> str:
        return f"<AgentRun(id={self.id}, agent='{self.agent_name}', status='{self.status}')>"


class AgentStep(Base, TimestampMixin):
    """
    Individual step in an agent run.

    Records details about each step including tool calls, LLM calls,
    reasoning steps, and outputs.
    """

    __tablename__ = "agent_steps"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the step",
    )
    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the parent agent run",
    )
    step_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Step number in the sequence",
    )
    step_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type: tool_call, llm_call, reasoning, output",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Name of the step/tool/action",
    )
    input_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Input data for the step",
    )
    output_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Output data from the step",
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Duration in milliseconds",
    )
    tokens_used: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Tokens used in this step",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if the step failed",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="steps",
    )

    __table_args__ = (
        Index("ix_agent_steps_run_number", "run_id", "step_number"),
        UniqueConstraint("run_id", "step_number", name="uq_agent_steps_run_number"),
        {"comment": "Individual steps in agent runs"},
    )

    def __repr__(self) -> str:
        return f"<AgentStep(id={self.id}, run_id={self.run_id}, step={self.step_number}, type='{self.step_type}')>"


# =============================================================================
# User Model
# =============================================================================


class User(Base, TimestampMixin):
    """
    A user of the platform.

    Users belong to organizations and have roles that determine their permissions.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the user",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        doc="User email address",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="User display name",
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="viewer",
        index=True,
        doc="User role: admin, analyst, viewer",
    )
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        doc="ID of the user's organization",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether the user account is active",
    )
    hashed_password: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Hashed password for authentication",
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="User preferences and settings",
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of last login",
    )

    __table_args__ = (
        Index("ix_users_org_role", "organization_id", "role"),
        {"comment": "Platform users"},
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"


# =============================================================================
# SentinelFlag Model
# =============================================================================


class SentinelFlag(Base, TimestampMixin):
    """
    A flag raised by the Sentinel monitoring system.

    Flags represent detected anomalies, velocity spikes, coordinated activity,
    or other notable patterns that require attention.
    """

    __tablename__ = "sentinel_flags"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the flag",
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the subject this flag relates to",
    )
    flag_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Type of flag: velocity_spike, coordinated_activity, sentiment_shift, etc.",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
        doc="Severity level: low, medium, high, critical",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable description of the flag",
    )
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional data and evidence for the flag",
    )
    evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Evidence supporting the flag",
    )
    recommended_action: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Recommended action to take",
    )
    is_resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Whether the flag has been resolved",
    )
    is_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether the flag has been acknowledged",
    )
    acknowledged_by_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="ID of the user who acknowledged the flag",
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the flag was acknowledged",
    )
    is_dismissed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether the flag has been dismissed",
    )
    dismissed_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Reason for dismissing the flag",
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the flag was resolved",
    )
    resolved_by_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="ID of the user who resolved the flag",
    )

    # Relationships
    subject: Mapped["Subject"] = relationship(
        "Subject",
        back_populates="sentinel_flags",
    )

    __table_args__ = (
        Index("ix_sentinel_flags_subject_severity", "subject_id", "severity"),
        Index("ix_sentinel_flags_type_resolved", "flag_type", "is_resolved"),
        {"comment": "Sentinel monitoring flags and alerts"},
    )

    def __repr__(self) -> str:
        return f"<SentinelFlag(id={self.id}, type='{self.flag_type}', severity='{self.severity}')>"


# =============================================================================
# Review Model
# =============================================================================


class Review(Base, TimestampMixin):
    """
    A human-in-the-loop review item.

    Reviews represent artifacts or flags that need human approval before
    being published or acted upon.
    """

    __tablename__ = "reviews"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the review",
    )
    review_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of review: artifact, flag",
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Title of the review item",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Description of what needs to be reviewed",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        doc="Status: pending, approved, rejected",
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
        doc="Priority: low, medium, high, urgent",
    )
    organization_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        doc="ID of the organization",
    )
    subject_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the related subject",
    )
    artifact_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="ID of the artifact being reviewed",
    )
    flag_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sentinel_flags.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        doc="ID of the flag being reviewed",
    )
    assigned_to_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the user assigned to review",
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Due date for the review",
    )
    decision: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        doc="Review decision: approved, rejected",
    )
    feedback: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Reviewer feedback or notes",
    )
    reviewed_by_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="ID of the user who reviewed",
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the review was completed",
    )

    # Relationships
    subject: Mapped[Optional["Subject"]] = relationship(
        "Subject",
        foreign_keys=[subject_id],
    )
    artifact: Mapped[Optional["Artifact"]] = relationship(
        "Artifact",
        foreign_keys=[artifact_id],
    )
    flag: Mapped[Optional["SentinelFlag"]] = relationship(
        "SentinelFlag",
        foreign_keys=[flag_id],
    )
    assigned_to: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assigned_to_id],
    )
    reviewed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[reviewed_by_id],
    )

    __table_args__ = (
        Index("ix_reviews_org_status", "organization_id", "status"),
        Index("ix_reviews_assigned_status", "assigned_to_id", "status"),
        {"comment": "Human-in-the-loop review queue"},
    )

    def __repr__(self) -> str:
        return f"<Review(id={self.id}, type='{self.review_type}', status='{self.status}')>"


# =============================================================================
# SubjectConfig Model
# =============================================================================


class SubjectConfig(Base, TimestampMixin):
    """
    Configuration for a subject's monitoring settings.

    Defines keywords, entities, sources, and alert thresholds for a subject.
    """

    __tablename__ = "subject_configs"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the config",
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        doc="ID of the subject this config belongs to",
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)),
        nullable=False,
        default=list,
        doc="Keywords to track",
    )
    entities: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)),
        nullable=False,
        default=list,
        doc="Entities to monitor",
    )
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)),
        nullable=False,
        default=list,
        doc="Source configurations",
    )
    alert_thresholds: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Alert threshold configuration",
    )
    collection_schedule: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Cron-style collection schedule",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether the config is active",
    )
    last_collection_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last data collection timestamp",
    )

    # Relationships
    subject: Mapped["Subject"] = relationship(
        "Subject",
        back_populates="config",
    )

    __table_args__ = (
        {"comment": "Subject monitoring configurations"},
    )

    def __repr__(self) -> str:
        return f"<SubjectConfig(id={self.id}, subject_id={self.subject_id}, active={self.is_active})>"


# =============================================================================
# Additional Models for Route Support
# =============================================================================


class Document(Base, TimestampMixin):
    """
    A document collected for analysis.

    Similar to Item but with additional fields for search and narrative linking.
    """

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the document",
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the subject this document relates to",
    )
    source_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="ID of the source this document came from",
    )
    url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
        doc="Original URL of the document",
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        index=True,
        doc="Title of the document",
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Full content of the document",
    )
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="AI-generated summary",
    )
    sentiment: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        doc="Sentiment label: positive, negative, neutral",
    )
    sentiment_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        doc="Sentiment score (-1 to 1)",
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="When the document was published",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
        doc="Soft delete flag",
    )

    # Relationships
    source: Mapped[Optional["Source"]] = relationship(
        "Source",
    )
    entities: Mapped[list["Entity"]] = relationship(
        "Entity",
        secondary="document_entities",
        back_populates="documents",
    )
    narratives: Mapped[list["Narrative"]] = relationship(
        "Narrative",
        secondary="document_narratives",
        back_populates="documents",
    )

    __table_args__ = (
        Index("ix_documents_subject_published", "subject_id", "published_at"),
        {"comment": "Documents collected for analysis"},
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, title='{self.title}')>"


class DocumentEntity(Base):
    """Association table linking documents to entities."""

    __tablename__ = "document_entities"

    document_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        {"comment": "Association between documents and entities"},
    )


class DocumentNarrative(Base):
    """Association table linking documents to narratives."""

    __tablename__ = "document_narratives"

    document_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    narrative_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        {"comment": "Association between documents and narratives"},
    )


class TimelineEvent(Base, TimestampMixin):
    """
    An event in the timeline.

    Timeline events track significant occurrences across subjects and narratives.
    """

    __tablename__ = "timeline_events"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the event",
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the related subject",
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type: document, narrative_change, flag, milestone",
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Event title",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Event description",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="When the event occurred",
    )
    importance: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
        doc="Importance level: low, medium, high, critical",
    )
    document_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        doc="Related document ID if applicable",
    )
    narrative_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="SET NULL"),
        nullable=True,
        doc="Related narrative ID if applicable",
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        doc="Additional metadata",
    )

    # Relationships
    subject: Mapped["Subject"] = relationship("Subject")
    document: Mapped[Optional["Document"]] = relationship("Document")
    narrative: Mapped[Optional["Narrative"]] = relationship("Narrative")

    __table_args__ = (
        Index("ix_timeline_events_subject_occurred", "subject_id", "occurred_at"),
        {"comment": "Timeline events for subjects"},
    )

    def __repr__(self) -> str:
        return f"<TimelineEvent(id={self.id}, type='{self.event_type}', title='{self.title}')>"


class NarrativeLifecycleEvent(Base, TimestampMixin):
    """
    A lifecycle event for a narrative.

    Tracks the evolution of narratives over time.
    """

    __tablename__ = "narrative_lifecycle_events"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the event",
    )
    narrative_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the narrative",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Lifecycle status at this point",
    )
    velocity_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Velocity score at this point",
    )
    document_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Document count at this point",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
        doc="When this snapshot was recorded",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional notes about this lifecycle event",
    )

    # Relationships
    narrative: Mapped["Narrative"] = relationship(
        "Narrative",
        back_populates="lifecycle_events",
    )

    __table_args__ = (
        Index("ix_narrative_lifecycle_narrative_recorded", "narrative_id", "recorded_at"),
        {"comment": "Narrative lifecycle history"},
    )

    def __repr__(self) -> str:
        return f"<NarrativeLifecycleEvent(id={self.id}, status='{self.status}')>"


class NarrativeAmplifier(Base, TimestampMixin):
    """
    An amplifier of a narrative.

    Tracks accounts and sources that are spreading a narrative.
    """

    __tablename__ = "narrative_amplifiers"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the amplifier",
    )
    narrative_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the narrative",
    )
    platform: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Platform: twitter, facebook, reddit, etc.",
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Platform-specific account ID",
    )
    account_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Display name of the account",
    )
    account_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Type: individual, organization, bot, etc.",
    )
    influence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        index=True,
        doc="Influence score (0-1)",
    )
    post_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of posts about this narrative",
    )
    total_reach: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total reach/impressions",
    )
    first_posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When this account first posted about the narrative",
    )
    last_posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When this account last posted about the narrative",
    )
    is_coordinated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether this amplifier is part of coordinated activity",
    )

    # Relationships
    narrative: Mapped["Narrative"] = relationship(
        "Narrative",
        back_populates="amplifiers",
    )

    __table_args__ = (
        Index("ix_narrative_amplifiers_narrative_influence", "narrative_id", "influence_score"),
        {"comment": "Entities amplifying narratives"},
    )

    def __repr__(self) -> str:
        return f"<NarrativeAmplifier(id={self.id}, account='{self.account_name}', influence={self.influence_score})>"


class NarrativeClaim(Base, TimestampMixin):
    """
    A claim associated with a narrative.

    Different from the general Claim model - these are specific claims
    that are part of a narrative's thesis.
    """

    __tablename__ = "narrative_claims"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the claim",
    )
    narrative_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("narratives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the narrative",
    )
    claim_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="The claim text",
    )
    claim_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Type of claim: fact, opinion, prediction, etc.",
    )
    verification_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        doc="Status: verified, disputed, unverified, etc.",
    )
    frequency: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        index=True,
        doc="How often this claim appears",
    )
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the claim was first detected",
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the claim was last seen",
    )
    source_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of unique sources for this claim",
    )

    # Relationships
    narrative: Mapped["Narrative"] = relationship(
        "Narrative",
        back_populates="claims",
    )

    __table_args__ = (
        Index("ix_narrative_claims_narrative_frequency", "narrative_id", "frequency"),
        {"comment": "Claims associated with narratives"},
    )

    def __repr__(self) -> str:
        return f"<NarrativeClaim(id={self.id}, frequency={self.frequency})>"


class AgentTrace(Base, TimestampMixin):
    """
    A trace entry for an agent run.

    Tracks individual steps, tool calls, and reasoning in agent execution.
    """

    __tablename__ = "agent_traces"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        doc="Unique identifier for the trace",
    )
    run_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="ID of the agent run",
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Sequence number in the trace",
    )
    trace_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type: tool_call, llm_call, reasoning, iteration, etc.",
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Content or reasoning text",
    )
    tool_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Name of the tool called",
    )
    tool_input: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Input to the tool",
    )
    tool_output: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Output from the tool",
    )
    tokens_used: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Tokens used in this step",
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Duration in milliseconds",
    )

    # Relationships
    run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="traces",
    )

    __table_args__ = (
        Index("ix_agent_traces_run_sequence", "run_id", "sequence_number"),
        {"comment": "Agent execution traces"},
    )

    def __repr__(self) -> str:
        return f"<AgentTrace(id={self.id}, type='{self.trace_type}', seq={self.sequence_number})>"
