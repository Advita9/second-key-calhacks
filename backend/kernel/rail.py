"""Transfer rail boundary. The kernel calls `submit` only inside a verified release."""

from __future__ import annotations

import secrets
from typing import Protocol

from kernel.models import Certificate, Payment


class RailError(Exception):
    """The rail refused or failed. Release is rolled back; nothing is consumed."""


class TransferRail(Protocol):
    def submit(self, payment: Payment, certificate: Certificate) -> str:
        """Submit the transfer and return the rail's transfer id. May raise."""
        ...


class NullTransferRail:
    """MOCK rail: returns a fake transfer id and moves no money."""

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        return f"mock_tr_{secrets.token_hex(6)}"
