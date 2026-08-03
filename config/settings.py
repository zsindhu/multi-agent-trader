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
    # Ceiling, not a target. GLM-5.2's hidden reasoning tokens share this
    # budget with visible content — at 4096, 11 of 12 sleeve envelopes (and
    # their ACTIONS) were truncated away on 2026-07-13. See
    # RECON_ENVELOPE_DEGRADATION.md.
    llm_max_tokens: int = 16384

    # ── Order fill: near-touch pricing + deterministic poll-and-chase ──
    # Root-cause fix for "submitted but unfilled → expired at 16:00 ET":
    # orders are priced at the near touch (sell at the bid, buy at the ask)
    # so they are immediately marketable, then polled. An order still
    # working after chase_poll_seconds is cancelled and re-submitted one
    # step more aggressive, up to chase_max_attempts, bounded by
    # chase_max_cross past the original touch. Fully deterministic — no LLM.
    # Set CHASE_ENABLED=false to revert to a single near-touch submit.
    chase_enabled: bool = True
    chase_poll_seconds: float = 15.0    # wait between fill polls
    chase_max_attempts: int = 3         # re-prices after the initial submit
    chase_step: float = 0.02            # price improvement per re-price ($/sh)
    chase_max_cross: float = 0.10       # hard cap past the touch ($/sh)

    model_config = {"env_file": ".env"}


settings = Settings()
