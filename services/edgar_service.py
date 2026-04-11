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

# SEC requires a User-Agent header with contact info
SEC_USER_AGENT = "PremiumTrader/1.0 (research sandbox; contact: github.com/zsindhu)"
SEC_BASE_URL = "https://efts.sec.gov/LATEST"
SEC_FILINGS_URL = "https://data.sec.gov/submissions"

# Rate limit: SEC asks for max 10 req/sec
_RATE_LIMIT_SLEEP = 0.15  # 150ms between calls ≈ 6.7 req/sec (well under limit)


class EdgarService:
    """Fetches SEC filings from EDGAR."""

    def __init__(self):
        self._cik_cache: dict[str, str] = {}

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

    async def _get_cik(self, symbol: str) -> Optional[str]:
        """Look up the CIK (Central Index Key) for a ticker symbol."""
        if symbol in self._cik_cache:
            return self._cik_cache[symbol]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://www.sec.gov/cgi-bin/browse-edgar",
                    params={
                        "company": "",
                        "CIK": symbol,
                        "type": "",
                        "dateb": "",
                        "owner": "include",
                        "count": "1",
                        "search_text": "",
                        "action": "getcompany",
                        "output": "atom",
                    },
                    headers={"User-Agent": SEC_USER_AGENT},
                    follow_redirects=True,
                )

                if resp.status_code != 200:
                    return None

                # Try the company tickers JSON endpoint (more reliable)
                resp2 = await client.get(
                    "https://www.sec.gov/cgi-bin/browse-edgar",
                    params={"action": "getcompany", "company": "", "CIK": symbol,
                            "type": "", "dateb": "", "owner": "include", "count": "1",
                            "search_text": "", "output": "atom"},
                    headers={"User-Agent": SEC_USER_AGENT},
                    follow_redirects=True,
                )

            await asyncio.sleep(_RATE_LIMIT_SLEEP)

            # Parse CIK from the tickers endpoint
            tickers_resp = await self._fetch_tickers_json()
            if tickers_resp and symbol in tickers_resp:
                cik = str(tickers_resp[symbol]).zfill(10)
                self._cik_cache[symbol] = cik
                return cik

            return None

        except Exception as e:
            logger.debug(f"[EDGAR] CIK lookup failed for {symbol}: {e}")
            return None

    async def _fetch_tickers_json(self) -> Optional[dict]:
        """Fetch the SEC company tickers JSON file."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://www.sec.gov/files/company_tickers.json",
                    headers={"User-Agent": SEC_USER_AGENT},
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
                return {
                    entry["ticker"]: entry["cik_str"]
                    for entry in data.values()
                    if "ticker" in entry and "cik_str" in entry
                }
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
