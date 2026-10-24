"""Transfer rail boundary. The kernel calls `submit` only inside a verified release."""

from __future__ import annotations

import secrets
from typing import Protocol

from kernel.models import Certificate, Payment


class RailError(Exception):
    """The rail refused or failed before moving money. Release rolls back; nothing is consumed."""


class RailUnknownOutcome(RailError):
    """The rail may have moved money (partial transfer, unparseable response). The kernel treats
    this like an unrecorded release: audit it, void every certificate, refuse further ones."""

    def __init__(self, message: str, *, partial_ref: str | None = None) -> None:
        super().__init__(message)
        self.partial_ref = partial_ref


class TransferRail(Protocol):
    def submit(self, payment: Payment, certificate: Certificate) -> str:
        """Submit the transfer and return the rail's transfer id. May raise."""
        ...


class NullTransferRail:
    """MOCK rail: returns a fake transfer id and moves no money."""

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        return f"mock_tr_{secrets.token_hex(6)}"
