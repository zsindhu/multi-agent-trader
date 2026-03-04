from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    database_url: str = "sqlite+aiosqlite:///./premium_trader.db"
    redis_url: str = "redis://localhost:6379/0"
    trading_mode: str = "paper"
    max_portfolio_risk: float = 0.02
    max_drawdown: float = 0.10
    max_position_pct: float = 0.15
    scan_interval_minutes: int = 15
    market_open: str = "09:30"
    market_close: str = "16:00"
    discord_webhook_url: Optional[str] = None

    model_config = {"env_file": ".env"}


settings = Settings()
