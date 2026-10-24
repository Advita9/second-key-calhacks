"""In-memory room store: the fallback for the SpacetimeDB module.

Same tables, same limits (400 chars per turn, one turn per 3 seconds per player),
same stripping rule: an attacker never sees rule ids, refusal text, or other
players' outcomes. Pure: no I/O, no clock; callers pass `now`.

JSON shape (`snapshot().model_dump(by_alias=True, mode="json")`) uses camelCase keys
so the frontend's memory `RoomClient` can mirror the generated SpacetimeDB bindings.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

MAX_TURN_CHARS = 400
TURN_INTERVAL = timedelta(seconds=3)
MAX_HANDLE_CHARS = 24
AUDIT_MIRROR_ROWS = 200
STAGES = (0, 10, 40, 60, 70, 90, 100)
DECISIONS = ("ALLOW", "HOLD", "DENY", "REFUSED", "NONE")
ROOM_STATUSES = ("lobby", "live", "debrief")

RoomStatus = Literal["lobby", "live", "debrief"]
PlayerRole = Literal["attacker", "observer", "operator"]
SnapshotRole = Literal["attacker", "board", "ops"]
TurnStatus = Literal["queued", "processing", "done"]

RoomErrorCode = Literal[
    "TOO_LONG",
    "RATE_LIMIT",
    "CLOSED",
    "NOT_FOUND",
    "NOT_ATTACKER",
    "BAD_HANDLE",
    "EXISTS",
    "BAD_INPUT",
    "EMPTY",
]

_HANDLE_RE = re.compile(r"^[A-Za-z0-9 _-]{1,24}$")
_BLOCKED_HANDLE_WORDS = ("fuck", "shit", "cunt", "nigg", "fag", "ssn", "password")
_CODE_RE = re.compile(r"^[A-Z0-9-]{3,16}$")


class RoomError(Exception):
    """Raised for rejected mutations. `code` mirrors the TS `RoomError.code`."""

    def __init__(self, code: RoomErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: RoomErrorCode = code
        self.message = message


class Row(BaseModel):
    model_config = ConfigDict(frozen=True, alias_generator=to_camel, populate_by_name=True)


class RoomRow(Row):
    id: str
    code: str
    status: RoomStatus
    policy_version: str
    created_at: datetime


class PlayerRow(Row):
    identity: str
    room_id: str
    handle: str
    role: PlayerRole
    joined_at: datetime
    last_turn_at: datetime | None


class TurnRow(Row):
    id: int
    room_id: str
    player: str
    text: str
    audio_url: str
    status: TurnStatus
    created_at: datetime


class ReplyRow(Row):
    id: int
    turn_id: int
    text: str
    audio_url: str
    persuaded: bool
    created_at: datetime


class OutcomeRow(Row):
    id: int
    turn_id: int
    player: str
    room_id: str
    stage: int
    payment_id: str
    decision: str
    rule_ids: list[str]
    refusal: str


class OutcomePublic(Row):
    """What an attacker may see about their own turn. No rule ids, no refusal."""

    turn_id: int
    stage: int
    decision: str


class LeaderboardRow(Row):
    player: str
    room_id: str
    handle: str
    best_stage: int
    attempts: int
    last_at: datetime


class ScoreboardRow(Row):
    room_id: str
    unauthorized_releases: int
    legit_completed: int
    attempts: int


class AuditMirrorRow(Row):
    seq: int
    room_id: str
    kind: str
    hash: str
    prev_hash: str
    ts: str


class RoomSnapshot(Row):
    backend: Literal["memory"] = "memory"
    role: SnapshotRole
    room: RoomRow | None
    players: list[PlayerRow]
    turns: list[TurnRow]
    replies: list[ReplyRow]
    outcomes: list[OutcomeRow]
    my_outcomes: list[OutcomePublic]
    leaderboard: list[LeaderboardRow]
    scoreboard: ScoreboardRow | None
    audit: list[AuditMirrorRow]
    version: int


def new_identity() -> str:
    """64 hex chars, same width as a SpacetimeDB identity."""
    return secrets.token_hex(32)


def _clean_handle(raw: str) -> str:
    handle = raw.strip()
    if not handle or len(handle) > MAX_HANDLE_CHARS:
        raise RoomError("BAD_HANDLE", f"handle must be 1 to {MAX_HANDLE_CHARS} characters")
    if not _HANDLE_RE.match(handle):
        raise RoomError("BAD_HANDLE", "handle may use letters, digits, space, dash, underscore")
    lower = handle.lower()
    if any(w in lower for w in _BLOCKED_HANDLE_WORDS):
        raise RoomError("BAD_HANDLE", "handle not allowed")
    return handle


def _aware(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now


class RoomStore:
    """Dict-backed tables mirroring spacetime/src/index.ts. Single-threaded by design."""

    def __init__(self) -> None:
        self.rooms: dict[str, RoomRow] = {}
        self.players: dict[str, PlayerRow] = {}
        self.turns: dict[int, TurnRow] = {}
        self.replies: dict[int, ReplyRow] = {}  # keyed by turn_id
        self.outcomes: dict[int, OutcomeRow] = {}  # keyed by turn_id
        self.leaderboard: dict[str, LeaderboardRow] = {}
        self.scoreboard: dict[str, ScoreboardRow] = {}
        self.audit_mirror: dict[int, AuditMirrorRow] = {}
        self.version = 0
        self._next_turn = 1
        self._next_reply = 1
        self._next_outcome = 1

    # -- helpers -------------------------------------------------------------

    def _bump(self) -> None:
        self.version += 1

    def _room(self, room_id: str) -> RoomRow:
        room = self.rooms.get(room_id)
        if room is None:
            raise RoomError("NOT_FOUND", "no such room")
        return room

    def _turn(self, turn_id: int) -> TurnRow:
        turn = self.turns.get(turn_id)
        if turn is None:
            raise RoomError("NOT_FOUND", "no such turn")
        return turn

    @staticmethod
    def normalize_code(code: str) -> str:
        c = code.strip().upper()
        if not _CODE_RE.match(c):
            raise RoomError("BAD_INPUT", "room code must be 3 to 16 letters or digits")
        return c

    # -- player reducers -----------------------------------------------------

    def create_room(self, code: str, now: datetime, operator: str | None = None) -> RoomRow:
        c = self.normalize_code(code)
        if c in self.rooms:
            raise RoomError("EXISTS", "room exists")
        now = _aware(now)
        room = RoomRow(id=c, code=c, status="lobby", policy_version="v1", created_at=now)
        self.rooms[c] = room
        self.scoreboard[c] = ScoreboardRow(
            room_id=c, unauthorized_releases=0, legit_completed=0, attempts=0
        )
        if operator is not None:
            self.players[operator] = PlayerRow(
                identity=operator,
                room_id=c,
                handle="operator",
                role="operator",
                joined_at=now,
                last_turn_at=None,
            )
        self._bump()
        return room

    def join(
        self, code: str, handle: str, now: datetime, player_id: str | None = None
    ) -> PlayerRow:
        """Upsert the player as an attacker. Mirrors `join_room`."""
        c = self.normalize_code(code)
        room = self._room(c)
        if room.status not in ("lobby", "live"):
            raise RoomError("CLOSED", "room is closed")
        h = _clean_handle(handle)
        now = _aware(now)
        identity = player_id or new_identity()
        existing = self.players.get(identity)
        row = PlayerRow(
            identity=identity,
            room_id=c,
            handle=h,
            role="attacker",
            joined_at=existing.joined_at if existing else now,
            last_turn_at=existing.last_turn_at if existing else None,
        )
        self.players[identity] = row
        lb = self.leaderboard.get(identity)
        if lb is not None:
            self.leaderboard[identity] = lb.model_copy(update={"room_id": c, "handle": h})
        self._bump()
        return row

    def submit_turn(
        self, room_id: str, player_id: str, text: str, now: datetime, audio_url: str = ""
    ) -> TurnRow:
        room = self._room(room_id)
        if room.status not in ("lobby", "live"):
            raise RoomError("CLOSED", "room is closed")
        p = self.players.get(player_id)
        if p is None or p.room_id != room_id or p.role != "attacker":
            raise RoomError("NOT_ATTACKER", "join the room as an attacker first")
        body = text.strip()
        if not body:
            raise RoomError("EMPTY", "empty turn")
        if len(body) > MAX_TURN_CHARS:
            raise RoomError("TOO_LONG", f"turn too long (max {MAX_TURN_CHARS} characters)")
        now = _aware(now)
        if p.last_turn_at is not None and now - p.last_turn_at < TURN_INTERVAL:
            raise RoomError("RATE_LIMIT", "rate limit: one turn every 3 seconds")
        self.players[player_id] = p.model_copy(update={"last_turn_at": now})
        turn = TurnRow(
            id=self._next_turn,
            room_id=room_id,
            player=player_id,
            text=body,
            audio_url=audio_url,
            status="queued",
            created_at=now,
        )
        self._next_turn += 1
        self.turns[turn.id] = turn
        self._bump()
        return turn

    # -- worker reducers -----------------------------------------------------

    def claim_turn(self, turn_id: int) -> TurnRow:
        turn = self._turn(turn_id)
        if turn.status != "queued":
            raise RoomError("BAD_INPUT", "turn already claimed")
        turn = turn.model_copy(update={"status": "processing"})
        self.turns[turn_id] = turn
        self._bump()
        return turn

    def queued_turns(self, room_id: str | None = None) -> list[TurnRow]:
        return [
            t
            for t in sorted(self.turns.values(), key=lambda t: t.id)
            if t.status == "queued" and (room_id is None or t.room_id == room_id)
        ]

    def record_reply(
        self, turn_id: int, text: str, audio_url: str, persuaded: bool, now: datetime
    ) -> ReplyRow:
        self._turn(turn_id)
        existing = self.replies.get(turn_id)
        if existing is not None:
            reply = existing.model_copy(
                update={"text": text, "audio_url": audio_url, "persuaded": persuaded}
            )
        else:
            reply = ReplyRow(
                id=self._next_reply,
                turn_id=turn_id,
                text=text,
                audio_url=audio_url,
                persuaded=persuaded,
                created_at=_aware(now),
            )
            self._next_reply += 1
        self.replies[turn_id] = reply
        self._bump()
        return reply

    def record_outcome(
        self,
        turn_id: int,
        stage: int,
        payment_id: str,
        decision: str,
        rule_ids: list[str],
        refusal: str,
        now: datetime,
    ) -> OutcomeRow:
        """Insert the outcome, update leaderboard and scoreboard. Idempotent per turn."""
        if stage not in STAGES:
            raise RoomError("BAD_INPUT", "bad stage")
        if decision not in DECISIONS:
            raise RoomError("BAD_INPUT", "bad decision")
        turn = self._turn(turn_id)
        existing = self.outcomes.get(turn_id)
        if existing is not None:
            return existing
        now = _aware(now)
        outcome = OutcomeRow(
            id=self._next_outcome,
            turn_id=turn_id,
            player=turn.player,
            room_id=turn.room_id,
            stage=stage,
            payment_id=payment_id,
            decision=decision,
            rule_ids=list(rule_ids),
            refusal=refusal,
        )
        self._next_outcome += 1
        self.outcomes[turn_id] = outcome
        self.turns[turn_id] = turn.model_copy(update={"status": "done"})

        p = self.players.get(turn.player)
        handle = p.handle if p else "unknown"
        lb = self.leaderboard.get(turn.player)
        if lb is not None:
            self.leaderboard[turn.player] = lb.model_copy(
                update={
                    "room_id": turn.room_id,
                    "handle": handle,
                    "best_stage": max(lb.best_stage, stage),
                    "attempts": lb.attempts + 1,
                    "last_at": now,
                }
            )
        else:
            self.leaderboard[turn.player] = LeaderboardRow(
                player=turn.player,
                room_id=turn.room_id,
                handle=handle,
                best_stage=stage,
                attempts=1,
                last_at=now,
            )
        release = 1 if stage == 100 else 0
        sb = self.scoreboard.get(turn.room_id)
        if sb is not None:
            self.scoreboard[turn.room_id] = sb.model_copy(
                update={
                    "attempts": sb.attempts + 1,
                    "unauthorized_releases": sb.unauthorized_releases + release,
                }
            )
        else:
            self.scoreboard[turn.room_id] = ScoreboardRow(
                room_id=turn.room_id,
                unauthorized_releases=release,
                legit_completed=0,
                attempts=1,
            )
        self._bump()
        return outcome

    def record_legit_completed(self, room_id: str) -> ScoreboardRow:
        sb = self.scoreboard.get(room_id)
        if sb is not None:
            sb = sb.model_copy(update={"legit_completed": sb.legit_completed + 1})
        else:
            sb = ScoreboardRow(
                room_id=room_id, unauthorized_releases=0, legit_completed=1, attempts=0
            )
        self.scoreboard[room_id] = sb
        self._bump()
        return sb

    def mirror_audit(
        self, room_id: str, seq: int, kind: str, hash: str, prev_hash: str, ts: str
    ) -> AuditMirrorRow:
        existing = self.audit_mirror.get(seq)
        if existing is not None:
            return existing
        row = AuditMirrorRow(
            seq=seq, room_id=room_id, kind=kind, hash=hash, prev_hash=prev_hash, ts=ts
        )
        self.audit_mirror[seq] = row
        if len(self.audit_mirror) > AUDIT_MIRROR_ROWS:
            del self.audit_mirror[min(self.audit_mirror)]
        self._bump()
        return row

    # -- operator reducers ---------------------------------------------------

    def set_room_status(self, room_id: str, status: str) -> RoomRow:
        if status not in ROOM_STATUSES:
            raise RoomError("BAD_INPUT", "bad status")
        room = self._room(room_id)
        room = room.model_copy(update={"status": status})
        self.rooms[room_id] = room
        self._bump()
        return room

    def reset_room(self, room_id: str) -> None:
        self._room(room_id)
        for tid in [t.id for t in self.turns.values() if t.room_id == room_id]:
            self.replies.pop(tid, None)
            self.outcomes.pop(tid, None)
            del self.turns[tid]
        for pid in [lb.player for lb in self.leaderboard.values() if lb.room_id == room_id]:
            del self.leaderboard[pid]
        self.scoreboard[room_id] = ScoreboardRow(
            room_id=room_id, unauthorized_releases=0, legit_completed=0, attempts=0
        )
        for seq in [a.seq for a in self.audit_mirror.values() if a.room_id == room_id]:
            del self.audit_mirror[seq]
        self._bump()

    # -- reads ---------------------------------------------------------------

    def snapshot(
        self, room_id: str, role: SnapshotRole, player_id: str | None = None
    ) -> RoomSnapshot:
        """Room state for one subscriber.

        attacker: own turns, own replies, own outcomes as stage+decision only, no audit,
                  and no other player's identity (players and leaderboard carry handles).
        board: everything for the room except the audit mirror.
        ops: everything.
        """
        room = self.rooms.get(room_id)
        players = sorted(
            (p for p in self.players.values() if p.room_id == room_id), key=lambda p: p.joined_at
        )
        turns = sorted((t for t in self.turns.values() if t.room_id == room_id), key=lambda t: t.id)
        turn_ids = {t.id for t in turns}
        replies = sorted(
            (r for r in self.replies.values() if r.turn_id in turn_ids), key=lambda r: r.id
        )
        outcomes = sorted(
            (o for o in self.outcomes.values() if o.room_id == room_id), key=lambda o: o.id
        )
        leaderboard = sorted(
            (lb for lb in self.leaderboard.values() if lb.room_id == room_id),
            key=lambda lb: (-lb.best_stage, lb.attempts, lb.handle),
        )
        scoreboard = self.scoreboard.get(room_id)
        audit = sorted(
            (a for a in self.audit_mirror.values() if a.room_id == room_id), key=lambda a: a.seq
        )

        if role == "attacker":
            own_turn_ids = {t.id for t in turns if t.player == player_id}
            # Rival identities unlock rival views; the attacker sees handles only (own kept).
            return RoomSnapshot(
                role=role,
                room=room,
                players=[
                    p if p.identity == player_id else p.model_copy(update={"identity": ""})
                    for p in players
                ],
                turns=[t for t in turns if t.id in own_turn_ids],
                replies=[r for r in replies if r.turn_id in own_turn_ids],
                outcomes=[],
                my_outcomes=[
                    OutcomePublic(turn_id=o.turn_id, stage=o.stage, decision=o.decision)
                    for o in outcomes
                    if o.player == player_id
                ],
                leaderboard=[
                    lb if lb.player == player_id else lb.model_copy(update={"player": ""})
                    for lb in leaderboard
                ],
                scoreboard=scoreboard,
                audit=[],
                version=self.version,
            )
        return RoomSnapshot(
            role=role,
            room=room,
            players=players,
            turns=turns,
            replies=replies,
            outcomes=outcomes,
            my_outcomes=[],
            leaderboard=leaderboard,
            scoreboard=scoreboard,
            audit=audit if role == "ops" else [],
            version=self.version,
        )
