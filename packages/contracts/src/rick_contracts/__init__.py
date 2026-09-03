"""Canonical platform contracts (dependency-light, no legacy imports)."""

from rick_contracts.chat import ChatRequest, ChatResponse, ChatStreamEvent
from rick_contracts.errors import ERROR_CODES
from rick_contracts.pagination import Page

__all__ = ["ChatRequest", "ChatResponse", "ChatStreamEvent", "ERROR_CODES", "Page"]
