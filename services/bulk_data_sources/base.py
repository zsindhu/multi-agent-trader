"""
Base adapter interface for bulk historical data sources.

Each source adapter (Stooq, yfinance, Kaggle, etc.) inherits from
BulkDataSourceAdapter and implements fetch_bars(). Adapters are
self-contained — they know their source's format and normalize to
the standard bar dict format defined in this module.
"""
from abc import ABC, abstractmethod
from datetime import date


class BulkDataSourceAdapter(ABC):
    """Abstract base for a bulk historical data source adapter."""

    # Subclasses must set this to a short lowercase identifier
    # ('stooq', 'yfinance', 'kaggle', etc.)
    source_name: str = None

    @abstractmethod
    async def fetch_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """
        Fetch daily bars for the given symbols and date range.

        Returns a list of bar dicts in the standard format:
            {
                "symbol": str,           # ticker, uppercase
                "bar_date": date,        # Python date object
                "open": float,
                "high": float,
                "low": float,
                "close": float,
                "volume": int,
                "vwap": Optional[float],
                "trade_count": Optional[int],
                "source": str,
            }

        Adapters log warnings for individual symbol failures but continue
        processing the rest of the batch. Adapters raise an exception
        only if the entire source is unreachable.
        """
        raise NotImplementedError
