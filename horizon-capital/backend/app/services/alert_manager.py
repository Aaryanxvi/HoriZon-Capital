"""Alert & Notification Manager.

Rule-based alert system that monitors portfolio events and dispatches
notifications via multiple channels (console, Telegram, email).

Subscribes to the message bus and evaluates alert rules against incoming
messages. Supports configurable thresholds and notification routing.

Research references
-------------------
- Jorion 2006, "Value at Risk" Ch. 15 — risk limit monitoring and breach
  escalation protocols.
- Hull 2018, "Risk Management and Financial Institutions" — operational
  risk monitoring frameworks and alert hierarchies.
"""

from __future__ import annotations

import asyncio
import smtplib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.config import settings
from app.core.logging import get_logger
from app.core.messaging import AgentMessage, MessageType

logger = get_logger("services.alert_manager")


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertChannel(StrEnum):
    CONSOLE = "CONSOLE"
    TELEGRAM = "TELEGRAM"
    EMAIL = "EMAIL"


@dataclass
class Alert:
    """A triggered alert."""

    alert_id: str
    rule_name: str
    severity: AlertSeverity
    title: str
    message: str
    timestamp: str = ""
    channels_notified: list[str] = field(default_factory=list)
    acknowledged: bool = False
    payload: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class AlertRule:
    """Configurable alert rule."""

    name: str
    description: str
    severity: AlertSeverity
    channels: list[AlertChannel]
    enabled: bool = True
    cooldown_seconds: int = 300  # don't re-fire within cooldown
    last_triggered: datetime | None = None


# Default alert rules
DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        name="drawdown_warning",
        description="Portfolio drawdown exceeds warning threshold",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.CONSOLE],
        cooldown_seconds=600,
    ),
    AlertRule(
        name="drawdown_critical",
        description="Portfolio drawdown exceeds critical threshold",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.CONSOLE, AlertChannel.TELEGRAM],
        cooldown_seconds=300,
    ),
    AlertRule(
        name="kill_switch_activated",
        description="Kill switch has been activated",
        severity=AlertSeverity.EMERGENCY,
        channels=[AlertChannel.CONSOLE, AlertChannel.TELEGRAM, AlertChannel.EMAIL],
        cooldown_seconds=0,
    ),
    AlertRule(
        name="var_breach",
        description="VaR limit breached",
        severity=AlertSeverity.CRITICAL,
        channels=[AlertChannel.CONSOLE, AlertChannel.TELEGRAM],
        cooldown_seconds=600,
    ),
    AlertRule(
        name="regime_change",
        description="Market regime changed",
        severity=AlertSeverity.INFO,
        channels=[AlertChannel.CONSOLE],
        cooldown_seconds=300,
    ),
    AlertRule(
        name="agent_crash",
        description="An agent has crashed and is being restarted",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.CONSOLE],
        cooldown_seconds=120,
    ),
    AlertRule(
        name="alpha_decay",
        description="Strategy alpha has decayed below threshold",
        severity=AlertSeverity.WARNING,
        channels=[AlertChannel.CONSOLE, AlertChannel.TELEGRAM],
        cooldown_seconds=3600,
    ),
    AlertRule(
        name="large_trade",
        description="A large trade has been executed",
        severity=AlertSeverity.INFO,
        channels=[AlertChannel.CONSOLE],
        cooldown_seconds=60,
    ),
    AlertRule(
        name="debate_rejection",
        description="Multi-agent debate rejected a trade proposal",
        severity=AlertSeverity.INFO,
        channels=[AlertChannel.CONSOLE],
        cooldown_seconds=60,
    ),
]


