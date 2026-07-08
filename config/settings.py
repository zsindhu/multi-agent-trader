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
    scan_interval_minutes: int = 20
    market_open: str = "09:30"
    market_close: str = "16:00"
    discord_webhook_url: Optional[str] = None
    finnhub_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    together_api_key: str = ""
    # Lead Agent LLM — any OpenAI-compatible endpoint. Auth uses
    # together_api_key. Migrated from Anthropic claude-sonnet-4-6 (July 2026).
    llm_model: str = "zai-org/GLM-5.2"
    llm_base_url: str = "https://api.together.xyz/v1"
    llm_max_tokens: int = 4096

    model_config = {"env_file": ".env"}


settings = Settings()
