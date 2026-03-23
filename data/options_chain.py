"""
Options Chain Analyzer — Filter, score, and rank option contracts.
Supports both calls and puts with configurable strategy parameters.
"""
from datetime import datetime, timedelta
from typing import Optional

import yaml
from loguru import logger

from core.broker import Broker


def _load_strategies() -> dict:
    """Load strategy parameters from config/strategies.yaml."""
    try:
        with open("config/strategies.yaml", "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning("strategies.yaml not found, using defaults")
        return {}


class OptionsChainAnalyzer:
    """
    Analyzes and filters options chains for premium-selling strategies.

    Capabilities:
    - Filter by DTE range, delta range, minimum open interest
    - Calculate annualized return on capital
    - Find optimal strikes for covered calls, cash-secured puts, wheel
    - Support both calls and puts
    """

    def __init__(self, broker: Optional[Broker] = None):
        if broker is None:
            from services.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()
        self.broker = broker
        self.strategies = _load_strategies()

    async def get_filtered_chain(
        self,
        symbol: str,
        contract_type: str = "put",
        dte_min: int = 20,
        dte_max: int = 45,
        delta_min: Optional[float] = None,
        delta_max: Optional[float] = None,
        min_open_interest: int = 10,
        min_volume: int = 0,
        min_bid: float = 0.05,
    ) -> list[dict]:
        """
        Fetch and filter an options chain.

        Args:
            symbol: Underlying stock ticker
            contract_type: "call" or "put"
            dte_min: Minimum days to expiration
            dte_max: Maximum days to expiration
            delta_min: Minimum absolute delta (e.g. 0.15)
            delta_max: Maximum absolute delta (e.g. 0.35)
            min_open_interest: Minimum open interest for liquidity
            min_volume: Minimum daily volume
            min_bid: Minimum bid price (filter out worthless contracts)

        Returns:
            Filtered list of option contract dicts
        """
        now = datetime.now()
        exp_gte = (now + timedelta(days=dte_min)).strftime("%Y-%m-%d")
        exp_lte = (now + timedelta(days=dte_max)).strftime("%Y-%m-%d")

        chain = await self.broker.get_options_chain(
            symbol=symbol,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            contract_type=contract_type,
        )

        if not chain:
            return []

        filtered = []
        for contract in chain:
            # DTE filter (double-check against actual expiration)
            exp_date = datetime.strptime(contract["expiration"], "%Y-%m-%d")
            dte = (exp_date - now).days
            if dte < dte_min or dte > dte_max:
                continue

            # Add DTE to contract data
            contract["dte"] = dte

            # Delta filter (use absolute delta for comparison)
            abs_delta = abs(contract.get("delta", 0))
            if delta_min is not None and abs_delta < delta_min:
                continue
            if delta_max is not None and abs_delta > delta_max:
                continue

            # Liquidity filters
            if contract.get("open_interest", 0) < min_open_interest:
                continue
            if contract.get("volume", 0) < min_volume:
                continue
            if contract.get("bid", 0) < min_bid:
                continue

            filtered.append(contract)

        logger.info(
            f"Filtered {symbol} {contract_type}s: {len(filtered)}/{len(chain)} contracts "
            f"(DTE {dte_min}-{dte_max}, OI >= {min_open_interest})"
        )
        return filtered

    def calculate_annualized_return(
        self,
        premium: float,
        strike: float,
        dte: int,
        contract_type: str = "put",
    ) -> float:
        """
        Calculate annualized return on capital for a premium-selling strategy.

        For puts: Return = (premium / collateral) * (365 / DTE) * 100
        For calls: Return = (premium / strike) * (365 / DTE) * 100

        Args:
            premium: Premium received per share (mid price)
            strike: Strike price
            dte: Days to expiration
            contract_type: "call" or "put"

        Returns:
            Annualized return as a percentage (e.g. 24.5 = 24.5%)
        """
        if strike <= 0 or dte <= 0:
            return 0.0

        if contract_type.lower() == "put":
            # Collateral for a cash-secured put = strike * 100
            collateral_per_share = strike
        else:
            # For covered calls, capital is the share price (≈ strike for OTM)
            collateral_per_share = strike

        return_pct = (premium / collateral_per_share) * (365.0 / dte) * 100.0
        return round(return_pct, 2)

    def score_contract(
        self,
        contract: dict,
        current_price: float,
        strategy: str = "cash_secured_puts",
        weights: Optional[dict] = None,
    ) -> float:
        """
        Score and rank an option contract using a weighted composite.

        Factors:
        - Annualized return on capital (higher = better)
        - Probability of profit (1 - |delta|) (higher = better)
        - Distance OTM from current price (further = safer)
        - IV rank contribution (captured via premium level)

        Args:
            contract: Option contract dict from the chain
            current_price: Current stock price
            strategy: Strategy name to load weights from config
            weights: Override weights dict {return_weight, pop_weight, distance_weight}

        Returns:
            Composite score (higher is better)
        """
        if weights is None:
            # Default weights — can be overridden per strategy
            weights = {
                "return_weight": 0.40,
                "pop_weight": 0.35,
                "distance_weight": 0.25,
            }

        premium = contract.get("mid_price", 0)
        strike = contract.get("strike", 0)
        dte = contract.get("dte", 30)
        delta = contract.get("delta", 0)
        contract_type = contract.get("contract_type", "put")

        # Factor 1: Annualized return (normalize to 0-1 range, cap at 100%)
        ann_return = self.calculate_annualized_return(premium, strike, dte, contract_type)
        contract["annualized_return"] = ann_return
        return_score = min(ann_return / 50.0, 1.0)  # 50% annual = max score

        # Factor 2: Probability of profit
        pop = 1.0 - abs(delta)
        contract["probability_of_profit"] = round(pop * 100, 1)
        pop_score = pop

        # Factor 3: Distance from current price (OTM distance)
        if current_price > 0:
            if contract_type == "put":
                distance_pct = (current_price - strike) / current_price
            else:  # call
                distance_pct = (strike - current_price) / current_price
            distance_pct = max(0, distance_pct)
        else:
            distance_pct = 0

        contract["distance_otm_pct"] = round(distance_pct * 100, 2)
        distance_score = min(distance_pct / 0.15, 1.0)  # 15% OTM = max score

        # Composite score
        score = (
            weights["return_weight"] * return_score
            + weights["pop_weight"] * pop_score
            + weights["distance_weight"] * distance_score
        )

        contract["score"] = round(score, 4)
        return score

    async def find_optimal_puts(
        self,
        symbol: str,
        current_price: float,
        strategy_name: str = "cash_secured_puts",
        top_n: int = 5,
    ) -> list[dict]:
        """
        Find the best put contracts to sell for a given symbol.

        Uses strategy parameters from strategies.yaml.
        """
        params = self.strategies.get(strategy_name, {})
        delta_target = abs(params.get("delta_target", 0.25))
        dte_min = params.get("dte_min", 20)
        dte_max = params.get("dte_max", 45)

        # Filter around the target delta (± 0.10)
        chain = await self.get_filtered_chain(
            symbol=symbol,
            contract_type="put",
            dte_min=dte_min,
            dte_max=dte_max,
            delta_min=max(0.10, delta_target - 0.10),
            delta_max=min(0.50, delta_target + 0.10),
            min_open_interest=10,
        )

        if not chain:
            logger.info(f"No qualifying puts found for {symbol}")
            return []

        # Score each contract
        for contract in chain:
            self.score_contract(contract, current_price, strategy_name)

        # Sort by score descending
        chain.sort(key=lambda c: c.get("score", 0), reverse=True)

        return chain[:top_n]

    async def find_optimal_calls(
        self,
        symbol: str,
        current_price: float,
        strategy_name: str = "covered_calls",
        top_n: int = 5,
    ) -> list[dict]:
        """
        Find the best call contracts to sell for a given symbol.

        Uses strategy parameters from strategies.yaml.
        """
        params = self.strategies.get(strategy_name, {})
        delta_target = abs(params.get("delta_target", 0.30))
        dte_min = params.get("dte_min", 20)
        dte_max = params.get("dte_max", 45)

        chain = await self.get_filtered_chain(
            symbol=symbol,
            contract_type="call",
            dte_min=dte_min,
            dte_max=dte_max,
            delta_min=max(0.10, delta_target - 0.15),
            delta_max=min(0.50, delta_target + 0.15),
            min_open_interest=10,
        )

        if not chain:
            logger.info(f"No qualifying calls found for {symbol}")
            return []

        # Score each contract
        for contract in chain:
            self.score_contract(contract, current_price, strategy_name)

        chain.sort(key=lambda c: c.get("score", 0), reverse=True)
        return chain[:top_n]

    async def find_wheel_contracts(
        self,
        symbol: str,
        current_price: float,
        wheel_state: str = "selling_puts",
        top_n: int = 3,
    ) -> list[dict]:
        """
        Find optimal contracts for the wheel strategy based on current state.
        """
        params = self.strategies.get("wheel", {})

        if wheel_state == "selling_puts":
            delta_target = abs(params.get("csp_delta", 0.25))
            return await self.find_optimal_puts(
                symbol, current_price, strategy_name="wheel", top_n=top_n
            )
        elif wheel_state == "selling_calls":
            delta_target = abs(params.get("cc_delta", 0.30))
            return await self.find_optimal_calls(
                symbol, current_price, strategy_name="wheel", top_n=top_n
            )
        else:
            return []
