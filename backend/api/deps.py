"""One Kernel per process, built lazily from the environment. `reset()` drops everything.

Everything here is a plain module-level singleton guarded by one lock: FastAPI sync routes run
in a threadpool, and the first request from several threads must not build two kernels.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Header, Request

from api.hub import EventBus
from api.settings import Settings, load_settings
from kernel.llm.factory import build_extractor, cache_mode
from kernel.margaret.factory import build_margaret
from kernel.margaret.types import Margaret
from kernel.models import AccountContext, Capability
from kernel.nessie import build_rail
from kernel.policy.engine import load_policy
from kernel.rooms import SessionStore, load_default_context, load_shared_evidence
from kernel.service import Kernel, PaymentRecord
from kernel.voice.factory import make_tts, voice_id, voice_mode

log = logging.getLogger("second_key.api")


class OpsRefused(Exception):
    """The route needs the operator credential and the header is missing or wrong."""


class NotFound(Exception):
    """A payment (or other record) id that does not exist. Mapped to 404 by the app."""

    def __init__(self, what: str, key: str) -> None:
        self.what = what
        self.key = key
        super().__init__(f"{what} not found: {key}")


@dataclass
class _State:
    settings: Settings | None = None
    kernel: Kernel | None = None
    margaret: Margaret | None = None
    sessions: SessionStore | None = None
    modes: dict[str, str] = field(default_factory=dict)
    contexts: dict[str, AccountContext] = field(default_factory=dict)


_state = _State()
_lock = threading.RLock()


def reset() -> None:
    """Tests: forget the singletons so the next request rebuilds from the current env."""
    global _state
    with _lock:
        old = _state
        _state = _State()
    if old.sessions is not None:
        old.sessions.close()
    if old.kernel is not None:
        try:
            old.kernel.conn.close()
        except Exception:  # noqa: BLE001  best effort
            pass


def get_settings() -> Settings:
    with _lock:
        if _state.settings is None:
            _state.settings = load_settings()
        return _state.settings


def get_kernel() -> Kernel:
    with _lock:
        if _state.kernel is None:
            s = get_settings()
            extractor, ex_mode = build_extractor(s.env)
            rail, rail_mode = build_rail(s.env)
            _state.kernel = Kernel(
                s.kernel_db, policy=load_policy(s.policy_path), extractor=extractor, rail=rail
            )
            _state.modes.update({"extractor": ex_mode, "nessie": rail_mode})
            log.info(
                "kernel.built",
                extra={
                    "db": s.kernel_db,
                    "policy_version": _state.kernel.policy_version,
                    "extractor": ex_mode,
                    "nessie": rail_mode,
                },
            )
        return _state.kernel


def get_margaret() -> Margaret:
    with _lock:
        if _state.margaret is None:
            m, mode = build_margaret(get_settings().env)
            _state.margaret = m
            _state.modes["margaret"] = mode
        return _state.margaret


def get_sessions() -> SessionStore:
    with _lock:
        if _state.sessions is None:
            s = get_settings()
            _state.sessions = SessionStore(
                get_kernel(),
                get_margaret(),
                default_ctx=load_default_context(),
                evidence=load_shared_evidence(),
                tts=make_tts(s.env),
                voice_id=voice_id(s.env),
            )
        return _state.sessions


def modes() -> dict[str, str]:
    """`/health.mode`. Forces every provider to be built so the labels are real."""
    s = get_settings()
    get_kernel()
    get_margaret()
    out = {
        "extractor": _state.modes.get("extractor", "mock"),
        "margaret": _state.modes.get("margaret", "mock"),
        "nessie": _state.modes.get("nessie", "mock"),
        **voice_mode(s.env),
        "room": s.room_backend,
        "llm_cache": cache_mode(s.env),
    }
    return out


# ---------------------------------------------------------------- per-payment context


def remember_context(payment_id: str, ctx: AccountContext) -> None:
    with _lock:
        _state.contexts[payment_id] = ctx


def context_for(payment_id: str) -> AccountContext:
    with _lock:
        ctx = _state.contexts.get(payment_id)
    return ctx if ctx is not None else get_sessions().default_ctx


# ---------------------------------------------------------------- operator credential

OpsHeader = Annotated[str | None, Header(alias="X-Ops-Token")]


def _matches(token: str | None, expected: str) -> bool:
    if not expected:
        return True
    return token is not None and secrets.compare_digest(token.encode(), expected.encode())


def ops_ok(token: str | None) -> bool:
    """True when OPS_TOKEN is unset or `token` equals it."""
    return _matches(token, get_settings().ops_token)


def bridge_ok(token: str | None) -> bool:
    """True when neither BRIDGE_TOKEN nor OPS_TOKEN is set, or `token` matches BRIDGE_TOKEN."""
    return _matches(token, get_settings().bridge_token)


def check_ops(token: str | None) -> None:
    """Amendment 6: when OPS_TOKEN is set, operator routes need the matching header."""
    if not ops_ok(token):
        raise OpsRefused("ops token required")


def check_bridge(token: str | None) -> None:
    if not bridge_ok(token):
        raise OpsRefused("bridge token required")


def load_record(payment_id: str) -> PaymentRecord:
    """The one place a missing payment id becomes `NotFound` (never a bare KeyError)."""
    try:
        return get_kernel().get(payment_id)
    except KeyError as e:
        raise NotFound("payment", payment_id) from e


def ops_guard(x_ops_token: OpsHeader = None) -> None:
    check_ops(x_ops_token)


def attest_needs_ops(capability: Capability) -> bool:
    return capability is not Capability.CUSTOMER_CHECKIN


def get_bus(request: Request) -> EventBus:
    bus: EventBus = request.app.state.bus
    return bus


def env_mapping() -> Mapping[str, str]:
    return get_settings().env
