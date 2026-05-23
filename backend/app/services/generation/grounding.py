"""
Grounding Enforcement

Ensures every non-trivial claim in generated content is backed by a citation
to source material. Provides quality metrics and flagging for ungrounded content.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

import anthropic
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.generation.base import Citation, SourceMaterial

logger = logging.getLogger(__name__)


class ClaimType(str, Enum):
    """Types of claims that may require grounding."""

    FACTUAL = "factual"  # Verifiable facts
    STATISTICAL = "statistical"  # Numbers, percentages, metrics
    QUOTATION = "quotation"  # Direct quotes
    ATTRIBUTION = "attribution"  # "X said/reported"
    CAUSAL = "causal"  # Cause and effect claims
    TEMPORAL = "temporal"  # Time-based claims
    COMPARATIVE = "comparative"  # Comparisons
    ANALYTICAL = "analytical"  # Analysis/interpretation (may not need citation)


class UngroundedClaim(BaseModel):
    """Details of an ungrounded claim."""

    text: str = Field(..., description="The ungrounded claim text")
    claim_type: ClaimType = Field(default=ClaimType.FACTUAL)
    sentence_index: int = Field(default=0)
    line_number: Optional[int] = None
    severity: str = Field(
        default="warning",
        description="Severity: 'error' requires fix, 'warning' is advisory",
    )
    suggestion: Optional[str] = Field(
        default=None,
        description="Suggested fix or citation",
    )
    potential_sources: List[UUID] = Field(
        default_factory=list,
        description="Source IDs that might support this claim",
    )


class GroundingResult(BaseModel):
    """Result of grounding analysis."""

    grounding_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Percentage of claims that are grounded (0-1)",
    )
    total_claims: int = Field(default=0)
    grounded_claims: int = Field(default=0)
    ungrounded_count: int = Field(default=0)
    ungrounded_claims: List[str] = Field(
        default_factory=list,
        description="List of ungrounded claim texts",
    )
    detailed_issues: List[UngroundedClaim] = Field(
        default_factory=list,
        description="Detailed information about ungrounded claims",
    )
    warnings: List[str] = Field(default_factory=list)
    meets_threshold: bool = Field(default=False)
    analysis_metadata: Dict[str, Any] = Field(default_factory=dict)


class GroundingConfig(BaseModel):
    """Configuration for grounding enforcement."""

    min_score_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum grounding score to pass",
    )
    require_statistical_citations: bool = Field(
        default=True,
        description="Require citations for all statistics",
    )
    require_quote_citations: bool = Field(
        default=True,
        description="Require citations for all quotes",
    )
    allow_analytical_uncited: bool = Field(
        default=True,
        description="Allow analytical statements without citations",
    )
    min_claim_length: int = Field(
        default=30,
        description="Minimum characters for a sentence to be considered a claim",
    )
    use_llm_verification: bool = Field(
        default=False,
        description="Use LLM to verify claim-citation alignment",
    )


class GroundingEnforcer:
    """
    Enforces grounding requirements for generated content.

    Analyzes content to:
    - Identify factual claims requiring citations
    - Verify citation coverage
    - Flag ungrounded sentences
    - Compute grounding quality score
    - Optionally use LLM for deeper verification
    """

    def __init__(
        self,
        config: Optional[GroundingConfig] = None,
        client: Optional[anthropic.Anthropic] = None,
    ):
        """
        Initialize the grounding enforcer.

        Args:
            config: Grounding configuration
            client: Anthropic client for LLM verification
        """
        self.config = config or GroundingConfig()
        self.client = client

        # Patterns for identifying claim types
        self._statistical_patterns = [
            r"\b\d+\.?\d*%\b",  # Percentages
            r"\b\d+\.?\d*\s*(million|billion|trillion|thousand)\b",  # Large numbers
            r"\b(increased|decreased|rose|fell|grew|declined)\s+by\s+\d+",
            r"\b(up|down)\s+\d+",
            r"\baverage\s+of\s+\d+",
            r"\b(doubled|tripled|halved)\b",
        ]

        self._quotation_patterns = [
            r'"[^"]{20,}"',  # Quoted text 20+ chars
            r"'[^']{20,}'",
            r'\u201c[^\u201d]+\u201d',  # Smart quotes
        ]

        self._attribution_patterns = [
            r"\b(according to|stated|said|reported|announced|revealed)\b",
            r"\b(spokesperson|official|representative|CEO|president)\s+said\b",
            r"\b(company|organization|government|study|report)\s+(said|stated|found)\b",
        ]

        self._analytical_patterns = [
            r"^(This|These|The)\s+(suggests?|indicates?|shows?|demonstrates?)\b",
            r"\b(likely|probably|possibly|perhaps|might|could|may)\b",
            r"\b(analysis|assessment|evaluation|interpretation)\s+(shows?|suggests?)\b",
            r"^(In\s+summary|Overall|In\s+conclusion|Therefore|Thus)\b",
            r"\b(we\s+can\s+see|it\s+appears|this\s+means)\b",
        ]

    def check_grounding(
        self,
        content: str,
        citations: List[Citation],
        sources: List[SourceMaterial],
    ) -> GroundingResult:
        """
        Check grounding of content against citations and sources.

        Args:
            content: Generated content to verify
            citations: Citations found in content
            sources: Available source materials

        Returns:
            GroundingResult with score and issues
        """
        result = GroundingResult()

        # Split content into sentences
        sentences = self._split_into_sentences(content)

        # Build citation index set for quick lookup
        cited_source_ids = {c.item_id for c in citations}

        claims = []
        grounded = []
        ungrounded = []

        for idx, sentence in enumerate(sentences):
            # Skip non-claim sentences
            if not self._is_potential_claim(sentence):
                continue

            claim_type = self._classify_claim(sentence)

            # Analytical claims may not need citations
            if (
                claim_type == ClaimType.ANALYTICAL
                and self.config.allow_analytical_uncited
            ):
                continue

            claims.append(sentence)

            # Check if sentence has citation
            if self._has_citation(sentence):
                grounded.append(sentence)
            else:
                ungrounded.append(sentence)

                # Create detailed issue
                severity = self._determine_severity(sentence, claim_type)
                potential = self._find_potential_sources(sentence, sources)

                result.detailed_issues.append(
                    UngroundedClaim(
                        text=sentence[:200],
                        claim_type=claim_type,
                        sentence_index=idx,
                        severity=severity,
                        potential_sources=potential,
                    )
                )

        # Calculate score
        result.total_claims = len(claims)
        result.grounded_claims = len(grounded)
        result.ungrounded_count = len(ungrounded)
        result.ungrounded_claims = [s[:150] + "..." if len(s) > 150 else s for s in ungrounded]

        if claims:
            result.grounding_score = len(grounded) / len(claims)
        else:
            result.grounding_score = 1.0  # No claims = fully grounded

        result.meets_threshold = result.grounding_score >= self.config.min_score_threshold

        # Add warnings
        if not result.meets_threshold:
            result.warnings.append(
                f"Grounding score {result.grounding_score:.2%} is below "
                f"threshold {self.config.min_score_threshold:.2%}"
            )

        if result.ungrounded_count > 0:
            result.warnings.append(
                f"Found {result.ungrounded_count} ungrounded claims"
            )

        # Add metadata
        result.analysis_metadata = {
            "total_sentences": len(sentences),
            "claim_sentences": len(claims),
            "citation_count": len(citations),
            "source_count": len(sources),
        }

        return result

    def _split_into_sentences(self, content: str) -> List[str]:
        """Split content into sentences."""
        # Handle common abbreviations
        text = content
        text = re.sub(r"\b(Mr|Mrs|Ms|Dr|Prof|Inc|Ltd|Corp|vs|etc)\.", r"\1<PERIOD>", text)

        # Split on sentence boundaries
        sentences = re.split(r"(?<=[.!?])\s+", text)

        # Restore periods
        sentences = [s.replace("<PERIOD>", ".").strip() for s in sentences]

        return [s for s in sentences if s]

    def _is_potential_claim(self, sentence: str) -> bool:
        """Determine if a sentence is a potential factual claim."""
        # Too short
        if len(sentence) < self.config.min_claim_length:
            return False

        # Headers
        if sentence.strip().startswith("#"):
            return False

        # Just a citation or reference
        if re.match(r"^\[\d+\]", sentence.strip()):
            return False

        # Empty list items
        if re.match(r"^[-*]\s*$", sentence.strip()):
            return False

        return True

    def _classify_claim(self, sentence: str) -> ClaimType:
        """Classify the type of claim in a sentence."""
        sentence_lower = sentence.lower()

        # Check for statistics
        for pattern in self._statistical_patterns:
            if re.search(pattern, sentence_lower):
                return ClaimType.STATISTICAL

        # Check for quotes
        for pattern in self._quotation_patterns:
            if re.search(pattern, sentence):
                return ClaimType.QUOTATION

        # Check for attributions
        for pattern in self._attribution_patterns:
            if re.search(pattern, sentence_lower):
                return ClaimType.ATTRIBUTION

        # Check for analytical statements
        for pattern in self._analytical_patterns:
            if re.search(pattern, sentence, re.IGNORECASE):
                return ClaimType.ANALYTICAL

        # Default to factual
        return ClaimType.FACTUAL

    def _has_citation(self, sentence: str) -> bool:
        """Check if a sentence contains a citation marker."""
        return bool(re.search(r"\[\d+\]", sentence))

    def _determine_severity(self, sentence: str, claim_type: ClaimType) -> str:
        """Determine severity of an ungrounded claim."""
        # Statistics and quotes are high severity
        if claim_type in (ClaimType.STATISTICAL, ClaimType.QUOTATION):
            return "error"

        # Attributions are medium
        if claim_type == ClaimType.ATTRIBUTION:
            return "error"

        # Factual claims are warnings
        return "warning"

    def _find_potential_sources(
        self,
        sentence: str,
        sources: List[SourceMaterial],
    ) -> List[UUID]:
        """Find sources that might support a claim."""
        potential = []

        # Simple keyword matching
        sentence_words = set(
            re.findall(r"\b[a-zA-Z]{4,}\b", sentence.lower())
        )

        for source in sources:
            source_words = set(
                re.findall(r"\b[a-zA-Z]{4,}\b", source.content.lower())
            )

            # Calculate word overlap
            overlap = len(sentence_words & source_words)
            if overlap >= 3:  # At least 3 shared significant words
                potential.append(source.item_id)

        return potential[:3]  # Return top 3

    def flag_ungrounded_sentences(
        self,
        content: str,
        sources: List[SourceMaterial],
    ) -> str:
        """
        Return content with ungrounded sentences flagged.

        Args:
            content: Content to analyze
            sources: Available source materials

        Returns:
            Content with flags added (e.g., [NEEDS CITATION])
        """
        sentences = self._split_into_sentences(content)
        flagged_parts = []

        for sentence in sentences:
            if not self._is_potential_claim(sentence):
                flagged_parts.append(sentence)
                continue

            claim_type = self._classify_claim(sentence)

            if (
                claim_type == ClaimType.ANALYTICAL
                and self.config.allow_analytical_uncited
            ):
                flagged_parts.append(sentence)
                continue

            if not self._has_citation(sentence):
                flagged_parts.append(f"{sentence} [NEEDS CITATION]")
            else:
                flagged_parts.append(sentence)

        return " ".join(flagged_parts)

    def compute_grounding_score(
        self,
        content: str,
        citations: List[Citation],
    ) -> float:
        """
        Compute a simple grounding score.

        Args:
            content: Content to analyze
            citations: Citations in content

        Returns:
            Score from 0 to 1
        """
        sentences = self._split_into_sentences(content)

        claims = [
            s for s in sentences
            if self._is_potential_claim(s)
            and self._classify_claim(s) != ClaimType.ANALYTICAL
        ]

        if not claims:
            return 1.0

        cited = sum(1 for s in claims if self._has_citation(s))
        return cited / len(claims)

    async def verify_with_llm(
        self,
        content: str,
        citations: List[Citation],
        sources: List[SourceMaterial],
    ) -> GroundingResult:
        """
        Use LLM to verify claim-citation alignment.

        This is a more thorough but slower verification that checks
        if citations actually support the claims they're attached to.

        Args:
            content: Content to verify
            citations: Citations in content
            sources: Source materials

        Returns:
            Detailed grounding result
        """
        if not self.client:
            api_key = settings.anthropic_api_key
            if api_key:
                self.client = anthropic.Anthropic(api_key=api_key.get_secret_value())
            else:
                self.client = anthropic.Anthropic()

        # Build source context
        source_context = "\n".join(
            f"[Source {i+1}] {s.title}\n{s.content[:1000]}"
            for i, s in enumerate(sources)
        )

        prompt = f"""Analyze the following content for grounding quality. For each factual claim,
