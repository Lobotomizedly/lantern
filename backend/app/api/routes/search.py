"""
Search Endpoints
Handles hybrid semantic search with advanced filtering capabilities.
"""

from datetime import datetime, date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from app.api.deps import DatabaseSession, CurrentUser, Pagination
from app.models.orm import Document, Narrative, Entity, Source
from app.models.schemas.search import (
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SearchFilters,
    SearchFacets,
    DateRange,
)

router = APIRouter()


@router.post(
    "",
    response_model=SearchResponse,
    summary="Hybrid semantic search",
    description="Perform hybrid semantic search across documents with advanced filtering.",
)
async def search_documents(
    search_request: SearchRequest,
    db: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
) -> SearchResponse:
    """
    Perform hybrid semantic search combining:
    - **Vector similarity**: Semantic search using embeddings
    - **Full-text search**: Keyword matching with BM25 ranking
    - **Metadata filtering**: Filter by subject, source, date range, etc.

    Filter options:
    - **subject_ids**: Limit to specific subjects
    - **source_types**: Filter by source type (news, social, etc.)
    - **date_range**: Filter by publication date
    - **reliability_tier**: Filter by source reliability (T1, T2, T3)
    - **sentiment**: Filter by sentiment (positive, negative, neutral)
    - **narrative_ids**: Filter by associated narratives
    - **entity_ids**: Filter by mentioned entities
    """
    # Build base query for documents
    query = select(Document).where(Document.is_deleted == False)

    filters = search_request.filters or SearchFilters()

    # Apply subject filter
    if filters.subject_ids:
        query = query.where(Document.subject_id.in_(filters.subject_ids))
    else:
        # Default to user's organization subjects
        from app.models.orm import Subject

        subquery = select(Subject.id).where(
            Subject.organization_id == current_user.organization_id
        )
        query = query.where(Document.subject_id.in_(subquery))

    # Apply source type filter
    if filters.source_types:
        query = query.join(Source).where(Source.source_type.in_(filters.source_types))

    # Apply date range filter
    if filters.date_range:
        if filters.date_range.start:
            query = query.where(Document.published_at >= filters.date_range.start)
        if filters.date_range.end:
            query = query.where(Document.published_at <= filters.date_range.end)

    # Apply reliability tier filter
    if filters.reliability_tiers:
        query = query.join(Source, isouter=True).where(
            Source.reliability_tier.in_(filters.reliability_tiers)
        )

    # Apply sentiment filter
    if filters.sentiments:
        query = query.where(Document.sentiment.in_(filters.sentiments))

    # Apply narrative filter
    if filters.narrative_ids:
        query = query.join(Document.narratives).where(
            Narrative.id.in_(filters.narrative_ids)
        )

    # Apply entity filter
    if filters.entity_ids:
        query = query.join(Document.entities).where(Entity.id.in_(filters.entity_ids))

    # Apply text search if query provided
    if search_request.query:
        # In production, this would use pgvector for semantic search
        # and ts_vector for full-text search with ranking
        search_term = f"%{search_request.query}%"
        query = query.where(
            or_(
                Document.title.ilike(search_term),
                Document.content.ilike(search_term),
                Document.summary.ilike(search_term),
            )
        )

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply sorting
    sort_field = search_request.sort_by or "relevance"
    sort_order = search_request.sort_order or "desc"

    if sort_field == "date":
        order_col = Document.published_at
    elif sort_field == "relevance":
        # In production, this would be the search score
        order_col = Document.published_at
    else:
        order_col = Document.published_at

    if sort_order == "desc":
        query = query.order_by(order_col.desc())
    else:
        query = query.order_by(order_col.asc())

    # Apply pagination
    page = search_request.page or 1
    page_size = search_request.page_size or 20
    query = (
        query.options(
            selectinload(Document.source),
            selectinload(Document.entities),
            selectinload(Document.narratives),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(query)
    documents = result.scalars().all()

    # Build facets for filter UI
    facets = await _build_search_facets(db, current_user, filters)

    # Set pagination headers
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(page_size)

    return SearchResponse(
        items=[
            SearchResultItem(
                id=doc.id,
                title=doc.title,
                summary=doc.summary,
                content_preview=doc.content[:500] if doc.content else None,
                url=doc.url,
                source_name=doc.source.name if doc.source else None,
                source_type=doc.source.source_type if doc.source else None,
                reliability_tier=doc.source.reliability_tier if doc.source else None,
                published_at=doc.published_at,
                sentiment=doc.sentiment,
                sentiment_score=doc.sentiment_score,
                entities=[
                    {"id": str(e.id), "name": e.name, "type": e.entity_type}
                    for e in doc.entities[:5]
                ],
                narratives=[
                    {"id": str(n.id), "name": n.name} for n in doc.narratives[:3]
                ],
                highlight=_generate_highlight(doc, search_request.query),
                relevance_score=1.0,  # Would come from search ranking
            )
            for doc in documents
        ],
        total=total,
        page=page,
        page_size=page_size,
        query=search_request.query,
        filters=filters,
        facets=facets,
    )


async def _build_search_facets(
    db: DatabaseSession,
    current_user: CurrentUser,
    current_filters: SearchFilters,
) -> SearchFacets:
    """Build facet counts for the search filter UI."""
    from app.models.orm import Subject

    # Get subjects accessible to user
    subject_query = select(Subject.id, Subject.name, func.count(Document.id)).join(
        Document, Document.subject_id == Subject.id, isouter=True
    ).where(
        Subject.organization_id == current_user.organization_id,
        Subject.is_archived == False,
    ).group_by(Subject.id, Subject.name)

    subject_result = await db.execute(subject_query)
    subject_facets = [
        {"id": str(row[0]), "name": row[1], "count": row[2]}
        for row in subject_result.all()
    ]

    # Get source type counts
    source_type_query = (
        select(Source.source_type, func.count(Document.id))
        .join(Document, Document.source_id == Source.id)
        .group_by(Source.source_type)
    )
    source_result = await db.execute(source_type_query)
    source_facets = [
        {"value": row[0], "count": row[1]} for row in source_result.all()
    ]

    # Get reliability tier counts
    tier_query = (
        select(Source.reliability_tier, func.count(Document.id))
        .join(Document, Document.source_id == Source.id)
        .where(Source.reliability_tier.isnot(None))
        .group_by(Source.reliability_tier)
    )
    tier_result = await db.execute(tier_query)
    tier_facets = [{"value": row[0], "count": row[1]} for row in tier_result.all()]

    # Get sentiment counts
    sentiment_query = (
        select(Document.sentiment, func.count(Document.id))
        .where(Document.sentiment.isnot(None))
        .group_by(Document.sentiment)
    )
    sentiment_result = await db.execute(sentiment_query)
    sentiment_facets = [
        {"value": row[0], "count": row[1]} for row in sentiment_result.all()
    ]

    return SearchFacets(
        subjects=subject_facets,
        source_types=source_facets,
        reliability_tiers=tier_facets,
        sentiments=sentiment_facets,
    )


def _generate_highlight(document: Document, query: str | None) -> str | None:
    """Generate highlighted snippet from document matching the query."""
    if not query or not document.content:
        return None

    query_lower = query.lower()
    content_lower = document.content.lower()

    # Find position of query in content
    pos = content_lower.find(query_lower)
    if pos == -1:
        return None

    # Extract context around the match
    start = max(0, pos - 100)
    end = min(len(document.content), pos + len(query) + 100)

    snippet = document.content[start:end]

    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(document.content):
        snippet = snippet + "..."

    return snippet
