"""Thin re-export of core messaging primitives for agent-layer convenience."""

from app.core.messaging import AgentBus, AgentMessage, MessageType

__all__ = ["AgentBus", "AgentMessage", "MessageType"]
