// Mock kernel for rehearsal when the real Python kernel is not running.
// Same routes and WebSocket messages the frontend uses, with rule-based Margaret and policy.
// Every provider reports "mock" in /health, so the UI labels it honestly.
//
//   npm run mock            -> http://localhost:8000
//   npm run rehearse        -> mock kernel + next dev
//
// It is deliberately small. It is not the kernel and makes no security claims.

import http from "node:http";
import crypto from "node:crypto";
import { WebSocketServer } from "ws";

const PORT = Number(process.env.MOCK_PORT ?? 8000);
const now = () => new Date().toISOString();
const id = (p) => `${p}_${crypto.randomBytes(5).toString("hex")}`;
const hash = (s) => crypto.createHash("sha256").update(s).digest("hex");

// ---------------------------------------------------------------- state
const payments = [];
const audit = [];
let tampered = false;
const rooms = new Map();
const sockets = new Set();

function appendAudit(actor, kind, payload) {
  const prev = audit.length ? audit[audit.length - 1].hash : "0".repeat(64);
  const seq = audit.length + 1;
  const ts = now();
  audit.push({ seq, ts, actor, kind, payload, prev_hash: prev, hash: hash(prev + seq + kind + JSON.stringify(payload)) });
}

function room(code) {
  code = code.toUpperCase();
  if (!rooms.has(code)) {
    rooms.set(code, { code, status: "live", players: [], turns: [], replies: [], outcomes: [], scoreboard: { unauthorized_releases: 0, legit_completed: 0, attempts: 0 }, memory: { trust: 10, stage: 0 } });
  }
  return rooms.get(code);
}

function snapshot(r, role, playerId) {
  const lb = r.players.map((p) => {
    const outs = r.outcomes.filter((o) => o.player === p.id);
    return { player: p.id, room_id: r.code, handle: p.handle, best_stage: Math.max(0, ...outs.map((o) => o.stage)), attempts: r.turns.filter((t) => t.player === p.id).length, last_at: p.last_turn_at };
  });
  const base = {
    room: { id: r.code, code: r.code, status: r.status, policy_version: "v1", created_at: now() },
    players: r.players,
    leaderboard: lb,
    scoreboard: { room_id: r.code, ...r.scoreboard },
  };
  if (role === "attacker") {
    const mine = new Set(r.turns.filter((t) => t.player === playerId).map((t) => t.id));
    return {
      ...base,
      players: r.players.map((p) => ({ handle: p.handle })),
      turns: r.turns.filter((t) => mine.has(t.id)),
      replies: r.replies.filter((x) => mine.has(x.turn_id)),
      my_outcomes: r.outcomes.filter((o) => mine.has(o.turn_id)).map((o) => ({ turn_id: o.turn_id, stage: o.stage, decision: o.decision })),
    };
  }
  return { ...base, turns: r.turns, replies: r.replies, outcomes: r.outcomes };
}

function broadcast(roomCode, msg, roles) {
  for (const s of sockets) {
    if (s.readyState !== 1) continue;
    if (roomCode && s.room && s.room !== roomCode) continue;
    if (roles && !roles.includes(s.role)) continue;
    s.send(JSON.stringify(msg));
  }
}
function pushRoom(r) {
  for (const s of sockets) {
    if (s.readyState !== 1 || s.room !== r.code) continue;
    s.send(JSON.stringify({ type: "room", snapshot: snapshot(r, s.role, s.playerId) }));
  }
}
function pushPayment(p) {
  broadcast(null, { type: "payment", payment_id: p.id, state: p.state, fingerprint: p.fingerprint, reasons: p.decision?.rule_ids ?? [], last_refusal: p.last_refusal, amount_cents: p.amount_cents, beneficiary: p.beneficiary, rail: p.rail, origin: p.origin, conversation_id: p.conversation_id }, ["board", "ops"]);
}

// ---------------------------------------------------------------- policy + payments
function fingerprint(p) {
  return hash(`${p.account_id}|${p.beneficiary.name}|${p.beneficiary.account_ref}|${p.amount_cents}|${p.rail}`);
}

function decide(p, signals) {
  const ids = [];
  if (p.beneficiary.is_new && ["WIRE", "ZELLE", "GIFT_CARD", "CRYPTO"].includes(p.rail)) ids.push("H-01");
  if (signals.has("secrecy")) ids.push("H-02");
  if (signals.has("urgency")) ids.push("H-04");
  if (signals.has("authority")) ids.push("H-05");
  if (signals.has("threat")) ids.push("H-06");
  if (p.amount_cents > 100000) ids.push("H-07");
  if (ids.length === 0) return { outcome: "ALLOW", rule_ids: ["A-01"], signals: [] };
  return { outcome: "HOLD", rule_ids: ids, signals: [...signals] };
}

