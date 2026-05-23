"""
Artifact-related schemas for API request/response validation.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.schemas.common import (
    BaseSchema,
    ArtifactType,
    ArtifactStatus,
    Citation,
)


# =============================================================================
# Artifact Content
# =============================================================================


class ArtifactContent(BaseModel):
    """Content of a generated artifact."""

    model_config = ConfigDict(from_attributes=True)

    format: str = Field(
        default="html",
        description="Content format (html, markdown, json)",
    )
    body: str = Field(
        ...,
        description="Main content body",
    )
    sections: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description="Structured sections if applicable",
    )
    data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Additional structured data",
    )


# =============================================================================
# Artifact Request
# =============================================================================


class ArtifactRequest(BaseModel):
    """Request schema for artifact operations."""

    model_config = ConfigDict(from_attributes=True)

    artifact_type: str = Field(
        ...,
        description="Type of artifact to generate",
    )
    subject_id: Optional[UUID] = Field(
        default=None,
        description="Subject to generate artifact for",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Custom title for the artifact",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Description or purpose of the artifact",
    )
    parameters: Optional[dict[str, Any]] = Field(
        default=None,
        description="Type-specific generation parameters",
    )


class ArtifactCreateRequest(ArtifactRequest):
    """Request schema for creating an artifact."""

    schedule: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional recurring schedule configuration",
    )


# Alias for backward compatibility
ArtifactCreate = ArtifactCreateRequest


# =============================================================================
# Artifact Response
# =============================================================================


class ArtifactResponse(BaseModel):
    """Response schema for artifact listing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    artifact_type: str
    title: str
    description: Optional[str] = None
    status: str
    subject_id: Optional[UUID] = None
    subject_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_completion_seconds: Optional[int] = None


class ArtifactListResponse(BaseModel):
    """Paginated list of artifacts."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ArtifactResponse]
    total: int
    page: int
    page_size: int


class ArtifactDetailResponse(ArtifactResponse):
    """Detailed artifact response with content."""

    content: Optional[ArtifactContent] = None
    export_urls: Optional[dict[str, str]] = None
    metadata: Optional[dict[str, Any]] = None
    error: Optional[str] = None


# =============================================================================
# Legacy Schemas (for backward compatibility)
# =============================================================================


class ArtifactBase(BaseSchema):
    """Base schema for Artifact (generated report/memo/etc)."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Title of the artifact",
    )
    artifact_type: ArtifactType = Field(
        ...,
        description="Type of artifact",
    )
    body: str = Field(
        ...,
        description="Main content body (markdown supported)",
    )
    summary: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Executive summary",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="Citations/references used",
    )
    status: ArtifactStatus = Field(
        default=ArtifactStatus.DRAFT,
        description="Current status",
    )
    subject_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of subjects this artifact is about",
    )
    narrative_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of narratives covered in this artifact",
    )
    event_ids: list[UUID] = Field(
        default_factory=list,
        description="IDs of events covered in this artifact",
    )
    s3_key: Optional[str] = Field(
        default=None,
        description="S3 key for the stored artifact file",
    )
    file_format: str = Field(
        default="md",
        description="File format (md, pdf, docx, html)",
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Version number",
    )
    published_at: Optional[datetime] = Field(
        default=None,
        description="When the artifact was published",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class ArtifactUpdate(BaseSchema):
    """Schema for updating an Artifact."""

    title: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
    )
    body: Optional[str] = None
    summary: Optional[str] = Field(
        default=None,
        max_length=2000,
    )
    citations: Optional[list[Citation]] = None
    status: Optional[ArtifactStatus] = None
    s3_key: Optional[str] = None
    file_format: Optional[str] = None
    published_at: Optional[datetime] = None
    metadata: Optional[dict[str, Any]] = None


class ArtifactRead(ArtifactBase):
    """Schema for reading an Artifact."""

    id: UUID = Field(..., description="Unique identifier")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
