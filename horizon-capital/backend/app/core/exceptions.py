"""Application exceptions."""


class HorizonError(Exception):
    """Base exception for Horizon Capital."""

    def __init__(self, message: str, code: str = "UNKNOWN"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(HorizonError):
    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTH_FAILED")


class AuthorizationError(HorizonError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, code="FORBIDDEN")


class NotFoundError(HorizonError):
    def __init__(self, resource: str, identifier: str):
        super().__init__(f"{resource} '{identifier}' not found", code="NOT_FOUND")


class RiskLimitBreached(HorizonError):  # noqa: N818
    def __init__(self, limit_name: str, value: float, threshold: float):
        super().__init__(
            f"Risk limit '{limit_name}' breached: {value:.4f} > {threshold:.4f}",
            code="RISK_BREACH",
        )


class KillSwitchActive(HorizonError):  # noqa: N818
    def __init__(self):
        super().__init__("Kill switch is active — all trading halted", code="KILL_SWITCH")


class BrokerError(HorizonError):
    def __init__(self, broker: str, message: str):
        super().__init__(f"Broker '{broker}' error: {message}", code="BROKER_ERROR")


class DataFeedError(HorizonError):
    def __init__(self, feed: str, message: str):
        super().__init__(f"Data feed '{feed}' error: {message}", code="FEED_ERROR")


class AgentError(HorizonError):
    def __init__(self, agent_id: str, message: str):
        super().__init__(f"Agent '{agent_id}' error: {message}", code="AGENT_ERROR")