class AlertManager:
    """Central alert management service.

    Subscribes to message bus events and triggers alerts based on
    configurable rules. Dispatches to multiple notification channels.

    Ref: Hull 2018 — tiered alert escalation with acknowledgement.
    """

    def __init__(self, bus=None) -> None:
        if bus is None:
            from app.core.runtime import get_bus
            bus = get_bus()
        self.bus = bus
        self._rules: dict[str, AlertRule] = {r.name: r for r in DEFAULT_RULES}
        self._history: list[Alert] = []
        self._max_history = 500
        self._running = False
        self._alert_counter = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Subscribe to bus events for alert monitoring."""
        self._running = True
        await self.bus.subscribe("horizon.risk.alert", self._on_risk_alert)
        await self.bus.subscribe("horizon.risk.kill_switch", self._on_kill_switch)
        await self.bus.subscribe("horizon.regime.update", self._on_regime_change)
        await self.bus.subscribe("horizon.system.health", self._on_health)
        await self.bus.subscribe("horizon.alpha.decay", self._on_alpha_decay)
        await self.bus.subscribe("horizon.debate.conclusion", self._on_debate)
        await self.bus.subscribe("horizon.trade.executed", self._on_trade)
        logger.info("alert_manager.started", rules=len(self._rules))

    async def stop(self) -> None:
        self._running = False
        logger.info("alert_manager.stopped")

    # ------------------------------------------------------------------
    # Bus event handlers
    # ------------------------------------------------------------------

    async def _on_risk_alert(self, msg: AgentMessage) -> None:
        """Handle risk alerts (VaR breach, drawdown)."""
        payload = msg.payload
        alert_type = payload.get("alert_type", "")

        if alert_type == "DRAWDOWN_WARNING" or payload.get("current_drawdown", 0) > 5.0:
            await self._trigger_rule(
                "drawdown_warning",
                title="Drawdown Warning",
                message=f"Current drawdown: {payload.get('current_drawdown', 0):.2f}%",
                payload=payload,
            )

        dd_limit = settings.risk_max_drawdown_pct * 0.8
        if (
            alert_type == "DRAWDOWN_CRITICAL"
            or payload.get("current_drawdown", 0) > dd_limit
        ):
            await self._trigger_rule(
                "drawdown_critical",
                title="CRITICAL: Drawdown Approaching Limit",
                message=(
                    f"Drawdown {payload.get('current_drawdown', 0):.2f}% approaching "
                    f"limit of {settings.risk_max_drawdown_pct}%"
                ),
                payload=payload,
            )

        if alert_type == "VAR_BREACH":
            await self._trigger_rule(
                "var_breach",
                title="VaR Limit Breached",
                message=(
                    f"VaR {payload.get('var_95', 0):.4f} "
                    f"exceeds limit {settings.risk_var_limit_pct}%"
                ),
                payload=payload,
            )

    async def _on_kill_switch(self, msg: AgentMessage) -> None:
        if msg.payload.get("active"):
            await self._trigger_rule(
                "kill_switch_activated",
                title="KILL SWITCH ACTIVATED",
                message=f"Reason: {msg.payload.get('reason', 'Unknown')}. All trading halted.",
                payload=msg.payload,
            )

    async def _on_regime_change(self, msg: AgentMessage) -> None:
        scope = msg.payload.get("market_scope", "")
        regime = msg.payload.get("regime", "")
        await self._trigger_rule(
            "regime_change",
            title=f"Regime Change: {scope}",
            message=(
                f"{scope} regime changed to {regime} "
                f"(conf={msg.payload.get('confidence', 0):.1%})"
            ),
            payload=msg.payload,
        )

    async def _on_health(self, msg: AgentMessage) -> None:
        status = msg.payload.get("status", "")
        if status in ("CRASHED", "DEAD"):
            await self._trigger_rule(
                "agent_crash",
                title=f"Agent Crashed: {msg.payload.get('agent_id', '')}",
                message=f"Agent {msg.payload.get('agent_id', '')} status={status}",
                payload=msg.payload,
            )

    async def _on_alpha_decay(self, msg: AgentMessage) -> None:
        await self._trigger_rule(
            "alpha_decay",
            title=f"Alpha Decay: {msg.payload.get('strategy', '')}",
            message=(
                f"Strategy {msg.payload.get('strategy', '')} "
                f"rolling Sharpe dropped to {msg.payload.get('rolling_sharpe', 0):.2f}"
            ),
            payload=msg.payload,
        )

    async def _on_debate(self, msg: AgentMessage) -> None:
        decision = msg.payload.get("final_decision", "")
        if decision in ("REJECT", "HOLD"):
            await self._trigger_rule(
                "debate_rejection",
                title=f"Debate Rejected: {msg.payload.get('symbol', '')}",
                message=(
                    f"Trade proposal for {msg.payload.get('symbol', '')} "
                    f"rejected by debate (consensus={msg.payload.get('consensus_score', 0):.2f})"
                ),
                payload=msg.payload,
            )

    async def _on_trade(self, msg: AgentMessage) -> None:
        qty = msg.payload.get("quantity", 0)
        price = msg.payload.get("price", 0)
        notional = abs(qty * price)
        if notional > 50000:  # large trade threshold
            await self._trigger_rule(
                "large_trade",
                title=f"Large Trade: {msg.payload.get('symbol', '')}",
                message=(
                    f"{msg.payload.get('side', '')} {qty} "
                    f"{msg.payload.get('symbol', '')} @ {price:.2f} "
                    f"(${notional:,.0f})"
                ),
                payload=msg.payload,
            )

    # ------------------------------------------------------------------
    # Alert triggering
    # ------------------------------------------------------------------

    async def _trigger_rule(
        self,
        rule_name: str,
        title: str,
        message: str,
        payload: dict | None = None,
    ) -> Alert | None:
        """Trigger an alert rule if enabled and not in cooldown."""
        rule = self._rules.get(rule_name)
        if not rule or not rule.enabled:
            return None

        # Check cooldown
        now = datetime.now(UTC)
        if rule.last_triggered and rule.cooldown_seconds > 0:
            elapsed = (now - rule.last_triggered).total_seconds()
            if elapsed < rule.cooldown_seconds:
                return None

        rule.last_triggered = now
        self._alert_counter += 1

        alert = Alert(
            alert_id=f"alert-{self._alert_counter:06d}",
            rule_name=rule_name,
            severity=rule.severity,
            title=title,
            message=message,
            payload=payload or {},
        )

        # Dispatch to channels
        for channel in rule.channels:
            try:
                await self._dispatch(channel, alert)
                alert.channels_notified.append(channel.value)
            except Exception as exc:
                logger.warning(
                    "alert_dispatch_failed",
                    channel=channel.value,
                    error=str(exc),
                )

        # Store in history
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        logger.info(
            "alert_triggered",
            alert_id=alert.alert_id,
            rule=rule_name,
            severity=rule.severity.value,
            title=title,
        )

        return alert

    async def _dispatch(self, channel: AlertChannel, alert: Alert) -> None:
        """Send alert to a specific channel."""
        if channel == AlertChannel.CONSOLE:
            await self._dispatch_console(alert)
        elif channel == AlertChannel.TELEGRAM:
            await self._dispatch_telegram(alert)
        elif channel == AlertChannel.EMAIL:
            await self._dispatch_email(alert)

    async def _dispatch_console(self, alert: Alert) -> None:
        """Print alert to console via bus broadcast."""
        severity_colors = {
            AlertSeverity.INFO: "cyan",
            AlertSeverity.WARNING: "yellow",
            AlertSeverity.CRITICAL: "red",
            AlertSeverity.EMERGENCY: "bold red",
        }
        color = severity_colors.get(alert.severity, "white")
        # Publish to bus so TUI can pick it up
        await self.bus.publish(
            AgentMessage(
                sender_id="alert-manager",
                channel="horizon.alerts.console",
                message_type=MessageType.SYSTEM,
                payload={
                    "alert_id": alert.alert_id,
                    "severity": alert.severity.value,
                    "title": alert.title,
                    "message": alert.message,
                    "color": color,
                },
            )
        )

    async def _dispatch_telegram(self, alert: Alert) -> None:
        """Send alert via Telegram bot API."""
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return

        severity_emoji = {
            AlertSeverity.INFO: "ℹ️",
            AlertSeverity.WARNING: "⚠️",
            AlertSeverity.CRITICAL: "🚨",
            AlertSeverity.EMERGENCY: "🆘",
        }
        emoji = severity_emoji.get(alert.severity, "📢")
        text = f"{emoji} *{alert.title}*\n{alert.message}"

        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                    timeout=10,
                )
        except ImportError:
            logger.debug("httpx_not_installed_for_telegram")
        except Exception as exc:
            logger.warning("telegram_send_failed", error=str(exc))

    async def _dispatch_email(self, alert: Alert) -> None:
        """Send alert via email (SMTP)."""
        if not settings.alert_email_smtp_host or not settings.alert_email_to:
            return

        try:
            from email.mime.text import MIMEText

            body = (
                f"{alert.title}\n\n{alert.message}\n\n"
                f"Severity: {alert.severity.value}"
            )
            msg = MIMEText(body)
            msg["Subject"] = (
                f"[Horizon Capital] {alert.severity.value}: "
                f"{alert.title}"
            )
            msg["From"] = settings.alert_email_from
            msg["To"] = settings.alert_email_to

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: self._send_email_sync(msg),
            )
        except Exception as exc:
            logger.warning("email_send_failed", error=str(exc))

    @staticmethod
    def _send_email_sync(msg) -> None:  # noqa: ANN001
        """Synchronous email send."""
        with smtplib.SMTP(
            settings.alert_email_smtp_host,
            settings.alert_email_smtp_port,
        ) as server:
            server.starttls()
            if settings.alert_email_password:
                server.login(settings.alert_email_from, settings.alert_email_password)
            server.sendmail(msg["From"], [msg["To"]], msg.as_string())

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_recent_alerts(self, limit: int = 20, severity: str | None = None) -> list[dict]:
        """Return recent alerts as dicts."""
        filtered = self._history
        if severity:
            filtered = [a for a in filtered if a.severity.value == severity.upper()]
        return [
            {
                "alert_id": a.alert_id,
                "rule_name": a.rule_name,
                "severity": a.severity.value,
                "title": a.title,
                "message": a.message,
                "timestamp": a.timestamp,
                "acknowledged": a.acknowledged,
            }
            for a in filtered[-limit:]
        ]

    def get_rules(self) -> list[dict]:
        """Return all alert rules and their status."""
        return [
            {
                "name": r.name,
                "description": r.description,
                "severity": r.severity.value,
                "enabled": r.enabled,
                "channels": [c.value for c in r.channels],
                "cooldown_seconds": r.cooldown_seconds,
            }
            for r in self._rules.values()
        ]

    def toggle_rule(self, rule_name: str) -> bool | None:
        """Toggle a rule on/off. Returns new enabled state or None if not found."""
        rule = self._rules.get(rule_name)
        if not rule:
            return None
        rule.enabled = not rule.enabled
        logger.info("alert_rule_toggled", rule=rule_name, enabled=rule.enabled)
        return rule.enabled

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for a in self._history:
            if a.alert_id == alert_id:
                a.acknowledged = True
                return True
        return False
