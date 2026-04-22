"""
Signal-Weight Learner — Logistic regression over Tier 2a signal scores
vs binary trade outcomes (win/loss).

Runs monthly (or on-demand). Reads from trade_outcomes where
funnel_driven=true, extracts the 11 signal scores from signal_profile,
fits a logistic regression, and proposes updated weights.

Output:
- config/learned_weights.json with per-rule weights + metadata
- agent_messages entry documenting what changed

Does NOT auto-apply weights. Human reviews and updates tier2a.yaml.
This is the manual review gate — no autonomous tuning.

Uses numpy-only logistic regression (no sklearn dependency).
"""
import json
import math
import os
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy import select

from core.database import AsyncSessionLocal
from models.trade_outcome import TradeOutcome
from models.agent_message import AgentMessage


# The 11 Tier 2a signal names in canonical order
SIGNAL_NAMES = [
    "volume_zscore",
    "range_expansion",
    "gap_zscore",
    "iv_rank_delta",
    "correlation_breakdown",
    "earnings_proximity",
    "news_density",
    "put_call_ratio",
    "volume_oi_ratio",
    "short_interest",
    "social_velocity",
]

# Initial weights from tier2a.yaml (baseline for bounded drift)
INITIAL_WEIGHTS = {
    "volume_zscore": 0.20,
    "range_expansion": 0.15,
    "gap_zscore": 0.15,
    "iv_rank_delta": 0.20,
    "correlation_breakdown": 0.15,
    "earnings_proximity": 0.15,
    "news_density": 0.15,
    "put_call_ratio": 0.10,
    "volume_oi_ratio": 0.10,
    "short_interest": 0.10,
    "social_velocity": 0.10,
}

# Safety bounds: no weight can exceed 3x initial or drop below 0.3x
DRIFT_MAX = 3.0
DRIFT_MIN = 0.3

MIN_SAMPLES = 50
CONFIDENCE_THRESHOLD = 200  # Below this, log warning about low confidence

OUTPUT_PATH = "config/learned_weights.json"


