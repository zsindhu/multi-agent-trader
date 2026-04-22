"""
EDGAR Service — Fetches SEC filings (10-K, 10-Q, 8-K) from the SEC's
EDGAR full-text search and company filings APIs.

Free, no API key. Rate limited to 10 requests/second by SEC policy.
Returns structured filing metadata and the filing text for LLM analysis.

Exposed as a Lead Agent tool: get_filing(symbol, filing_type).
"""
import asyncio
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

# SEC requires a User-Agent header with a real email address
SEC_USER_AGENT = "PremiumTrader research@premiumtrader.dev"
SEC_BASE_URL = "https://efts.sec.gov/LATEST"
SEC_FILINGS_URL = "https://data.sec.gov/submissions"

# Rate limit: SEC asks for max 10 req/sec
_RATE_LIMIT_SLEEP = 0.15  # 150ms between calls ≈ 6.7 req/sec (well under limit)


class EdgarService:
    """Fetches SEC filings from EDGAR."""

    def __init__(self):
        self._cik_cache: dict[str, str] = {}
        self._tickers_cache: Optional[dict] = None

    async def get_filing(
        self,
        symbol: str,
        filing_type: str = "10-K",
        max_results: int = 3,
    ) -> list[dict]:
        """
        Fetch recent filings for a symbol.

        Args:
            symbol: Ticker symbol (e.g., "AAPL")
            filing_type: "10-K", "10-Q", "8-K", etc.
            max_results: Number of recent filings to return

        Returns:
            List of dicts with filing metadata:
            [{
                "symbol": "AAPL",
                "filing_type": "10-K",
                "filed_date": "2025-11-01",
                "period_of_report": "2025-09-28",
                "accession_number": "0000320193-25-000106",
                "primary_document": "aapl-20250928.htm",
                "url": "https://...",
                "source": "edgar",
            }]
        """
        symbol = symbol.upper()

        try:
            # Step 1: Get CIK for the ticker
            cik = await self._get_cik(symbol)
            if not cik:
                logger.debug(f"[EDGAR] No CIK found for {symbol}")
                return []

            # Step 2: Get recent filings
            filings = await self._get_filings(cik, filing_type, max_results)
            for f in filings:
                f["symbol"] = symbol
                f["source"] = "edgar"

            return filings

        except Exception as e:
            logger.warning(f"[EDGAR] Failed to fetch {filing_type} for {symbol}: {e}")
            return []

    async def get_recent_filings_for_symbols(
        self,
        symbols: list[str],
        filing_type: str = "10-K",
    ) -> dict[str, list[dict]]:
        """
        Fetch the most recent filing for each symbol.

        Returns dict mapping symbol -> list of filing dicts.
        Rate-limited to respect SEC's 10 req/sec policy.
        """
        results = {}
        for symbol in symbols:
            try:
                filings = await self.get_filing(symbol, filing_type, max_results=1)
                results[symbol] = filings
            except Exception as e:
                logger.debug(f"[EDGAR] Skipping {symbol}: {e}")
                results[symbol] = []
            await asyncio.sleep(_RATE_LIMIT_SLEEP)

        return results

    async def fetch_filing_text(self, url: str, max_chars: int = 12000) -> Optional[str]:
        """
        Download a filing HTML from SEC and extract readable text.
        Returns first max_chars of cleaned text, or None on failure.
        """
        if not url:
            return None

        try:
            await asyncio.sleep(_RATE_LIMIT_SLEEP)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers={"User-Agent": SEC_USER_AGENT}, follow_redirects=True)
                if resp.status_code != 200:
                    logger.debug(f"[EDGAR] Filing fetch HTTP {resp.status_code}: {url}")
                    return None

                html = resp.text

            import re
            # Remove script/style/xbrl blocks
            text = re.sub(r'<(script|style|xbrl|ix:header)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
            # Remove inline XBRL tags but keep their text content
            text = re.sub(r'<ix:[^>]*>', '', text)
            text = re.sub(r'</ix:[^>]*>', '', text)
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', ' ', text)
            # Remove XBRL metadata lines (namespace URIs, booleans, technical identifiers)
            text = re.sub(r'http://\S+', '', text)
            text = re.sub(r'\b(true|false)\b', '', text, flags=re.IGNORECASE)
            # Collapse whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            # Skip past XBRL preamble — find first substantial paragraph
            # Look for "PART I" or "Item 1" or "ANNUAL REPORT" as start markers
            for marker in ['PART I', 'Item 1', 'ANNUAL REPORT', 'QUARTERLY REPORT']:
                idx = text.find(marker)
                if idx > 0 and idx < len(text) // 2:
                    text = text[idx:]
                    break

            return text[:max_chars] if text else None

        except Exception as e:
            logger.debug(f"[EDGAR] Filing text extraction failed: {e}")
            return None

    async def _get_cik(self, symbol: str) -> Optional[str]:
        """Look up the CIK (Central Index Key) for a ticker symbol via company_tickers.json."""
        if symbol in self._cik_cache:
            return self._cik_cache[symbol]

        tickers = await self._fetch_tickers_json()
        if tickers and symbol in tickers:
            cik = str(tickers[symbol]).zfill(10)
            self._cik_cache[symbol] = cik
            return cik
        return None

    async def _fetch_tickers_json(self) -> Optional[dict]:
        """Fetch the SEC company tickers JSON file. Cached for the session."""
        if self._tickers_cache is not None:
            return self._tickers_cache

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers={"User-Agent": SEC_USER_AGENT},
                )
                if resp.status_code != 200:
                    logger.warning(f"[EDGAR] Tickers JSON HTTP {resp.status_code}")
                    return None

                data = resp.json()
                self._tickers_cache = {
                    entry["ticker"]: entry["cik_str"]
                    for entry in data.values()
                    if "ticker" in entry and "cik_str" in entry
                }
                logger.info(f"[EDGAR] Loaded {len(self._tickers_cache)} ticker-CIK mappings")
                return self._tickers_cache
        except Exception as e:
            logger.debug(f"[EDGAR] Failed to fetch tickers JSON: {e}")
            return None

    async def _get_filings(self, cik: str, filing_type: str, max_results: int) -> list[dict]:
        """Fetch recent filings from the EDGAR submissions API."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{SEC_FILINGS_URL}/CIK{cik}.json",
                    headers={"User-Agent": SEC_USER_AGENT},
                )

                if resp.status_code != 200:
                    return []

                data = resp.json()
                recent = data.get("filings", {}).get("recent", {})

                forms = recent.get("form", [])
                dates = recent.get("filingDate", [])
                periods = recent.get("reportDate", [])
                accessions = recent.get("accessionNumber", [])
                primary_docs = recent.get("primaryDocument", [])

                results = []
                for i in range(len(forms)):
                    if forms[i] == filing_type:
                        accession_clean = accessions[i].replace("-", "")
                        results.append({
                            "filing_type": forms[i],
                            "filed_date": dates[i] if i < len(dates) else None,
                            "period_of_report": periods[i] if i < len(periods) else None,
                            "accession_number": accessions[i] if i < len(accessions) else None,
                            "primary_document": primary_docs[i] if i < len(primary_docs) else None,
                            "url": (
                                f"https://www.sec.gov/Archives/edgar/data/"
                                f"{cik.lstrip('0')}/{accession_clean}/"
                                f"{primary_docs[i]}"
                            ) if i < len(primary_docs) else None,
                        })
                        if len(results) >= max_results:
                            break

                return results

        except Exception as e:
            logger.debug(f"[EDGAR] Filings fetch failed for CIK {cik}: {e}")
            return []
