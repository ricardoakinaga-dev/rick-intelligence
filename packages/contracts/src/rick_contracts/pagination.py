"""Stable pagination DTO (cursor preferred for large evolving datasets)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field

from rick_contracts.base import StrictContractModel

T = TypeVar("T")


class Page(StrictContractModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    page: int = 1
    page_size: int = 20
    total: int = 0
    next_cursor: str | None = None