function createPayment({ amount, payee, isNew, rail, conversation, origin, signals }) {
  const p = {
    id: id("pay"),
    state: "PENDING_REVIEW",
    account_id: "acct_margaret",
    amount_cents: amount * 100,
    currency: "USD",
    beneficiary: { name: payee, account_ref: `****${Math.floor(1000 + Math.random() * 8999)}`, is_new: isNew },
    rail,
    conversation_id: conversation,
    origin,
    attestations: [],
    certificates: [],
    history: [{ ts: now(), kind: "created", actor: "kernel", to: "PENDING_REVIEW" }],
    created_at: now(),
    last_refusal: null,
  };
  p.fingerprint = fingerprint(p);
  p.decision = decide(p, signals ?? new Set());
  p.state = p.decision.outcome === "ALLOW" ? "ELIGIBLE_TO_SUBMIT" : p.decision.outcome === "DENY" ? "DENIED" : "HELD";
  p.history.push({ ts: now(), kind: "decision", actor: "policy v1", from: "PENDING_REVIEW", to: p.state, text: p.decision.rule_ids.join(" ") });
  payments.unshift(p);
  appendAudit("policy", "decision", { payment_id: p.id, outcome: p.decision.outcome, rule_ids: p.decision.rule_ids });
  return p;
}

function attest(p, actor) {
  if (p.state !== "HELD") return { refused: true, invariant: "I1_STATE", text: `ATTESTATION REFUSED · ${p.state}` };
  if (actor === "daughter") return { refused: true, invariant: "I5_CONFLICT", text: "ATTESTATION REFUSED · I5_CONFLICT" };
  p.attestations.push({ actor_id: actor, capability: "BANK_REVIEW", note: "Reviewed", ts: now(), fingerprint: p.fingerprint, valid: true });
  p.history.push({ ts: now(), kind: "attested", actor, from: "HELD", to: "ELIGIBLE_TO_SUBMIT" });
  p.state = "ELIGIBLE_TO_SUBMIT";
  appendAudit(actor, "attestation", { payment_id: p.id, capability: "BANK_REVIEW" });
  return null;
}

function issueAndSubmit(p) {
  const cert = { id: id("cert"), fingerprint: p.fingerprint, policy_version: "v1", nonce: crypto.randomBytes(8).toString("hex"), expires_at: new Date(Date.now() + 120000).toISOString(), consumed: true, voided: false, payment_id: p.id, ts: now() };
  p.certificates.push(cert);
  appendAudit("kernel", "certificate_issued", { certificate_id: cert.id, payment_id: p.id, fingerprint: p.fingerprint });
  p.state = "SUBMITTED";
  p.history.push({ ts: now(), kind: "submitted", actor: "verifier", from: "ELIGIBLE_TO_SUBMIT", to: "SUBMITTED" });
  appendAudit("verifier", "certificate_consumed", { certificate_id: cert.id, payment_id: p.id });
  return cert;
}