class SignalLearner:
    """Fits logistic regression on signal scores vs trade outcomes."""

    async def run(self, dry_run: bool = False) -> dict:
        """
        Fit the model and produce proposed weights.
        Returns summary dict.
        """
        logger.info(f"[Learner] Starting signal-weight learning (dry_run={dry_run})")

        # Step 1: Load funnel-driven outcomes
        X, y, sample_size = await self._load_data()

        if sample_size < MIN_SAMPLES:
            logger.warning(
                f"[Learner] Only {sample_size} funnel-driven outcomes "
                f"(need {MIN_SAMPLES}). Skipping."
            )
            return {"skipped": True, "reason": f"insufficient_samples ({sample_size}/{MIN_SAMPLES})"}

        if sample_size < CONFIDENCE_THRESHOLD:
            logger.warning(
                f"[Learner] {sample_size} samples — directional signal only, "
                f"not statistically robust (need {CONFIDENCE_THRESHOLD} for confidence)"
            )

        # Step 2: Fit logistic regression
        coefficients, intercept = self._fit_logistic(X, y)

        # Step 3: Convert coefficients to proposed weights
        proposed = self._coefficients_to_weights(coefficients)

        # Step 4: Apply safety bounds
        bounded = self._apply_bounds(proposed)

        # Step 5: Compute diagnostics
        diagnostics = self._compute_diagnostics(coefficients, X, y)

        # Step 6: Build output
        output = {
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "sample_size": sample_size,
            "confidence": "high" if sample_size >= CONFIDENCE_THRESHOLD else "low",
            "win_rate": float(np.mean(y)),
            "weights": bounded,
            "diagnostics": diagnostics,
            "initial_weights": INITIAL_WEIGHTS,
        }

        if dry_run:
            print(f"\n--- Proposed Weights (n={sample_size}) ---")
            for name in SIGNAL_NAMES:
                init = INITIAL_WEIGHTS[name]
                prop = bounded[name]
                change = ((prop - init) / init * 100) if init > 0 else 0
                flag = diagnostics.get(name, {}).get("ci_crosses_zero", False)
                marker = " ⚠ CI crosses zero" if flag else ""
                print(f"  {name:25s} {init:.3f} → {prop:.3f} ({change:+.0f}%){marker}")
            return output

        # Write to file
        try:
            with open(OUTPUT_PATH, "w") as f:
                json.dump(output, f, indent=2, default=str)
            logger.info(f"[Learner] Wrote proposed weights to {OUTPUT_PATH}")
        except Exception as e:
            logger.error(f"[Learner] Failed to write weights file: {e}")

        # Log to agent_messages
        try:
            async with AsyncSessionLocal() as session:
                session.add(AgentMessage(
                    sender="Signal-Learner",
                    message_type="weight_update",
                    subject=f"Weight proposal {datetime.now(timezone.utc).date().isoformat()}",
                    body=self._format_summary(bounded, diagnostics, sample_size),
                    payload=output,
                ))
                await session.commit()
        except Exception as e:
            logger.error(f"[Learner] Failed to log weight update: {e}")

        return output

    async def _load_data(self) -> tuple:
        """Load signal scores and outcomes from trade_outcomes."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TradeOutcome)
                .where(TradeOutcome.funnel_driven == True)
                .where(TradeOutcome.outcome.in_(["win", "loss"]))
            )
            outcomes = list(result.scalars().all())

        if not outcomes:
            return np.array([]), np.array([]), 0

        X_rows = []
        y_rows = []

        for o in outcomes:
            profile = o.signal_profile or {}
            signals = profile.get("signals", {})

            # Extract score for each signal (0.0 if missing)
            row = [signals.get(name, {}).get("score", 0.0) for name in SIGNAL_NAMES]
            X_rows.append(row)
            y_rows.append(1.0 if o.outcome == "win" else 0.0)

        return np.array(X_rows), np.array(y_rows), len(outcomes)

    def _fit_logistic(self, X: np.ndarray, y: np.ndarray) -> tuple:
        """
        Fit logistic regression using gradient descent (numpy only).
        Returns (coefficients, intercept).
        """
        n_samples, n_features = X.shape

        # Normalize features
        means = X.mean(axis=0)
        stds = X.std(axis=0)
        stds[stds == 0] = 1.0
        X_norm = (X - means) / stds

        # Add intercept column
        X_aug = np.column_stack([X_norm, np.ones(n_samples)])

        # Initialize weights
        w = np.zeros(n_features + 1)

        # Gradient descent with L2 regularization for numerical stability
        lr = 0.1
        reg = 0.01  # L2 penalty
        for _ in range(1000):
            z = X_aug @ w
            pred = 1.0 / (1.0 + np.exp(-np.clip(z, -250, 250)))
            grad = X_aug.T @ (pred - y) / n_samples + reg * w
            w -= lr * grad

        # Denormalize coefficients
        coefficients = w[:n_features] / stds
        intercept = w[-1] - (means / stds) @ w[:n_features]

        return coefficients, float(intercept)

    def _coefficients_to_weights(self, coefficients: np.ndarray) -> dict:
        """Convert logistic regression coefficients to normalized weights."""
        # Use absolute coefficient magnitude as importance
        abs_coefs = np.abs(coefficients)
        total = abs_coefs.sum()

        if total == 0:
            return dict(INITIAL_WEIGHTS)

        # Normalize to sum to ~1.0 (matching the tier2a weight convention)
        normalized = abs_coefs / total
        return {name: round(float(normalized[i]), 4) for i, name in enumerate(SIGNAL_NAMES)}

    def _apply_bounds(self, proposed: dict) -> dict:
        """Apply safety bounds: no weight exceeds 3x or drops below 0.3x initial."""
        bounded = {}
        for name in SIGNAL_NAMES:
            init = INITIAL_WEIGHTS[name]
            prop = proposed.get(name, init)
            lower = init * DRIFT_MIN
            upper = init * DRIFT_MAX
            bounded[name] = round(max(lower, min(upper, prop)), 4)
        return bounded

    def _compute_diagnostics(self, coefficients: np.ndarray, X: np.ndarray, y: np.ndarray) -> dict:
        """Compute per-signal diagnostics including approximate confidence intervals."""
        diagnostics = {}
        n = len(y)

        for i, name in enumerate(SIGNAL_NAMES):
            coef = float(coefficients[i])
            # Approximate standard error (simplified — proper SE needs Hessian)
            se = 1.0 / max(1, math.sqrt(n)) if n > 0 else 1.0

            # 95% CI approximation
            ci_low = coef - 1.96 * se
            ci_high = coef + 1.96 * se
            crosses_zero = ci_low <= 0 <= ci_high

            # Correlation with outcome
            if X.shape[0] > 0:
                signal_vals = X[:, i]
                if signal_vals.std() > 0:
                    corr = float(np.corrcoef(signal_vals, y)[0, 1])
                else:
                    corr = 0.0
            else:
                corr = 0.0

            diagnostics[name] = {
                "coefficient": round(coef, 4),
                "correlation_with_wins": round(corr, 4),
                "ci_low": round(ci_low, 4),
                "ci_high": round(ci_high, 4),
                "ci_crosses_zero": crosses_zero,
            }

        return diagnostics

    def _format_summary(self, weights: dict, diagnostics: dict, n: int) -> str:
        """Format a human-readable summary for the agent_message body."""
        lines = [f"Signal weight proposal based on {n} labeled outcomes.\n"]

        if n < CONFIDENCE_THRESHOLD:
            lines.append(f"⚠ LOW CONFIDENCE: {n} samples (recommend {CONFIDENCE_THRESHOLD}+)\n")

        lines.append(f"{'Signal':25s} {'Initial':>8s} {'Proposed':>8s} {'Change':>8s} {'Corr w/Win':>10s}")
        lines.append("-" * 65)

        for name in SIGNAL_NAMES:
            init = INITIAL_WEIGHTS[name]
            prop = weights[name]
            change = ((prop - init) / init * 100) if init > 0 else 0
            diag = diagnostics.get(name, {})
            corr = diag.get("correlation_with_wins", 0)
            flag = " ⚠" if diag.get("ci_crosses_zero") else ""
            lines.append(f"{name:25s} {init:8.3f} {prop:8.3f} {change:+7.0f}% {corr:10.3f}{flag}")

        return "\n".join(lines)
