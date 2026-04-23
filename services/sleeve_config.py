"""
Sleeve Configuration — Loads and validates per-sleeve YAML configs.

Each sleeve config specifies: scanner criteria, Tier 2a weight overrides,
capital allocation, strategy parameters, and universe filters.

The SleeveOrchestrator uses these configs to run per-sleeve Lead Agent
calls with tailored contexts.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml
from loguru import logger


SLEEVES_DIR = "config/sleeves"

# Default weight for signals not explicitly overridden
DEFAULT_SIGNAL_WEIGHT = 0.05


@dataclass
class SleeveConfig:
    """Configuration for a single strategy sleeve."""
    id: str
    name: str
    description: str
    capital_allocation: float
    scanner_filter: dict = field(default_factory=dict)
    strategy: dict = field(default_factory=dict)
    weight_overrides: dict = field(default_factory=dict)

    @property
    def max_positions(self) -> int:
        return self.strategy.get("max_concurrent_positions", 5)

    @property
    def trade_type(self) -> str:
        return self.strategy.get("trade_type", "csp")

    @property
    def delta_target(self) -> float:
        return self.strategy.get("delta_target", -0.25)

    @property
    def dte_range(self) -> tuple:
        return (self.strategy.get("dte_min", 20), self.strategy.get("dte_max", 45))

    def get_signal_weight(self, signal_name: str) -> float:
        """Get the weight for a signal, using sleeve override or default."""
        return self.weight_overrides.get(signal_name, DEFAULT_SIGNAL_WEIGHT)


def load_sleeve_configs(directory: str = SLEEVES_DIR) -> dict[str, SleeveConfig]:
    """
    Load all sleeve configs from the config/sleeves/ directory.
    Returns dict mapping sleeve_id -> SleeveConfig.
    """
    configs = {}

    if not os.path.isdir(directory):
        logger.warning(f"[Sleeves] Config directory {directory} not found")
        return configs

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".yaml"):
            continue

        filepath = os.path.join(directory, filename)
        try:
            with open(filepath) as f:
                raw = yaml.safe_load(f)

            sleeve_data = raw.get("sleeve", {})
            sleeve_id = sleeve_data.get("id")
            if not sleeve_id:
                logger.warning(f"[Sleeves] No 'id' in {filename}, skipping")
                continue

            config = SleeveConfig(
                id=sleeve_id,
                name=sleeve_data.get("name", sleeve_id),
                description=sleeve_data.get("description", ""),
                capital_allocation=sleeve_data.get("capital_allocation", 100000),
                scanner_filter=sleeve_data.get("scanner_filter", {}),
                strategy=sleeve_data.get("strategy", {}),
                weight_overrides=sleeve_data.get("weight_overrides", {}),
            )
            configs[sleeve_id] = config
            logger.info(f"[Sleeves] Loaded sleeve '{config.name}' (${config.capital_allocation:,.0f})")

        except Exception as e:
            logger.error(f"[Sleeves] Failed to load {filename}: {e}")

    logger.info(f"[Sleeves] {len(configs)} sleeve configs loaded")
    return configs
