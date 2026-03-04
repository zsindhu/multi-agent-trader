"""
Notifier — Discord webhook notifications for trade alerts, risk warnings,
and daily summaries.

Uses httpx (already in requirements.txt) for async POST to Discord.
If no webhook URL is configured, logs warnings but never crashes.

Usage:
    notifier = Notifier()
    await notifier.send_trade_alert(trade_data)
    await notifier.send_risk_warning("Drawdown exceeded 5%")
    await notifier.send_daily_summary(summary_data)
"""
from datetime import datetime
from typing import Optional

import httpx
from loguru import logger

from config.settings import settings


class Notifier:
    """
    Discord webhook notifier for Premium Trader events.

    All methods are fire-and-forget — failures are logged, never raised.
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self._webhook_url = webhook_url or settings.discord_webhook_url
        self._enabled = bool(self._webhook_url)

        if not self._enabled:
            logger.warning(
                "[Notifier] No Discord webhook URL configured — "
                "notifications will be logged only"
            )

    # ── Trade Alerts ──────────────────────────────────────────────

    async def send_trade_alert(self, trade: dict):
        """
        Notify when a worker executes a trade.

        Args:
            trade: Dict with keys: agent, symbol, strategy, side, strike,
                   premium, dte, delta, contracts, order_id
        """
        agent = trade.get("agent", "Unknown")
        symbol = trade.get("symbol", "?")
        strategy = trade.get("strategy", "?")
        side = trade.get("side", "sell")
        strike = trade.get("strike", 0)
        premium = trade.get("premium", 0)
        dte = trade.get("dte", 0)
        delta = trade.get("delta", 0)
        contracts = trade.get("contracts", 1)

        title = f"{'🟢' if side == 'sell' else '🔴'} Trade Executed — {symbol}"
        description = (
            f"**{agent}** • {strategy}\n"
            f"**{side.upper()}** {contracts}x {symbol} "
            f"${strike:.0f} {'P' if 'put' in strategy.lower() or 'csp' in strategy.lower() else 'C'}\n"
            f"Premium: **${premium * 100:.0f}** per contract\n"
            f"DTE: {dte} days • Delta: {abs(delta):.2f}"
        )

        embed = self._build_embed(
            title=title,
            description=description,
            color=0x10B981 if side == "sell" else 0xEF4444,  # green / red
            fields=[
                {"name": "Agent", "value": agent, "inline": True},
                {"name": "Strategy", "value": strategy, "inline": True},
                {"name": "Symbol", "value": symbol, "inline": True},
            ],
        )

        await self._send(embed)
        logger.info(
            f"[Notifier] Trade alert: {side.upper()} {contracts}x {symbol} "
            f"${strike} @ ${premium:.2f}"
        )

    # ── Risk Warnings ─────────────────────────────────────────────

    async def send_risk_warning(self, message: str, details: Optional[dict] = None):
        """
        Notify on risk events (drawdown breach, worker paused, etc.).

        Args:
            message: Human-readable warning message
            details: Optional dict with extra context
        """
        title = "⚠️ Risk Warning"
        description = message

        fields = []
        if details:
            if "drawdown" in details:
                fields.append({
                    "name": "Current Drawdown",
                    "value": f"{details['drawdown']:.1%}",
                    "inline": True,
                })
            if "worker" in details:
                fields.append({
                    "name": "Worker",
                    "value": details["worker"],
                    "inline": True,
                })
            if "action" in details:
                fields.append({
                    "name": "Action Taken",
                    "value": details["action"],
                    "inline": True,
                })

        embed = self._build_embed(
            title=title,
            description=description,
            color=0xF59E0B,  # amber
            fields=fields,
        )

        await self._send(embed)
        logger.warning(f"[Notifier] Risk warning: {message}")

    # ── Daily Summary ─────────────────────────────────────────────

    async def send_daily_summary(self, summary: dict):
        """
        End-of-day summary notification.

        Args:
            summary: Dict with keys: total_pnl, premium_collected, trades_executed,
                     portfolio_value, equity, cash, regime, agent_performance (list)
        """
        pnl = summary.get("total_pnl", 0)
        premium = summary.get("premium_collected", 0)
        trades = summary.get("trades_executed", 0)
        port_value = summary.get("portfolio_value", 0)
        equity = summary.get("equity", 0)
        cash = summary.get("cash", 0)
        regime = summary.get("regime", "normal")

        pnl_emoji = "📈" if pnl >= 0 else "📉"
        title = f"{pnl_emoji} Daily Summary — {datetime.now().strftime('%b %d, %Y')}"

        description = (
            f"**P&L Today**: ${pnl:+,.2f}\n"
            f"**Premium Collected**: ${premium:,.2f}\n"
            f"**Trades Executed**: {trades}\n"
            f"**Portfolio Value**: ${port_value:,.2f}\n"
            f"**Market Regime**: {regime}"
        )

        fields = [
            {"name": "Equity", "value": f"${equity:,.2f}", "inline": True},
            {"name": "Cash", "value": f"${cash:,.2f}", "inline": True},
            {"name": "Trades", "value": str(trades), "inline": True},
        ]

        # Per-agent performance
        agents = summary.get("agent_performance", [])
        if agents:
            agent_lines = []
            for a in agents:
                name = a.get("name", "?")
                win_rate = a.get("win_rate", 0)
                agent_pnl = a.get("pnl", 0)
                agent_lines.append(f"• **{name}**: {win_rate:.0f}% WR, ${agent_pnl:+,.2f}")
            fields.append({
                "name": "Agent Performance",
                "value": "\n".join(agent_lines),
                "inline": False,
            })

        embed = self._build_embed(
            title=title,
            description=description,
            color=0x6366F1,  # indigo
            fields=fields,
        )

        await self._send(embed)
        logger.info(f"[Notifier] Daily summary sent: P&L ${pnl:+,.2f}, {trades} trades")

    # ── Cycle Complete ────────────────────────────────────────────

    async def send_cycle_summary(self, cycle_results: dict):
        """
        Brief notification after each orchestration cycle.

        Only sends if there were actual trades or position actions.
        """
        total_trades = sum(
            len(r.get("new_trades", []))
            for r in cycle_results.values()
            if isinstance(r, dict)
        )
        total_actions = sum(
            len(r.get("position_actions", []))
            for r in cycle_results.values()
            if isinstance(r, dict)
        )

        if total_trades == 0 and total_actions == 0:
            return  # Don't spam on quiet cycles

        title = f"🔄 Cycle Complete — {total_trades} trades, {total_actions} actions"
        lines = []
        for name, result in cycle_results.items():
            if not isinstance(result, dict):
                continue
            trades = len(result.get("new_trades", []))
            actions = len(result.get("position_actions", []))
            if trades or actions:
                lines.append(f"• **{name}**: {trades} trades, {actions} actions")

        embed = self._build_embed(
            title=title,
            description="\n".join(lines) if lines else "No activity",
            color=0x0EA5E9,  # sky blue
        )
        await self._send(embed)

    # ── Internal Helpers ──────────────────────────────────────────

    def _build_embed(
        self,
        title: str,
        description: str,
        color: int = 0x6366F1,
        fields: Optional[list[dict]] = None,
    ) -> dict:
        """Build a Discord embed payload."""
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Premium Trader"},
        }
        if fields:
            embed["fields"] = fields
        return embed

    async def _send(self, embed: dict):
        """POST an embed to the Discord webhook. Fire-and-forget."""
        if not self._enabled:
            logger.debug(f"[Notifier] (no webhook) {embed.get('title', '?')}")
            return

        payload = {
            "username": "Premium Trader",
            "embeds": [embed],
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._webhook_url, json=payload)
                if resp.status_code not in (200, 204):
                    logger.warning(
                        f"[Notifier] Discord returned {resp.status_code}: {resp.text[:200]}"
                    )
        except httpx.TimeoutException:
            logger.warning("[Notifier] Discord webhook timed out")
        except Exception as e:
            logger.warning(f"[Notifier] Discord webhook failed: {e}")