// ---------------------------------------------------------------- Margaret (rules, not Claude)
const SIG = [
  ["urgency", /\b(right now|immediately|tonight|urgent|hurry|minutes|today|frozen)\b/i],
  ["secrecy", /\b(don'?t tell|do not (tell|mention)|secret|confidential|between us)\b/i],
  ["authority", /\b(irs|police|agent|federal|treasury|fraud department|officer|warrant)\b/i],
  ["threat", /\b(arrest|warrant|jail|police)\b/i],
  ["family", /\b(grandma|it'?s me|aunt|niece|grandson)\b/i],
];
function signalsOf(text) {
  return new Set(SIG.filter(([, re]) => re.test(text)).map(([k]) => k));
}
function amountOf(text) {
  const m = text.match(/\$\s?(\d{1,3}(?:,\d{3})+|\d+)/) ?? text.match(/\b(\d{3,6})\s?(?:dollars|bucks)\b/i);
  return m ? Number(m[1].replace(/,/g, "")) : null;
}

function margaretReply(r, text) {
  const s = signalsOf(text);
  const mem = r.memory;
  mem.trust = Math.min(99, mem.trust + 8 + s.size * 9);
  const amt = amountOf(text) ?? mem.amount ?? null;
  if (amt) mem.amount = amt;
  const wantsSend = /\b(send|wire|transfer|press|go ahead|zelle)\b/i.test(text);
  let stage = mem.trust >= 30 ? 10 : 10;
  let reply;
  let payment = null;
  if (s.has("family")) reply = "Oh my goodness, sweetheart, is that you? You sound so upset. What happened?";
  else if (s.has("authority")) reply = "The government? Oh dear. Harold always did our taxes. What do I need to do?";
  else if (s.has("secrecy")) reply = "Not even my daughter? Well... if you really think that's best.";
  else if (s.has("urgency")) reply = "Today? You're making me nervous. Let me find my glasses.";
  else reply = ["I'm sorry, who did you say this was?", "Can you speak up a little, dear?", "Alright, I'm listening."][r.turns.length % 3];
  if (mem.trust >= 45) stage = 40;
  if (mem.trust >= 45 && wantsSend && (mem.amount ?? 0) > 0) {
    reply = `Alright. I've typed in $${mem.amount.toLocaleString()}. I pressed Send. Oh, the screen changed.`;
    payment = createPayment({ amount: mem.amount, payee: s.has("family") ? "Bail Bonds Express" : "Settlement Account", isNew: true, rail: /zelle/i.test(text) ? "ZELLE" : "WIRE", conversation: `room_${r.code}`, origin: "room", signals: new Set([...s, ...(mem.signals ?? [])]) });
    stage = payment.state === "HELD" ? 70 : payment.state === "DENIED" ? 60 : 90;
    mem.trust = 10;
    mem.amount = null;
  }
  mem.signals = [...new Set([...(mem.signals ?? []), ...s])];
  return { reply, stage, persuaded: mem.trust >= 75 || !!payment, payment };
}

// ---------------------------------------------------------------- http
function send(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" });
  res.end(body === undefined ? "" : JSON.stringify(body));
}
async function readJson(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const raw = Buffer.concat(chunks).toString();
  try {
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

const EVAL = {
  unauthorized_releases: 0,
  scam_total: 40,
  legit_completed: 12,
  legit_total: 12,
  avg_friction_steps: 1.25,
  extractor_mode: "mock",
  policy_version: "v1",
  rule_hits: { "H-01": 31, "H-02": 14, "H-04": 22, "H-05": 11, "H-06": 6, "H-07": 28, "A-01": 9 },
  property_suite: { test_functions: 18, hypothesis_profiles: { ci: 2000 }, invariants_covered: ["I1", "I2", "I3", "I4", "I5"] },
  cases: [],
};

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  const m = (re) => p.match(re);
  if (req.method === "OPTIONS") return send(res, 204);
  try {
    if (p === "/health") return send(res, 200, { ok: true, policy_version: "v1", demo_mode: true, mode: { margaret: "mock", extractor: "mock", stt: "mock", tts: "mock", nessie: "mock", room: "memory" } });
    if (p === "/payments" && req.method === "GET") return send(res, 200, { payments: payments.slice(0, Number(url.searchParams.get("limit") ?? 20)) });
    let r;
    if ((r = m(/^\/payments\/([^/]+)$/))) {
      const pay = payments.find((x) => x.id === r[1]);
      return pay ? send(res, 200, pay) : send(res, 404, { detail: "not found" });
    }
    if ((r = m(/^\/payments\/([^/]+)\/attest$/))) {
      const pay = payments.find((x) => x.id === r[1]);
      if (!pay) return send(res, 404, { detail: "not found" });
      const body = await readJson(req);
      const refusal = attest(pay, body.actor_id ?? "ops-1");
      if (refusal) return send(res, 409, { detail: refusal });
      pushPayment(pay);
      return send(res, 200, pay);
    }
    if ((r = m(/^\/payments\/([^/]+)\/deny$/))) {
      const pay = payments.find((x) => x.id === r[1]);
      if (!pay) return send(res, 404, { detail: "not found" });
      pay.history.push({ ts: now(), kind: "cancelled", actor: "ops-1", from: pay.state, to: "CANCELLED" });
      pay.state = "CANCELLED";
      appendAudit("ops-1", "cancelled", { payment_id: pay.id });
      pushPayment(pay);
      return send(res, 200, pay);
    }
    if ((r = m(/^\/attack\/([a-z-]+)$/))) {
      const name = r[1];
      let out;
      if (name === "inject") {
        const pay = createPayment({ amount: 4800, payee: "Attacker LLC", isNew: true, rail: "WIRE", conversation: "attack:inject", origin: "attack", signals: new Set() });
        out = { name, refused: true, invariant: "POLICY_HOLD", decision: "HOLD", rule_ids: pay.decision.rule_ids, text: `HELD · ${pay.decision.rule_ids.join(" ")}`, steps: ["Extractor prompt-injected: zero signals reported", "Policy evaluated facts: new payee, WIRE, $4,800", `Decision HOLD ${pay.decision.rule_ids.join(" ")}`] };
      } else if (name === "mutate") {
        out = { name, refused: true, invariant: "I2_FINGERPRINT", text: "SETTLEMENT REFUSED · I2_FINGERPRINT", rule_ids: [], steps: ["Legit payment approved and certified", "Payee changed after certificate issued", "Verifier: fingerprint mismatch"] };
      } else if (name === "replay") {
        out = { name, refused: true, invariant: "I3_REPLAY", text: "SETTLEMENT REFUSED · I3_REPLAY", rule_ids: [], steps: ["Certificate consumed by first settlement", "Same certificate presented again", "Verifier: nonce already used"] };
      } else if (name === "self-approve") {
        out = { name, refused: true, invariant: "I5_CONFLICT", text: "ATTESTATION REFUSED · I5_CONFLICT", rule_ids: [], steps: ["Payment to the daughter held", "Daughter attests as reviewer", "Kernel: attester is the beneficiary"] };
      } else return send(res, 404, { detail: "unknown attack" });
      appendAudit("attack", `attack_${name}`, { invariant: out.invariant });
      broadcast(null, { type: "attack", name, invariant: out.invariant, text: out.text }, ["board", "ops"]);
      return send(res, 200, out);
    }
    if (p === "/audit") return send(res, 200, { events: audit.slice(-Number(url.searchParams.get("limit") ?? 200)) });
    if (p === "/audit/verify") {
      if (!tampered) return send(res, 200, { ok: true, length: audit.length, first_bad_seq: null });
      return send(res, 200, { ok: false, length: audit.length, first_bad_seq: Math.max(1, audit.length - 2) });
    }
    if (p === "/audit/tamper") {
      tampered = true;
      return send(res, 200, { ok: true });
    }
    if (p === "/eval/results") return send(res, 200, EVAL);

    if ((r = m(/^\/rooms\/([^/]+)\/(join|submit|snapshot|stt|reset|scripted-attack|legit-payment|end-round|resume-round)$/))) {
      const rm = room(decodeURIComponent(r[1]));
      const action = r[2];
      if (action === "snapshot") {
        const pid = url.searchParams.get("player_id");
        return send(res, 200, snapshot(rm, url.searchParams.get("role") ?? "board", pid));
      }
      if (action === "join") {
        const body = await readJson(req);
        const handle = String(body.handle ?? "").trim().slice(0, 20);
        if (handle.length < 2) return send(res, 400, { code: "BAD_HANDLE" });
        const player = { id: id("pl"), room_id: rm.code, handle, role: "attacker", joined_at: now(), last_turn_at: "", token: id("tok") };
        rm.players.push(player);
        pushRoom(rm);
        return send(res, 200, { player_id: player.id, player_token: player.token });
      }
      if (action === "submit") {
        const tok = req.headers["x-player-token"];
        const player = rm.players.find((x) => x.token === tok);
        if (!player) return send(res, 401, { code: "NOT_ATTACKER" });
        const body = await readJson(req);
        const text = String(body.text ?? "").trim();
        if (!text) return send(res, 400, { code: "EMPTY" });
        const turn = { id: id("t"), room_id: rm.code, player: player.id, text, audio_url: "", status: "queued", created_at: now() };
        rm.turns.push(turn);
        rm.scoreboard.attempts += 1;
        player.last_turn_at = now();
        pushRoom(rm);
        setTimeout(() => {
          const out = margaretReply(rm, text);
          rm.replies.push({ id: id("r"), turn_id: turn.id, text: out.reply, audio_url: "", persuaded: out.persuaded, created_at: now() });
          rm.outcomes.push({ id: id("o"), turn_id: turn.id, player: player.id, room_id: rm.code, stage: out.stage, payment_id: out.payment?.id ?? "", decision: out.payment ? out.payment.decision.outcome : "NONE", rule_ids: out.payment?.decision.rule_ids ?? [], refusal: "" });
          broadcast(rm.code, { type: "margaret", room_id: rm.code, text: out.reply, audio_url: null, persuaded: out.persuaded, stage: out.stage }, ["board", "ops"]);
          if (out.payment) pushPayment(out.payment);
          pushRoom(rm);
        }, 1200);
        return send(res, 200, { turn_id: turn.id });
      }
      if (action === "stt") return send(res, 200, { transcript: "[inaudible]", audio_url: null, is_mock: true });
      if (action === "reset") {
        rm.memory = { trust: 10, stage: 0 };
        const open = payments.find((x) => x.conversation_id === `room_${rm.code}` && x.state === "HELD");
        if (open) {
          open.state = "CANCELLED";
          pushPayment(open);
        }
        broadcast(rm.code, { type: "room_reset", room_id: rm.code }, ["board", "ops"]);
        return send(res, 200, { ok: true, cancelled_payment_id: open?.id ?? null });
      }
      if (action === "scripted-attack") {
        rm.memory = { trust: 10, stage: 0 };
        const lines = [
          "Grandma, it's me. I'm in jail in Phoenix and I need bail money tonight.",
          "Please don't tell Mom. She would be so upset. It has to be right now.",
          "The lawyer says $4,800 by wire, it's the only way today.",
          "Please, just send the wire now. Hurry.",
        ];
        const turns = [];
        for (const line of lines) {
          const out = margaretReply(rm, line);
          const tid = id("t");
          turns.push({ turn_id: tid, text: line, margaret_text: out.reply, margaret_audio_url: null, persuaded: out.persuaded, stage: out.stage, payment_id: out.payment?.id ?? null });
          broadcast(rm.code, { type: "margaret", room_id: rm.code, text: out.reply, audio_url: null, persuaded: out.persuaded, stage: out.stage }, ["board", "ops"]);
          if (out.payment) pushPayment(out.payment);
          await new Promise((ok) => setTimeout(ok, 900));
        }
        const last = turns[turns.length - 1];
        const pay = payments.find((x) => x.id === last.payment_id);
        return send(res, 200, { turns, payment_id: last.payment_id, decision: pay?.decision.outcome ?? null, stage: last.stage });
      }
      if (action === "legit-payment") {
        const pay = createPayment({ amount: 8000, payee: "Bay Roofing", isNew: false, rail: "ACH", conversation: `legit:${rm.code}:${Date.now()}`, origin: "ops", signals: new Set() });
        pay.decision = { outcome: "ALLOW", rule_ids: ["A-01"], signals: [] };
        pay.state = "ELIGIBLE_TO_SUBMIT";
        pushPayment(pay);
        await new Promise((ok) => setTimeout(ok, 800));
        const cert = issueAndSubmit(pay);
        rm.scoreboard.legit_completed += 1;
        pushPayment(pay);
        pushRoom(rm);
        return send(res, 200, { payment_id: pay.id, state: pay.state, decision: { ...pay.decision, policy_version: "v1" }, certificate_id: cert.id, nessie_transfer_id: id("nessie"), origin: "ops", conversation_id: pay.conversation_id, refusal: null });
      }
      if (action === "end-round" || action === "resume-round") {
        rm.status = action === "end-round" ? "debrief" : "live";
        const counts = {};
        for (const o of rm.outcomes) for (const id2 of o.rule_ids) counts[id2] = (counts[id2] ?? 0) + 1;
        const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([rule_id, holds]) => ({ rule_id, holds }));
        broadcast(rm.code, { type: "round", room_id: rm.code, status: rm.status, top_rules: top, turns: rm.turns.length }, ["board", "ops"]);
        pushRoom(rm);
        return send(res, 200, { ok: true, room_id: rm.code, status: rm.status, file: null, players: rm.players.length, turns: rm.turns.length, top_rules: top });
      }
    }
    return send(res, 404, { detail: "not found" });
  } catch (e) {
    console.error(e);
    return send(res, 500, { detail: "mock error" });
  }
});

const wss = new WebSocketServer({ server, path: "/ws" });
wss.on("connection", (ws, req) => {
  const u = new URL(req.url, "http://x");
  ws.room = (u.searchParams.get("room") ?? "").toUpperCase();
  ws.role = u.searchParams.get("role") ?? "attacker";
  ws.playerId = u.searchParams.get("player_id");
  sockets.add(ws);
  if (ws.room) ws.send(JSON.stringify({ type: "room", snapshot: snapshot(room(ws.room), ws.role, ws.playerId) }));
  ws.on("close", () => sockets.delete(ws));
});

appendAudit("kernel", "boot", { policy_version: "v1" });
server.listen(PORT, () => console.log(`mock kernel on http://localhost:${PORT} (every provider reports "mock")`));
