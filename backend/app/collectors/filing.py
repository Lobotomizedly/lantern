"""
SEC EDGAR filing collector for the Lantern Narrative Intelligence Platform.

Supports:
- SEC EDGAR RSS feed monitoring
- Filing metadata extraction
- Filing content download and parsing
- Support for various form types (10-K, 10-Q, 8-K, etc.)
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import aiohttp
import structlog
from bs4 import BeautifulSoup

from .base import (
    BaseCollector,
    RateLimitConfig,
    CircuitBreakerConfig,
    RetryConfig,
)


class FilingType(Enum):
    """Common SEC filing types."""
    FORM_10K = "10-K"
    FORM_10K_A = "10-K/A"  # Amendment
    FORM_10Q = "10-Q"
    FORM_10Q_A = "10-Q/A"
    FORM_8K = "8-K"
    FORM_8K_A = "8-K/A"
    FORM_4 = "4"  # Insider trading
    FORM_13F = "13F-HR"  # Institutional holdings
    FORM_S1 = "S-1"  # IPO registration
    FORM_DEF14A = "DEF 14A"  # Proxy statement
    FORM_20F = "20-F"  # Foreign company annual report
    FORM_6K = "6-K"  # Foreign company current report
    SC_13D = "SC 13D"  # Beneficial ownership
    SC_13G = "SC 13G"  # Beneficial ownership (passive)
    OTHER = "OTHER"

    @classmethod
    def from_string(cls, form_type: str) -> "FilingType":
        """Convert string to FilingType."""
        form_type = form_type.upper().strip()
        for ft in cls:
            if ft.value == form_type:
                return ft
            # Handle variations
            if form_type.startswith(ft.value.replace(" ", "")):
                return ft
        return cls.OTHER


@dataclass
class FilingMetadata:
    """SEC filing metadata."""
    accession_number: str
    form_type: FilingType
    form_type_raw: str
    company_name: str
    cik: str
    filed_date: datetime
    accepted_date: Optional[datetime]
    period_of_report: Optional[datetime]
    filing_url: str
    primary_document_url: Optional[str]
    primary_document_name: Optional[str]
    file_number: Optional[str]
    film_number: Optional[str]
    sic_code: Optional[str]
    state_of_incorporation: Optional[str]
    fiscal_year_end: Optional[str]
    items_reported: List[str] = field(default_factory=list)  # For 8-K
    raw_data: Dict[str, Any] = field(default_factory=dict)
    dedup_hash: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "accession_number": self.accession_number,
            "form_type": self.form_type.value,
            "form_type_raw": self.form_type_raw,
            "company_name": self.company_name,
            "cik": self.cik,
            "filed_date": self.filed_date.isoformat(),
            "accepted_date": self.accepted_date.isoformat() if self.accepted_date else None,
            "period_of_report": self.period_of_report.isoformat() if self.period_of_report else None,
            "filing_url": self.filing_url,
            "primary_document_url": self.primary_document_url,
            "primary_document_name": self.primary_document_name,
            "file_number": self.file_number,
            "film_number": self.film_number,
            "sic_code": self.sic_code,
            "state_of_incorporation": self.state_of_incorporation,
            "fiscal_year_end": self.fiscal_year_end,
            "items_reported": self.items_reported,
            "dedup_hash": self.dedup_hash,
            "collected_at": self.collected_at.isoformat(),
        }


@dataclass
class FilingDocument:
    """Parsed filing document."""
    filing_metadata: FilingMetadata
    document_type: str
    filename: str
    content_type: str
    raw_content: str
    clean_text: Optional[str]
    sections: Dict[str, str] = field(default_factory=dict)
    exhibits: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "filing_metadata": self.filing_metadata.to_dict(),
            "document_type": self.document_type,
            "filename": self.filename,
            "content_type": self.content_type,
            "clean_text": self.clean_text,
            "sections": self.sections,
            "exhibits": self.exhibits,
            "tables": self.tables,
        }


class EDGARClient:
    """Client for SEC EDGAR API and RSS feeds."""

    BASE_URL = "https://www.sec.gov"
    EDGAR_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"
    FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
    RSS_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

    # SEC rate limit: 10 requests per second
    USER_AGENT = "Lantern/1.0 (contact@lantern.ai)"

    def __init__(self):
        self.logger = structlog.get_logger(__name__)

    async def get_company_filings_rss(
        self,
        cik: str,
        form_types: Optional[List[str]] = None,
        count: int = 40,
    ) -> List[Dict[str, Any]]:
        """
        Get company filings via RSS feed.

        Args:
            cik: Company CIK number
            form_types: Filter by form types
            count: Number of filings to return

        Returns:
            List of filing entries
        """
        # Format CIK (pad with zeros)
        cik = cik.lstrip("0").zfill(10)

        params = {
            "action": "getcompany",
            "CIK": cik,
            "type": form_types[0] if form_types and len(form_types) == 1 else "",
            "dateb": "",
            "owner": "include",
            "count": count,
            "output": "atom",
        }

        url = f"{self.RSS_FEED_URL}?{'&'.join(f'{k}={v}' for k, v in params.items() if v)}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                content = await response.text()

        return self._parse_atom_feed(content, form_types)

    def _parse_atom_feed(
        self,
        content: str,
        form_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Parse EDGAR Atom feed."""
        entries = []

        try:
            root = ElementTree.fromstring(content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns):
                # Extract data
                title = entry.findtext("atom:title", "", ns)
                updated = entry.findtext("atom:updated", "", ns)

                link_elem = entry.find("atom:link", ns)
                link = link_elem.get("href", "") if link_elem is not None else ""

                summary = entry.findtext("atom:summary", "", ns)

                # Parse filing info from title
                # Format: "10-K - Company Name (0001234567) (Filer)"
                form_match = re.match(r"^([A-Z0-9\-/]+)\s*-", title)
                form_type = form_match.group(1).strip() if form_match else ""

                # Filter by form type
                if form_types and form_type not in form_types:
                    continue

                # Parse CIK from title
                cik_match = re.search(r"\((\d{10})\)", title)
                cik = cik_match.group(1) if cik_match else ""

                # Extract company name
                company_match = re.match(r"^[A-Z0-9\-/]+\s*-\s*(.+?)\s*\(\d{10}\)", title)
                company_name = company_match.group(1).strip() if company_match else ""

                # Parse accession number from link
                acc_match = re.search(r"/(\d+-\d+-\d+)", link)
                accession_number = acc_match.group(1) if acc_match else ""

                entries.append({
                    "title": title,
                    "link": link,
                    "updated": updated,
                    "summary": summary,
                    "form_type": form_type,
                    "cik": cik,
                    "company_name": company_name,
                    "accession_number": accession_number,
                })

        except ElementTree.ParseError as e:
            self.logger.error("atom_parse_error", error=str(e))

        return entries

    async def get_latest_filings_rss(
        self,
        form_types: Optional[List[str]] = None,
        count: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get latest filings across all companies.

        Args:
            form_types: Filter by form types
            count: Number of filings to return

        Returns:
            List of filing entries
        """
        all_entries = []

        # Get feeds for each form type
        if form_types:
            for form_type in form_types:
                url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&company=&dateb=&owner=include&count={count}&output=atom"

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            url,
                            headers={"User-Agent": self.USER_AGENT},
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as response:
                            response.raise_for_status()
                            content = await response.text()

                    entries = self._parse_atom_feed(content)
                    all_entries.extend(entries)

                except Exception as e:
                    self.logger.error(
                        "latest_filings_error",
                        form_type=form_type,
                        error=str(e),
                    )
        else:
            url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&company=&dateb=&owner=include&count={count}&output=atom"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    response.raise_for_status()
                    content = await response.text()

            all_entries = self._parse_atom_feed(content)

        return all_entries

    async def get_filing_index(self, accession_number: str, cik: str) -> Dict[str, Any]:
        """
        Get filing index with document list.

        Args:
            accession_number: Filing accession number
            cik: Company CIK

        Returns:
            Filing index data
        """
        cik = cik.lstrip("0").zfill(10)
        acc_no_dashes = accession_number.replace("-", "")

        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{acc_no_dashes}/{accession_number}-index.json"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                index_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 404:
                    # Try HTML index
                    return await self._get_filing_index_html(accession_number, cik)
                response.raise_for_status()
                return await response.json()

    async def _get_filing_index_html(
        self,
        accession_number: str,
        cik: str,
    ) -> Dict[str, Any]:
        """Parse filing index from HTML page."""
        cik = cik.lstrip("0").zfill(10)
        acc_no_dashes = accession_number.replace("-", "")

        index_url = f"{self.BASE_URL}/Archives/edgar/data/{cik}/{acc_no_dashes}/"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                index_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        documents = []

        # Find document table
        table = soup.find("table", {"summary": "Document Format Files"})
        if table:
            for row in table.find_all("tr")[1:]:  # Skip header
                cols = row.find_all("td")
                if len(cols) >= 4:
                    link = cols[2].find("a")
                    documents.append({
                        "sequence": cols[0].get_text(strip=True),
                        "description": cols[1].get_text(strip=True),
                        "document": link.get_text(strip=True) if link else "",
                        "url": urljoin(index_url, link["href"]) if link else "",
                        "type": cols[3].get_text(strip=True),
                        "size": cols[4].get_text(strip=True) if len(cols) > 4 else "",
                    })

        return {
            "directory": {
                "name": accession_number,
                "item": documents,
            }
        }

    async def download_document(self, url: str) -> str:
        """
        Download filing document content.

        Args:
            url: Document URL

        Returns:
            Document content
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                response.raise_for_status()
                return await response.text()


class FilingParser:
    """Parser for SEC filing documents."""

    # 10-K/10-Q sections
    ANNUAL_SECTIONS = [
        "ITEM 1. BUSINESS",
        "ITEM 1A. RISK FACTORS",
        "ITEM 1B. UNRESOLVED STAFF COMMENTS",
        "ITEM 2. PROPERTIES",
        "ITEM 3. LEGAL PROCEEDINGS",
        "ITEM 4. MINE SAFETY DISCLOSURES",
        "ITEM 5. MARKET FOR REGISTRANT'S COMMON EQUITY",
        "ITEM 6. SELECTED FINANCIAL DATA",
        "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS",
        "ITEM 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK",
        "ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA",
        "ITEM 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS",
        "ITEM 9A. CONTROLS AND PROCEDURES",
        "ITEM 9B. OTHER INFORMATION",
        "ITEM 10. DIRECTORS, EXECUTIVE OFFICERS AND CORPORATE GOVERNANCE",
        "ITEM 11. EXECUTIVE COMPENSATION",
        "ITEM 12. SECURITY OWNERSHIP",
        "ITEM 13. CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS",
        "ITEM 14. PRINCIPAL ACCOUNTANT FEES AND SERVICES",
        "ITEM 15. EXHIBITS AND FINANCIAL STATEMENT SCHEDULES",
    ]

    # 8-K items
    CURRENT_REPORT_ITEMS = {
        "1.01": "Entry into a Material Definitive Agreement",
        "1.02": "Termination of a Material Definitive Agreement",
        "1.03": "Bankruptcy or Receivership",
        "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
        "2.01": "Completion of Acquisition or Disposition of Assets",
        "2.02": "Results of Operations and Financial Condition",
        "2.03": "Creation of a Direct Financial Obligation",
        "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
        "2.05": "Costs Associated with Exit or Disposal Activities",
        "2.06": "Material Impairments",
        "3.01": "Notice of Delisting or Failure to Satisfy Listing Rule",
        "3.02": "Unregistered Sales of Equity Securities",
        "3.03": "Material Modification to Rights of Security Holders",
        "4.01": "Changes in Registrant's Certifying Accountant",
        "4.02": "Non-Reliance on Previously Issued Financial Statements",
        "5.01": "Changes in Control of Registrant",
        "5.02": "Departure/Election of Directors or Officers; Compensatory Arrangements",
        "5.03": "Amendments to Articles of Incorporation or Bylaws",
        "5.04": "Temporary Suspension of Trading Under Employee Benefit Plans",
        "5.05": "Amendments to Code of Ethics",
        "5.06": "Change in Shell Company Status",
        "5.07": "Submission of Matters to a Vote of Security Holders",
        "5.08": "Shareholder Director Nominations",
        "6.01": "ABS Informational and Computational Material",
        "6.02": "Change of Servicer or Trustee",
        "6.03": "Change in Credit Enhancement or Other External Support",
        "6.04": "Failure to Make a Required Distribution",
        "6.05": "Securities Act Updating Disclosure",
        "7.01": "Regulation FD Disclosure",
        "8.01": "Other Events",
        "9.01": "Financial Statements and Exhibits",
    }

    def __init__(self):
        self.logger = structlog.get_logger(__name__)

    def parse_html_filing(self, html: str) -> Tuple[str, Dict[str, str]]:
        """
        Parse HTML filing document.

        Args:
            html: Raw HTML content

        Returns:
            Tuple of (clean_text, sections_dict)
        """
        soup = BeautifulSoup(html, "html.parser")

        # Remove scripts and styles
        for element in soup(["script", "style"]):
            element.decompose()

        # Get full text
        clean_text = soup.get_text(separator="\n", strip=True)
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text)

        # Extract sections
        sections = {}
        text_upper = clean_text.upper()

        for section in self.ANNUAL_SECTIONS:
            # Find section start
            pattern = section.replace(".", r"\.").replace(" ", r"\s+")
            match = re.search(pattern, text_upper)
            if match:
                start = match.start()
                # Find next section or end
                end = len(clean_text)
                for next_section in self.ANNUAL_SECTIONS:
                    if next_section != section:
                        next_pattern = next_section.replace(".", r"\.").replace(" ", r"\s+")
                        next_match = re.search(next_pattern, text_upper[start + len(section):])
                        if next_match:
                            end = min(end, start + len(section) + next_match.start())

                section_text = clean_text[start:end].strip()
                # Normalize section name
                section_key = section.lower().replace(" ", "_").replace(".", "")
                sections[section_key] = section_text

        return clean_text, sections

    def extract_8k_items(self, text: str) -> List[str]:
        """
        Extract reported items from 8-K filing.

        Args:
            text: Filing text

        Returns:
            List of item numbers reported
        """
        items = []
        text_upper = text.upper()

        for item_num in self.CURRENT_REPORT_ITEMS.keys():
            escaped_item = item_num.replace('.', r'\.')
            pattern = rf"ITEM\s+{escaped_item}"
            if re.search(pattern, text_upper):
                items.append(item_num)

        return items

    def extract_tables(self, html: str) -> List[Dict[str, Any]]:
        """
        Extract tables from HTML filing.

        Args:
            html: Raw HTML content

        Returns:
            List of table data
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = []

        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                row = []
                for cell in tr.find_all(["td", "th"]):
                    row.append(cell.get_text(strip=True))
                if row:
                    rows.append(row)

            if rows:
                tables.append({
                    "rows": rows,
                    "header": rows[0] if rows else [],
                    "data": rows[1:] if len(rows) > 1 else [],
                })

        return tables


class FilingCollector(BaseCollector[FilingMetadata]):
    """
    SEC EDGAR filing collector.

    Supports:
    - Company filing monitoring
    - Latest filings feed
    - Filing content download and parsing
    - Multiple form type filtering
    """

    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        retry_config: Optional[RetryConfig] = None,
        monitored_ciks: Optional[List[str]] = None,
        monitored_form_types: Optional[List[str]] = None,
    ):
        """
        Initialize filing collector.

        Args:
            rate_limit_config: Rate limiting configuration
            circuit_breaker_config: Circuit breaker configuration
            retry_config: Retry configuration
            monitored_ciks: List of CIKs to monitor
            monitored_form_types: List of form types to collect
        """
        super().__init__(
            name="filing",
            rate_limit_config=rate_limit_config or RateLimitConfig(
                requests_per_second=10.0,  # SEC limit
                requests_per_minute=100.0,
                requests_per_hour=1000.0,
            ),
            circuit_breaker_config=circuit_breaker_config,
            retry_config=retry_config,
        )

        self.client = EDGARClient()
        self.parser = FilingParser()
        self.monitored_ciks = monitored_ciks or []
        self.monitored_form_types = monitored_form_types or [
            "10-K", "10-Q", "8-K", "4", "DEF 14A"
        ]

    def register_company(self, cik: str) -> None:
        """Add company CIK to monitoring list."""
        cik = cik.lstrip("0").zfill(10)
        if cik not in self.monitored_ciks:
            self.monitored_ciks.append(cik)
            self.logger.info("company_registered", cik=cik)

    async def fetch(
        self,
        subject_name: str,
        aliases: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        ciks: Optional[List[str]] = None,
        form_types: Optional[List[str]] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch SEC filings.

        Args:
            subject_name: Not directly used (use CIKs instead)
            aliases: Not used for SEC filings
            since: Start of time range
            until: End of time range
            ciks: Company CIKs to fetch (overrides monitored_ciks)
            form_types: Form types to fetch (overrides monitored_form_types)

        Returns:
            List of raw filing data
        """
        target_ciks = ciks or self.monitored_ciks
        target_form_types = form_types or self.monitored_form_types

        all_filings = []

        if target_ciks:
            # Fetch for specific companies
            tasks = [
                self.client.get_company_filings_rss(
                    cik=cik,
                    form_types=target_form_types,
                    count=40,
                )
                for cik in target_ciks
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for cik, result in zip(target_ciks, results):
                if isinstance(result, Exception):
                    self.logger.error(
                        "company_filings_error",
                        cik=cik,
                        error=str(result),
                    )
                    self.metrics.errors += 1
                else:
                    all_filings.extend(result)
        else:
            # Fetch latest filings across all companies
            filings = await self.client.get_latest_filings_rss(
                form_types=target_form_types,
                count=100,
            )
            all_filings.extend(filings)

        # Filter by date
        if since or until:
            filtered = []
            for filing in all_filings:
                try:
                    updated = filing.get("updated", "")
                    if updated:
                        filing_date = datetime.fromisoformat(
                            updated.replace("Z", "+00:00")
                        )
                        if since and filing_date < since:
                            continue
                        if until and filing_date > until:
                            continue
                    filtered.append(filing)
                except (ValueError, TypeError):
                    filtered.append(filing)  # Include if can't parse date
            all_filings = filtered

        self.logger.info(
            "filings_fetched",
            total_filings=len(all_filings),
            ciks=len(target_ciks) if target_ciks else "all",
        )

        return all_filings

    def normalize(self, raw_item: Dict[str, Any]) -> FilingMetadata:
        """
        Normalize raw filing data to FilingMetadata.

        Args:
            raw_item: Raw filing data from RSS feed

        Returns:
            Normalized FilingMetadata
        """
        # Parse dates
        filed_date = datetime.now(tz=timezone.utc)
        if raw_item.get("updated"):
            try:
                filed_date = datetime.fromisoformat(
                    raw_item["updated"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        form_type_raw = raw_item.get("form_type", "")
        form_type = FilingType.from_string(form_type_raw)

        filing = FilingMetadata(
            accession_number=raw_item.get("accession_number", ""),
            form_type=form_type,
            form_type_raw=form_type_raw,
            company_name=raw_item.get("company_name", ""),
            cik=raw_item.get("cik", ""),
            filed_date=filed_date,
            accepted_date=None,
            period_of_report=None,
            filing_url=raw_item.get("link", ""),
            primary_document_url=None,
            primary_document_name=None,
            file_number=None,
            film_number=None,
            sic_code=None,
            state_of_incorporation=None,
            fiscal_year_end=None,
            items_reported=[],
            raw_data=raw_item,
            dedup_hash="",
        )

        filing.dedup_hash = self.compute_dedup_hash(filing)
        return filing

    def compute_dedup_hash(self, item: FilingMetadata) -> str:
        """
        Compute deduplication hash for filing.

        Uses accession number as unique identifier.
        """
        return self.hash_content(item.accession_number)

    async def download_and_parse_filing(
        self,
        filing: FilingMetadata,
    ) -> Optional[FilingDocument]:
        """
        Download and parse full filing content.

        Args:
            filing: Filing metadata

        Returns:
            Parsed filing document or None on failure
        """
        try:
            # Get filing index
            index = await self.client.get_filing_index(
                filing.accession_number,
                filing.cik,
            )

            # Find primary document
            items = index.get("directory", {}).get("item", [])
            primary_doc = None
            for item in items:
                doc_name = item.get("document", "").lower()
                if doc_name.endswith(".htm") or doc_name.endswith(".html"):
                    # Prefer documents that match common naming patterns
                    if any(x in doc_name for x in ["10k", "10q", "8k", "def14a"]):
                        primary_doc = item
                        break
                    elif not primary_doc:
                        primary_doc = item

            if not primary_doc:
                self.logger.warning(
                    "no_primary_document",
                    accession_number=filing.accession_number,
                )
                return None

            # Download document
            doc_url = primary_doc.get("url", "")
            if not doc_url.startswith("http"):
                cik = filing.cik.lstrip("0").zfill(10)
                acc_no = filing.accession_number.replace("-", "")
                doc_url = f"{self.client.BASE_URL}/Archives/edgar/data/{cik}/{acc_no}/{primary_doc['document']}"

            content = await self.client.download_document(doc_url)

            # Parse content
            clean_text, sections = self.parser.parse_html_filing(content)

            # Extract 8-K items if applicable
            items_reported = []
            if filing.form_type in [FilingType.FORM_8K, FilingType.FORM_8K_A]:
                items_reported = self.parser.extract_8k_items(clean_text)

            # Update filing with items
            filing.items_reported = items_reported
            filing.primary_document_url = doc_url
            filing.primary_document_name = primary_doc.get("document", "")

            return FilingDocument(
                filing_metadata=filing,
                document_type=primary_doc.get("type", ""),
                filename=primary_doc.get("document", ""),
                content_type="text/html",
                raw_content=content,
                clean_text=clean_text,
                sections=sections,
                exhibits=[],
                tables=[],
            )

        except Exception as e:
            self.logger.error(
                "filing_parse_error",
                accession_number=filing.accession_number,
                error=str(e),
            )
            return None
