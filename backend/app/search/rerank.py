"""
Cross-encoder reranking for final search precision.

This module provides cross-encoder based reranking to improve
the precision of search results from hybrid retrieval.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from app.search.hybrid import HybridSearchResult
from app.search.vector import SearchableType

logger = logging.getLogger(__name__)


@dataclass
class RerankedResult:
    """A single reranked search result."""

    id: UUID
    entity_type: SearchableType
    rerank_score: float  # Cross-encoder relevance score
    original_rank: int  # Position in original results
    new_rank: int  # Position after reranking
    hybrid_score: Optional[float] = None  # Original hybrid score
    title: Optional[str] = None
    content: Optional[str] = None
    source_id: Optional[UUID] = None
    source_name: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    reliability_tier: Optional[str] = None
    url: Optional[str] = None
    highlights: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CrossEncoderConfig(BaseModel):
    """Configuration for cross-encoder reranking."""

    # Model to use for cross-encoding
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"

    # Maximum input length (query + document)
    max_length: int = 512

    # Batch size for inference
    batch_size: int = 32

    # Device for inference (cpu, cuda, mps)
    device: str = "cpu"

    # Whether to use FP16 for faster inference
    use_fp16: bool = False


class CrossEncoderReranker:
    """
    Cross-encoder reranker for improving search precision.

    Uses a cross-encoder model to compute relevance scores between
    the query and each document, then reranks based on these scores.
    """

    def __init__(self, config: Optional[CrossEncoderConfig] = None):
        """
        Initialize the cross-encoder reranker.

        Args:
            config: Cross-encoder configuration.
        """
        self.config = config or CrossEncoderConfig()
        self._model = None
        self._tokenizer = None
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize the cross-encoder model.

        This is done lazily to avoid loading the model until needed.
        """
        if self._initialized:
            return

        try:
            # Import here to avoid loading transformers at module load time
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(
                self.config.model_name,
                max_length=self.config.max_length,
                device=self.config.device,
            )

            self._initialized = True
            logger.info(
                f"Cross-encoder initialized: {self.config.model_name} "
                f"on {self.config.device}"
            )
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Reranking will use fallback scoring."
            )
        except Exception as e:
            logger.error(f"Failed to initialize cross-encoder: {e}")
            raise

    async def rerank(
        self,
        query: str,
        results: list[HybridSearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedResult]:
        """
        Rerank search results using cross-encoder.

        Args:
            query: The original search query.
            results: Results from hybrid search to rerank.
            top_n: Number of top results to return. If None, returns all.

        Returns:
            Reranked results ordered by cross-encoder score.
        """
        if not results:
            return []

        # Initialize model if needed
        if not self._initialized:
            await self.initialize()

        # Prepare query-document pairs
        pairs = [
            (query, self._get_document_text(result))
            for result in results
        ]

        # Get cross-encoder scores
        if self._model is not None:
            scores = await self._compute_scores(pairs)
        else:
            # Fallback: use original hybrid scores normalized
            scores = self._fallback_scores(results)

        # Create reranked results
        scored_results = list(zip(results, scores, range(1, len(results) + 1)))

        # Sort by cross-encoder score (descending)
        scored_results.sort(key=lambda x: x[1], reverse=True)

        # Apply top_n limit
        if top_n is not None:
            scored_results = scored_results[:top_n]

        # Build reranked results with new rankings
        reranked = []
        for new_rank, (result, score, original_rank) in enumerate(scored_results, start=1):
            reranked.append(
                RerankedResult(
                    id=result.id,
                    entity_type=result.entity_type,
                    rerank_score=float(score),
                    original_rank=original_rank,
                    new_rank=new_rank,
                    hybrid_score=result.hybrid_score,
                    title=result.title,
                    content=result.content,
                    source_id=result.source_id,
                    source_name=result.source_name,
                    author=result.author,
                    published_at=result.published_at,
                    reliability_tier=result.reliability_tier,
                    url=result.url,
                    highlights=result.highlights,
                    metadata=result.metadata,
                )
            )

        return reranked

    async def _compute_scores(
        self,
        pairs: list[tuple[str, str]],
    ) -> list[float]:
        """
        Compute cross-encoder scores for query-document pairs.

        Args:
            pairs: List of (query, document) tuples.

        Returns:
            List of relevance scores.
        """
        import asyncio

        # Run inference in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(
            None,
            self._model.predict,
            pairs,
        )

        return scores.tolist() if hasattr(scores, "tolist") else list(scores)

    def _get_document_text(self, result: HybridSearchResult) -> str:
        """
        Extract text from a result for cross-encoder input.

        Args:
            result: The search result.

        Returns:
            Combined text from title and content.
        """
        parts = []

        if result.title:
            parts.append(result.title)

        if result.content:
            # Truncate content to fit within max_length
            max_content = self.config.max_length - 100  # Leave room for query
            content = result.content[:max_content]
            parts.append(content)

        return " ".join(parts) if parts else ""

    def _fallback_scores(self, results: list[HybridSearchResult]) -> list[float]:
        """
        Generate fallback scores when cross-encoder is not available.

        Uses normalized hybrid scores as fallback.

        Args:
            results: The search results.

        Returns:
            Normalized scores.
        """
        if not results:
            return []

        max_score = max(r.hybrid_score for r in results)
        if max_score == 0:
            return [0.0] * len(results)

        return [r.hybrid_score / max_score for r in results]

    async def batch_rerank(
        self,
        queries: list[str],
        results_per_query: list[list[HybridSearchResult]],
        top_n: Optional[int] = None,
    ) -> list[list[RerankedResult]]:
        """
        Rerank multiple queries in batch for efficiency.

        Args:
            queries: List of search queries.
            results_per_query: List of result lists, one per query.
            top_n: Number of top results to return per query.

        Returns:
            List of reranked result lists.
        """
        if len(queries) != len(results_per_query):
            raise ValueError("Number of queries must match number of result lists")

        # Initialize model if needed
        if not self._initialized:
            await self.initialize()

        # Collect all pairs and track boundaries
        all_pairs = []
        boundaries = [0]

        for query, results in zip(queries, results_per_query):
            pairs = [
                (query, self._get_document_text(result))
                for result in results
            ]
            all_pairs.extend(pairs)
            boundaries.append(len(all_pairs))

        # Get all scores at once
        if self._model is not None and all_pairs:
            all_scores = await self._compute_scores(all_pairs)
        else:
            # Fallback for each query
            all_scores = []
            for results in results_per_query:
                all_scores.extend(self._fallback_scores(results))

        # Split scores back by query
        reranked_lists = []
        for i, (query, results) in enumerate(zip(queries, results_per_query)):
            start = boundaries[i]
            end = boundaries[i + 1]
            scores = all_scores[start:end]

            # Create reranked results for this query
            scored_results = list(zip(results, scores, range(1, len(results) + 1)))
            scored_results.sort(key=lambda x: x[1], reverse=True)

            if top_n is not None:
                scored_results = scored_results[:top_n]

            reranked = []
            for new_rank, (result, score, original_rank) in enumerate(scored_results, start=1):
                reranked.append(
                    RerankedResult(
                        id=result.id,
                        entity_type=result.entity_type,
                        rerank_score=float(score),
                        original_rank=original_rank,
                        new_rank=new_rank,
                        hybrid_score=result.hybrid_score,
                        title=result.title,
                        content=result.content,
                        source_id=result.source_id,
                        source_name=result.source_name,
                        author=result.author,
                        published_at=result.published_at,
                        reliability_tier=result.reliability_tier,
                        url=result.url,
                        highlights=result.highlights,
                        metadata=result.metadata,
                    )
                )
            reranked_lists.append(reranked)

        return reranked_lists

    def analyze_rerank_impact(
        self,
        original_results: list[HybridSearchResult],
        reranked_results: list[RerankedResult],
    ) -> dict[str, Any]:
        """
        Analyze the impact of reranking on result ordering.

        Args:
            original_results: Results before reranking.
            reranked_results: Results after reranking.

        Returns:
            Analysis metrics.
        """
        if not original_results or not reranked_results:
            return {
                "total_results": 0,
                "results_changed_position": 0,
                "average_position_change": 0,
                "top_result_changed": False,
            }

        # Calculate position changes
        position_changes = []
        for result in reranked_results:
            change = abs(result.original_rank - result.new_rank)
            position_changes.append(change)

        results_changed = sum(1 for c in position_changes if c > 0)
        avg_change = sum(position_changes) / len(position_changes) if position_changes else 0

        # Check if top result changed
        original_top = original_results[0].id if original_results else None
        reranked_top = reranked_results[0].id if reranked_results else None
        top_changed = original_top != reranked_top

        return {
            "total_results": len(reranked_results),
            "results_changed_position": results_changed,
            "average_position_change": round(avg_change, 2),
            "max_position_change": max(position_changes) if position_changes else 0,
            "top_result_changed": top_changed,
            "position_changes": [
                {
                    "id": str(r.id),
                    "original_rank": r.original_rank,
                    "new_rank": r.new_rank,
                    "change": r.original_rank - r.new_rank,
                }
                for r in reranked_results
            ],
        }