verify if it is properly supported by the cited sources.

CONTENT TO ANALYZE:
{content}

AVAILABLE SOURCES:
{source_context}

Analyze each factual claim and determine:
1. Is there a citation present?
2. Does the cited source actually support the claim?
3. Are there any misleading or unsupported statements?

Respond in this format:
<analysis>
<total_claims>N</total_claims>
<properly_grounded>N</properly_grounded>
<weakly_grounded>N</weakly_grounded>
<ungrounded>N</ungrounded>
<issues>
- Issue 1: description
- Issue 2: description
</issues>
<grounding_score>0.XX</grounding_score>
</analysis>
"""

        try:
            response = self.client.messages.create(
                model=settings.anthropic_model,
                max_tokens=2048,
                temperature=0.1,
                messages=[{"role": "user", "content": prompt}],
            )

            analysis = response.content[0].text
            return self._parse_llm_analysis(analysis)

        except Exception as e:
            logger.error(f"LLM verification failed: {e}")
            # Fall back to rule-based analysis
            return self.check_grounding(content, citations, sources)

    def _parse_llm_analysis(self, analysis: str) -> GroundingResult:
        """Parse LLM analysis response into GroundingResult."""
        result = GroundingResult()

        # Extract values using regex
        total_match = re.search(r"<total_claims>(\d+)</total_claims>", analysis)
        grounded_match = re.search(r"<properly_grounded>(\d+)</properly_grounded>", analysis)
        score_match = re.search(r"<grounding_score>([\d.]+)</grounding_score>", analysis)
        issues_match = re.search(r"<issues>(.*?)</issues>", analysis, re.DOTALL)

        if total_match:
            result.total_claims = int(total_match.group(1))
        if grounded_match:
            result.grounded_claims = int(grounded_match.group(1))
        if score_match:
            try:
                result.grounding_score = float(score_match.group(1))
            except ValueError:
                pass

        if issues_match:
            issues_text = issues_match.group(1).strip()
            issues = re.findall(r"- (.+?)(?:\n|$)", issues_text)
            result.ungrounded_claims = issues

        result.ungrounded_count = result.total_claims - result.grounded_claims
        result.meets_threshold = result.grounding_score >= self.config.min_score_threshold

        return result

    def generate_grounding_report(
        self,
        result: GroundingResult,
    ) -> str:
        """
        Generate a human-readable grounding report.

        Args:
            result: Grounding analysis result

        Returns:
            Formatted report string
        """
        lines = [
            "## Grounding Analysis Report",
            "",
            f"**Grounding Score:** {result.grounding_score:.1%}",
            f"**Status:** {'PASS' if result.meets_threshold else 'NEEDS ATTENTION'}",
            "",
            "### Statistics",
            f"- Total claims analyzed: {result.total_claims}",
            f"- Properly grounded: {result.grounded_claims}",
            f"- Ungrounded: {result.ungrounded_count}",
            "",
        ]

        if result.ungrounded_claims:
            lines.extend([
                "### Ungrounded Claims",
                "",
            ])
            for i, claim in enumerate(result.ungrounded_claims[:10], 1):
                lines.append(f"{i}. {claim}")
            lines.append("")

        if result.warnings:
            lines.extend([
                "### Warnings",
                "",
            ])
            for warning in result.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        if result.detailed_issues:
            lines.extend([
                "### Detailed Issues",
                "",
            ])
            for issue in result.detailed_issues[:5]:
                lines.append(f"- **{issue.severity.upper()}** ({issue.claim_type.value})")
                lines.append(f"  Text: \"{issue.text}\"")
                if issue.potential_sources:
                    lines.append(f"  Potential sources: {len(issue.potential_sources)} found")
                lines.append("")

        return "\n".join(lines)
