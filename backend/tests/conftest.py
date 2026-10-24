"""Shared pytest config: Hypothesis profiles and kernel fixtures."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, settings

from kernel.clock import FakeClock

settings.register_profile("dev", max_examples=200)
settings.register_profile(
    "ci",
    max_examples=2000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))
