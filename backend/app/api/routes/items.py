"""
Items Endpoints
Handles listing and retrieval of content items (articles, posts, filings, etc.).
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import Item, Source
from app.models.schemas import (
    ItemRead,
    PaginatedResponse,
)

router = APIRouter()


# =============================================================================
# Response Schemas
# =============================================================================


class ItemListResponse(PaginatedResponse):
    """Paginated response for items list."""

    items: list[ItemRead]


class ItemDetailResponse(ItemRead):
    """Detailed item response with related data."""

    source_name: str | None = None
    source_type: str | None = None
    entity_count: int = 0
    claim_count: int = 0


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "",
    response_model=ItemListResponse,
    summary="List items",
    description="Retrieve a paginated list of content items with optional filters.",
)
async def list_items(
    db: DatabaseSession,
    current_user: CurrentUser,
    pagination: Pagination,
    response: Response,
    source_id: Annotated[
        UUID | None, Query(description="Filter by source ID")
    ] = None,
    source_type: Annotated[
        str | None, Query(description="Filter by source type (news, social, filing, etc.)")
    ] = None,
    language: Annotated[
        str | None, Query(description="Filter by language code (e.g., 'en')")
    ] = None,
    min_sentiment: Annotated[
        float | None, Query(ge=-1.0, le=1.0, description="Minimum sentiment score")
    ] = None,
    max_sentiment: Annotated[
        float | None, Query(ge=-1.0, le=1.0, description="Maximum sentiment score")
    ] = None,
    min_salience: Annotated[
        float | None, Query(ge=0.0, le=1.0, description="Minimum salience score")
    ] = None,
    published_after: Annotated[
        datetime | None, Query(description="Filter items published after this date")
    ] = None,
    published_before: Annotated[
        datetime | None, Query(description="Filter items published before this date")
    ] = None,
    search: Annotated[
        str | None, Query(description="Search in title and text content")
    ] = None,
    author: Annotated[
        str | None, Query(description="Filter by author")
    ] = None,
) -> ItemListResponse:
    """
    List content items with filtering options:
    - **source_id**: Filter by specific source
    - **source_type**: Filter by source type (news, social, filing, etc.)
    - **language**: Filter by language code
    - **min_sentiment/max_sentiment**: Filter by sentiment range
    - **min_salience**: Filter by minimum salience/importance
    - **published_after/published_before**: Filter by publication date range
    - **search**: Full-text search in title and content
    - **author**: Filter by author name
    """
    # Build base query
    query = select(Item)

    # Apply filters
    if source_id:
        query = query.where(Item.source_id == source_id)

    if source_type:
        query = query.join(Source).where(Source.source_type == source_type)

    if language:
        query = query.where(Item.language == language)

    if min_sentiment is not None:
        query = query.where(Item.sentiment >= min_sentiment)

    if max_sentiment is not None:
        query = query.where(Item.sentiment <= max_sentiment)

    if min_salience is not None:
        query = query.where(Item.salience >= min_salience)

    if published_after:
        query = query.where(Item.published_at >= published_after)

    if published_before:
        query = query.where(Item.published_at <= published_before)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Item.title.ilike(search_filter))
            | (Item.normalized_text.ilike(search_filter))
        )

    if author:
        query = query.where(Item.author.ilike(f"%{author}%"))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Calculate pagination metadata
    total_pages = (total + pagination.page_size - 1) // pagination.page_size if total > 0 else 0

    # Apply pagination and ordering
    query = (
        query.options(selectinload(Item.source))
        .order_by(Item.published_at.desc().nullslast(), Item.created_at.desc())
        .offset((pagination.page - 1) * pagination.page_size)
        .limit(pagination.page_size)
    )

    result = await db.execute(query)
    items = result.scalars().all()

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(pagination.page)
    response.headers["X-Page-Size"] = str(pagination.page_size)

    return ItemListResponse(
        items=[ItemRead.model_validate(item) for item in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        total_pages=total_pages,
        has_next=pagination.page < total_pages,
        has_prev=pagination.page > 1,
    )


@router.get(
    "/{item_id}",
    response_model=ItemDetailResponse,
    summary="Get item details",
    description="Retrieve detailed information about a specific content item.",
)
async def get_item(
    item_id: UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
    include_embedding: Annotated[
        bool, Query(description="Include vector embedding in response")
    ] = False,
) -> ItemDetailResponse:
    """
    Get detailed item information including:
    - Full content and metadata
    - Source information
    - Related entity and claim counts
    - Optionally include vector embedding
    """
    query = (
        select(Item)
        .options(
            selectinload(Item.source),
            selectinload(Item.entities),
            selectinload(Item.claims),
        )
        .where(Item.id == item_id)
    )

    result = await db.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with id '{item_id}' not found",
        )

    # Build response with related counts
    item_data = ItemRead.model_validate(item)

    # Exclude embedding unless explicitly requested
    if not include_embedding:
        item_data.embedding = None

    return ItemDetailResponse(
        **item_data.model_dump(),
        source_name=item.source.name if item.source else None,
        source_type=item.source.source_type if item.source else None,
        entity_count=len(item.entities) if item.entities else 0,
        claim_count=len(item.claims) if item.claims else 0,
    )
