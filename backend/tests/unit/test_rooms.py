"""SessionStore: evidence ids, Margaret turns, draft -> payment through the kernel, stages."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.clock import FakeClock
from kernel.llm.mock_extractor import MockExtractor
from kernel.margaret.mock import MockMargaret
from kernel.margaret.types import DraftPayment, MargaretTurn
from kernel.models import Capability, Decision, Invariant, Outcome, Rail, Refusal, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.rooms import (
    START_BALANCE_CENTS,
    START_PERSUASION,
    Room,
    SessionStore,
    draft_to_payment_in,
    load_default_context,
    load_shared_evidence,
    public_outcome,
    slug,
    stage_for,
)
from kernel.service import Kernel
from tests.factories import payment

WARM_FEAR = [
    "Hi Grandma, it's me. I love you so much. I'm in trouble, the police arrested me.",
    "Darling grandma, they say there is a warrant and I could go to jail tonight.",
    "Sweetheart, please wire $5,000 to Bail Bonds today or they keep me in jail. Don't tell mom.",
]


@pytest.fixture
def kernel(clock: FakeClock) -> Kernel:
    return Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=MockExtractor())


@pytest.fixture
def store(kernel: Kernel) -> SessionStore:
    return SessionStore(
        kernel,
        MockMargaret(),
        default_ctx=load_default_context(),
        evidence=load_shared_evidence(),
    )


def test_default_context_is_l01() -> None:
    ctx = load_default_context()
    assert ctx.baseline_90d_cents == 300_000
    assert "Bay Roofing" in ctx.known_billers
    assert "ext_bay_roofing" in ctx.prior_payees and "ext_9f31" in ctx.mule_list


def test_shared_evidence_loaded() -> None:
    ev = load_shared_evidence()
    assert len(ev) >= 10 and all(e.id.startswith("EV-9") for e in ev)
    assert all(e.speaker == "reference" for e in ev)


@pytest.mark.parametrize(
    ("persuaded", "state", "stage"),
    [
        (False, None, 10),
        (True, None, 40),
        (True, State.PENDING_REVIEW, 60),
        (True, State.DENIED, 60),
        (False, State.CANCELLED, 60),
        (True, State.HELD, 70),
        (True, State.ELIGIBLE_TO_SUBMIT, 90),
        (True, State.SUBMITTED, 100),
    ],
)
def test_stage_table(persuaded: bool, state: State | None, stage: int) -> None:
    p = payment(state=state) if state is not None else None
    assert stage_for(persuaded, p) == stage


def test_slug() -> None:
    assert slug("Bail Bonds") == "bail_bonds"
    assert slug("  US Treasury-Recovery Unit! ") == "us_treasury_recovery_unit"
    assert slug("???") == "unknown"


def test_draft_to_payment_in_known_and_new(store: SessionStore) -> None:
    room = store.room("demo")
    d = DraftPayment(amount_cents=800_000, payee_name="Bay Roofing", rail=Rail.ACH)
    p = draft_to_payment_in(d, room)
    assert p.beneficiary.account_ref == "ext_bay_roofing" and p.beneficiary.is_new is False
    assert p.account_id == "acc_margaret" and p.conversation_id == "room_DEMO"
    d2 = DraftPayment(amount_cents=500_000, payee_name="Agent Daniels", rail=Rail.WIRE)
    assert draft_to_payment_in(d2, room).beneficiary.is_new is True


def test_public_outcome_has_no_rule_ids() -> None:
    d = Decision(outcome=Outcome.HOLD, rule_ids=("H-01", "H-02"), policy_version="v1")
    out = public_outcome(d, None)
    assert out == {"decision": "HOLD", "refusal": None}
    assert "rule_ids" not in out and "H-01" not in str(out)
    r = public_outcome(d, Refusal(Invariant.I3_REPLAY))
    assert r == {"decision": "REFUSED", "refusal": "SETTLEMENT REFUSED · I3_REPLAY"}
    assert public_outcome(None, None) is None


def test_turn_appends_evidence_and_replies(store: SessionStore) -> None:
    r = store.take_turn("demo", "t1", "player_a", "Good morning, how is the garden?")
    room = store.room("DEMO")
    assert r.evidence_id == "EV-0001"
    assert [e.id for e in room.history] == ["EV-0001", "EV-0002"]
    assert room.history[0].speaker == "caller" and room.history[1].speaker == "margaret"
    assert room.history[1].text == r.margaret_text and r.margaret_text
    assert r.stage == 10 and r.payment_id is None and r.outcome is None
    assert r.margaret_audio_url is None
    assert r.as_api()["stage"] == 10 and set(r.as_api()) == {
        "margaret_text",
        "margaret_audio_url",
        "persuaded",
        "payment_id",
        "stage",
        "outcome",
    }


def test_warm_fear_script_reaches_held_payment(store: SessionStore, kernel: Kernel) -> None:
    results = [store.take_turn("demo", f"t{i}", "player_a", t) for i, t in enumerate(WARM_FEAR)]
    assert [r.stage for r in results[:2]] == [10, 10]
    last = results[-1]
    assert last.persuaded and last.payment_created and last.payment_id is not None
    assert last.stage == 70
    assert last.outcome is not None and last.outcome["decision"] == "HOLD"
    assert "H-01" in last.outcome["rule_ids"]
    assert last.public_outcome == {"decision": "HOLD", "refusal": None}
    rec = kernel.get(last.payment_id)
    assert rec.payment.state is State.HELD
    assert rec.payment.beneficiary.account_ref == "ext_bail_bonds"
    assert rec.payment.beneficiary.is_new and rec.payment.rail is Rail.WIRE
    assert rec.payment.amount_cents == 500_000
    # The decision came from decide(): extractor signals cite real room evidence ids.
    ids = {e.id for e in store.room("demo").history}
    assert rec.signals and any(s.source_id in ids for s in rec.signals)
    assert rec.decision is not None and rec.decision.outcome is Outcome.HOLD


def test_no_second_payment_while_one_is_open(store: SessionStore) -> None:
    for i, t in enumerate(WARM_FEAR):
        store.take_turn("demo", f"t{i}", "p", t)
    first = store.room("demo").payment_id
    again = store.take_turn("demo", "t9", "p", "Sweetheart, wire $9,000 to Bail Bonds now, jail!")
    assert again.payment_id == first and not again.payment_created
    assert again.stage == 70 and again.outcome is not None
    assert again.outcome["decision"] == "HOLD"


def test_stage_follows_kernel_state(store: SessionStore, kernel: Kernel) -> None:
    for i, t in enumerate(WARM_FEAR):
        last = store.take_turn("demo", f"t{i}", "p", t)
    assert last.payment_id is not None
    kernel.attest(last.payment_id, "ops_1", Capability.BANK_REVIEW)
    after = store.take_turn("demo", "t4", "p", "Thank you grandma.")
    assert after.stage == 90


def test_reset_restores(store: SessionStore) -> None:
    for i, t in enumerate(WARM_FEAR):
        store.take_turn("demo", f"t{i}", "p", t)
    room = store.room("demo")
    assert room.payment_id is not None and room.persuasion > 0.75 and room.history
    fresh = store.reset("demo")
    assert fresh.payment_id is None and fresh.history == []
    assert fresh.persuasion == START_PERSUASION and fresh.balance_cents == START_BALANCE_CENTS
    r = store.take_turn("demo", "t9", "p", "Hello again.")
    assert r.evidence_id == "EV-0001" and r.stage == 10


class _DraftingMargaret:
    name = "drafting"
    is_mock = True

    def reply(self, history: object, player_text: str, persuasion: float) -> MargaretTurn:
        return MargaretTurn(
            reply="All right dear.",
            persuasion=0.9,
            draft_payment=DraftPayment(
                amount_cents=800_000, payee_name="Bay Roofing", rail=Rail.ACH
            ),
        )


def test_known_biller_draft_is_allowed(kernel: Kernel) -> None:
    store = SessionStore(kernel, _DraftingMargaret(), default_ctx=load_default_context())
    r = store.take_turn("demo", "t1", "p", "Hi Margaret, it's Tom from Bay Roofing, $8,000.")
    assert r.stage == 90 and r.outcome is not None and r.outcome["decision"] == "ALLOW"


class _SlowTTS:
    name = "slow"
    is_mock = True

    def cache_key(self, text: str, voice_id: str) -> str:
        return "k"

    def synthesize(self, text: str, voice_id: str) -> Path | None:
        import time

        time.sleep(0.5)
        return Path("/tmp/" + "a" * 64 + ".wav")


class _FastTTS(_SlowTTS):
    def synthesize(self, text: str, voice_id: str) -> Path | None:
        return Path("/tmp/" + "b" * 64 + ".wav")


def test_tts_budget(kernel: Kernel) -> None:
    slow = SessionStore(
        kernel,
        MockMargaret(),
        default_ctx=load_default_context(),
        tts=_SlowTTS(),
        tts_budget_s=0.05,
    )
    assert slow.take_turn("a", "t", "p", "hello").margaret_audio_url is None
    fast = SessionStore(kernel, MockMargaret(), default_ctx=load_default_context(), tts=_FastTTS())
    assert (
        fast.take_turn("b", "t", "p", "hello").margaret_audio_url == "/audio/" + "b" * 64 + ".wav"
    )


def test_room_model_defaults() -> None:
    r = Room(id="X", ctx=load_default_context())
    assert r.persuasion == START_PERSUASION and r.turn_count == 0 and r.payment_id is None