class LLMReranker:
    """
    Alternative reranker using LLM for relevance scoring.

    Uses an LLM to assess relevance when cross-encoder is not suitable.
    This is slower but can provide better context understanding.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        max_concurrent: int = 5,
    ):
        """
        Initialize LLM reranker.

        Args:
            model: LLM model to use for scoring.
            max_concurrent: Maximum concurrent scoring requests.
        """
        self.model = model
        self.max_concurrent = max_concurrent
        self._client = None

    async def initialize(self) -> None:
        """Initialize the LLM client."""
        try:
            import anthropic
            from app.core.config import settings

            api_key = settings.anthropic_api_key
            if api_key:
                self._client = anthropic.AsyncAnthropic(
                    api_key=api_key.get_secret_value()
                )
                logger.info(f"LLM reranker initialized with model: {self.model}")
        except ImportError:
            logger.warning("anthropic package not installed")
        except Exception as e:
            logger.error(f"Failed to initialize LLM reranker: {e}")

    async def rerank(
        self,
        query: str,
        results: list[HybridSearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedResult]:
        """
        Rerank results using LLM relevance scoring.

        Args:
            query: The search query.
            results: Results to rerank.
            top_n: Number of top results to return.

        Returns:
            Reranked results.
        """
        if not results or not self._client:
            # Fallback to original ordering
            return self._convert_to_reranked(results, top_n)

        import asyncio

        # Score results with concurrency limit
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def score_result(idx: int, result: HybridSearchResult) -> tuple[int, float]:
            async with semaphore:
                score = await self._score_with_llm(query, result)
                return idx, score

        tasks = [
            score_result(i, result)
            for i, result in enumerate(results)
        ]

        scored = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any failures
        scores = [0.0] * len(results)
        for result in scored:
            if isinstance(result, tuple):
                idx, score = result
                scores[idx] = score

        # Create reranked results
        scored_results = list(zip(results, scores, range(1, len(results) + 1)))
        scored_results.sort(key=lambda x: x[1], reverse=True)

        if top_n is not None:
            scored_results = scored_results[:top_n]

        reranked = []
        for new_rank, (result, score, original_rank) in enumerate(scored_results, start=1):
            reranked.append(
                RerankedResult(
                    id=result.id,
                    entity_type=result.entity_type,
                    rerank_score=score,
                    original_rank=original_rank,
                    new_rank=new_rank,
                    hybrid_score=result.hybrid_score,
                    title=result.title,
                    content=result.content,
                    source_id=result.source_id,
                    source_name=result.source_name,
                    author=result.author,
                    published_at=result.published_at,
                    reliability_tier=result.reliability_tier,
                    url=result.url,
                    highlights=result.highlights,
                    metadata=result.metadata,
                )
            )

        return reranked

    async def _score_with_llm(
        self,
        query: str,
        result: HybridSearchResult,
    ) -> float:
        """Score a single result using LLM."""
        try:
            document = f"Title: {result.title or 'N/A'}\nContent: {result.content or 'N/A'}"

            prompt = f"""Rate the relevance of this document to the query on a scale of 0-10.
Only respond with a single number.

Query: {query}

Document:
{document[:1000]}

Relevance score (0-10):"""

            response = await self._client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse score from response
            score_text = response.content[0].text.strip()
            score = float(score_text)
            return min(max(score / 10.0, 0.0), 1.0)  # Normalize to 0-1

        except Exception as e:
            logger.warning(f"LLM scoring failed: {e}")
            return 0.5  # Default middle score

    def _convert_to_reranked(
        self,
        results: list[HybridSearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedResult]:
        """Convert hybrid results to reranked results without scoring."""
        if top_n is not None:
            results = results[:top_n]

        return [
            RerankedResult(
                id=r.id,
                entity_type=r.entity_type,
                rerank_score=r.hybrid_score,
                original_rank=i + 1,
                new_rank=i + 1,
                hybrid_score=r.hybrid_score,
                title=r.title,
                content=r.content,
                source_id=r.source_id,
                source_name=r.source_name,
                author=r.author,
                published_at=r.published_at,
                reliability_tier=r.reliability_tier,
                url=r.url,
                highlights=r.highlights,
                metadata=r.metadata,
            )
            for i, r in enumerate(results)
        ]
