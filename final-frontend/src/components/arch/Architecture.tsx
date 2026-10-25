"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Margaret, type Mood } from "@/components/margaret/Margaret";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  FULL_CORE,
  FULL_EDGES,
  FULL_NODES,
  FULL_SERVICE,
  SCENARIOS,
  SIMPLE_CORE,
  SIMPLE_EDGES,
  SIMPLE_NODES,
  SIMPLE_VIEWBOX,
  VIEW,
  type ArchEdge,
  type ArchNode,
  type Scenario,
} from "./model";

type Side = "r" | "l" | "t" | "b";
type Pt = { x: number; y: number };

function anchor(n: ArchNode, side: Side): Pt {
  if (side === "r") return { x: n.x + n.w, y: n.y + n.h / 2 };
  if (side === "l") return { x: n.x, y: n.y + n.h / 2 };
  if (side === "t") return { x: n.x + n.w / 2, y: n.y };
  return { x: n.x + n.w / 2, y: n.y + n.h };
}
const NORMAL: Record<Side, Pt> = { r: { x: 1, y: 0 }, l: { x: -1, y: 0 }, t: { x: 0, y: -1 }, b: { x: 0, y: 1 } };

function geometry(a: ArchNode, b: ArchNode, e: ArchEdge) {
  const out: Side = e.out ?? (b.x >= a.x + a.w ? "r" : b.y > a.y ? "b" : "t");
  const inn: Side = e.in ?? (out === "r" ? "l" : out === "b" ? "t" : out === "t" ? "b" : "r");
  const p0 = anchor(a, out);
  const p3 = anchor(b, inn);
  const dist = Math.hypot(p3.x - p0.x, p3.y - p0.y);
  const k = out === inn ? (out === "l" ? Math.min(46, Math.min(a.x, b.x) - 6) : 46) : Math.max(18, dist * 0.42);
  const p1 = { x: p0.x + NORMAL[out].x * k, y: p0.y + NORMAL[out].y * k };
  const p2 = { x: p3.x + NORMAL[inn].x * k, y: p3.y + NORMAL[inn].y * k };
  const d = `M${p0.x},${p0.y} C${p1.x},${p1.y} ${p2.x},${p2.y} ${p3.x},${p3.y}`;
  const mid = { x: (p0.x + 3 * p1.x + 3 * p2.x + p3.x) / 8, y: (p0.y + 3 * p1.y + 3 * p2.y + p3.y) / 8 };
  return { d, mid };
}

const STEP_MS = 1150;

export function Architecture({ compact = false }: { compact?: boolean }) {
  const [view, setView] = useState<"simple" | "full">("simple");
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [idx, setIdx] = useState(-1);
  const [selected, setSelected] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const nodes = view === "simple" ? SIMPLE_NODES : FULL_NODES;
  const edges = view === "simple" ? SIMPLE_EDGES : FULL_EDGES;
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const stepOf = useMemo(() => new Map(FULL_NODES.map((n) => [n.id, n.step])), []);

  // The scenario path in this view's node ids (simple view collapses runs of the same step).
  const path = useMemo(() => {
    if (!scenario) return [] as string[];
    const ids = scenario.steps.map((s) => (view === "simple" ? (stepOf.get(s.node) ?? s.node) : s.node));
    return ids;
  }, [scenario, view, stepOf]);

  const playing = scenario !== null && idx < scenario.steps.length - 1;
  const done = scenario !== null && idx >= scenario.steps.length - 1;

  useEffect(() => {
    if (!scenario || idx >= scenario.steps.length - 1) return;
    timer.current = setTimeout(() => setIdx((i) => i + 1), idx < 0 ? 200 : STEP_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [scenario, idx]);

  const visited = new Set(path.slice(0, idx + 1));
  const current = idx >= 0 ? path[idx] : null;
  const activeEdges = new Set<string>();
  for (let i = 1; i <= idx; i++) {
    const a = path[i - 1];
    const b = path[i];
    if (a && b && a !== b) {
      activeEdges.add(`${a}>${b}`);
      activeEdges.add(`${b}>${a}`);
    }
  }

  const play = (s: Scenario) => {
    setSelected(null);
    setScenario(s);
    setIdx(-1);
  };
  const reset = () => {
    setScenario(null);
    setIdx(-1);
  };

  const step = scenario && idx >= 0 ? scenario.steps[idx] : null;
  const mood: Mood = step?.mood ?? "calm";
  const detail = selected ? byId.get(selected) : current ? byId.get(current) : null;
  const dim = scenario !== null;

  const core = view === "simple" ? SIMPLE_CORE : FULL_CORE;

  return (
    <div className="flex flex-col gap-5" data-testid="architecture">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-xl border border-line bg-stone p-1" role="tablist" aria-label="Diagram detail">
          {(["simple", "full"] as const).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={view === v}
              onClick={() => {
                setView(v);
                setSelected(null);
              }}
              className={cn("rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors", view === v ? "bg-paper text-ink shadow-[0_1px_2px_rgba(27,23,22,0.08)]" : "text-muted hover:text-ink")}
              data-testid={`arch-view-${v}`}
            >
              {v === "simple" ? "Five steps" : "Full system"}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2" aria-label="Play a scenario">
          <span className="mr-1 text-sm text-muted">Play a scenario</span>
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              onClick={() => play(s)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors",
                scenario?.id === s.id ? "border-crimson bg-crimson text-white" : s.kind === "attack" ? "border-rose-2 bg-rose/50 text-crimson hover:border-crimson" : "border-line-2 bg-paper text-ink-2 hover:border-ink/40",
              )}
              data-testid={`scenario-${s.id}`}
            >
              {s.label}
            </button>
          ))}
          {scenario ? (
            <Button variant="ghost" size="sm" onClick={reset}>
              Clear
            </Button>
          ) : null}
        </div>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-line bg-paper">
        <svg viewBox={view === "simple" ? SIMPLE_VIEWBOX : `0 0 ${VIEW.w} ${VIEW.h}`} className={cn("block w-full min-w-[880px]", compact ? "max-h-[520px]" : "")} role="img" aria-label="Second Key architecture">
          <defs>
            <linearGradient id="vaultFill" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#5a070b" />
              <stop offset="1" stopColor="#3c0306" />
            </linearGradient>
            <pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="1" fill="#e2ddd6" />
            </pattern>
            {(["muted", "crimson", "light", "white"] as const).map((k) => (
              <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L10,5 L0,10 z" fill={k === "muted" ? "#b3aaa0" : k === "crimson" ? "#790005" : k === "light" ? "rgba(246,233,232,0.55)" : "#ffffff"} />
              </marker>
            ))}
          </defs>

          <rect width={VIEW.w} height={VIEW.h} fill="url(#dots)" />

          {view === "full" ? (
            <g>
              <rect x={FULL_SERVICE.x} y={FULL_SERVICE.y} width={FULL_SERVICE.w} height={FULL_SERVICE.h} rx="20" fill="#faf9f7" stroke="#d3ccc3" strokeDasharray="5 5" />
              <text x={FULL_SERVICE.x + 22} y={FULL_SERVICE.y + 26} fontSize="13" fontWeight="600" fill="#3b3431">
                Kernel service
              </text>
              <text x={FULL_SERVICE.x + 22} y={FULL_SERVICE.y + 44} fontSize="11.5" fill="#6f6661">
                Python, FastAPI, SQLite
              </text>
              <text x={FULL_SERVICE.x + 22} y={FULL_SERVICE.y + 456} fontSize="11.5" fill="#6f6661">
                <tspan x={FULL_SERVICE.x + 22}>Models live here.</tspan>
                <tspan x={FULL_SERVICE.x + 22} dy="16">They propose and report.</tspan>
                <tspan x={FULL_SERVICE.x + 22} dy="16">They cannot release money.</tspan>
              </text>
            </g>
          ) : null}

          <rect x={core.x} y={core.y} width={core.w} height={core.h} rx="22" fill="url(#vaultFill)" />
          <text x={core.x + 22} y={core.y + 28} fontSize="13" fontWeight="600" fill="#f6e9e8">
            {view === "simple" ? "The kernel: rules, not models" : "Authority core"}
          </text>
          <text x={core.x + 22} y={core.y + 46} fontSize="11.5" fill="#d2a9a6">
            {view === "simple" ? "Nothing said on a call can change what happens in here." : "Rules, certificates, audit. No model."}
          </text>

          {edges.map((e) => {
            const a = byId.get(e.from);
            const b = byId.get(e.to);
            if (!a || !b) return null;
            const { d, mid } = geometry(a, b, e);
            const inCore = a.zone === "core" && b.zone === "core";
            const active = activeEdges.has(`${e.from}>${e.to}`);
            const stroke = active ? (inCore ? "#ffffff" : "#790005") : inCore ? "rgba(246,233,232,0.45)" : "#b3aaa0";
            const marker = active ? (inCore ? "white" : "crimson") : inCore ? "light" : "muted";
            return (
              <g key={`${e.from}-${e.to}`} style={{ opacity: dim && !active ? 0.35 : 1, transition: "opacity 300ms" }}>
                <path d={d} fill="none" stroke={stroke} strokeWidth={active ? 2.5 : 1.5} strokeDasharray={e.dashed && !active ? "4 5" : undefined} className={active ? "flow" : undefined} markerEnd={`url(#arrow-${marker})`} />
                {e.label && view === "full" ? (
                  <g>
                    <rect x={mid.x - e.label.length * 3.2 - 6} y={mid.y - 9} width={e.label.length * 6.4 + 12} height="18" rx="9" fill={inCore ? "#4a0508" : "#ffffff"} stroke={inCore ? "none" : "#e2ddd6"} />
                    <text x={mid.x} y={mid.y + 4} textAnchor="middle" fontSize="10.5" fill={inCore ? "#f6e9e8" : "#6f6661"} fontFamily="var(--font-mono)">
                      {e.label}
                    </text>
                  </g>
                ) : null}
                {e.label && view === "simple" ? (
                  <text x={mid.x} y={mid.y - 10} textAnchor="middle" fontSize="12" fill={inCore ? "#f6e9e8" : "#6f6661"}>
                    {e.label}
                  </text>
                ) : null}
              </g>
            );
          })}

          {nodes.map((n, i) => (
            <NodeBox
              key={n.id}
              n={n}
              index={view === "simple" ? i + 1 : null}
              big={view === "simple"}
              active={current === n.id}
              visited={visited.has(n.id)}
              dim={dim && !visited.has(n.id)}
              selected={selected === n.id}
              onClick={() => setSelected((s) => (s === n.id ? null : n.id))}
            />
          ))}
        </svg>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <div className="flex min-h-[200px] items-stretch gap-4 rounded-2xl border border-line bg-stone p-5" aria-live="polite">
          <Margaret mood={done && scenario?.outcome.tone === "allow" ? "happy" : mood} className="w-32 shrink-0 self-end sm:w-36" />
          <div className="flex min-w-0 flex-1 flex-col">
            {scenario ? (
              <>
                <p className="text-sm text-muted">{scenario.pitch}</p>
                <AnimatePresence mode="wait">
                  <motion.p key={`${scenario.id}-${idx}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25 }} className="mt-3 text-lg leading-snug text-ink">
                    {step?.say ?? "Starting…"}
                  </motion.p>
                </AnimatePresence>
                <div className="mt-auto pt-4">
                  {done ? (
                    <div className="refuse-in">
                      <p className={cn("code text-xl font-semibold", scenario.outcome.tone === "allow" ? "text-allow" : scenario.outcome.tone === "hold" ? "text-hold" : "text-crimson")} data-testid="scenario-outcome">
                        {scenario.outcome.text}
                      </p>
                      <p className="mt-1 text-sm leading-snug text-ink-2">{scenario.outcome.note}</p>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5" aria-hidden>
                      {scenario.steps.map((_, i) => (
                        <span key={i} className={cn("h-1.5 flex-1 rounded-full transition-colors", i <= idx ? "bg-crimson" : "bg-line")} />
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <p className="text-lg font-semibold tracking-tight">Pick a scenario to watch a payment move through the system.</p>
                <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
                  Margaret is a Claude persona and she is meant to be fooled. The white boxes can be talked to. The crimson boxes cannot: they only follow rules, and money moves only when a human reviewer and a one-time certificate agree.
                </p>
              </>
            )}
            {playing ? null : scenario ? (
              <Button variant="secondary" size="sm" className="mt-4 self-start" onClick={() => play(scenario)}>
                Replay
              </Button>
            ) : null}
          </div>
        </div>

        <div className="rounded-2xl border border-line bg-paper p-5" data-testid="arch-detail">
          {detail ? (
            <div>
              <div className="flex items-center gap-2">
                <span className={cn("size-2.5 rounded-full", detail.zone === "core" ? "bg-crimson" : detail.zone === "ai" ? "bg-ink-2" : "border border-line-2 bg-paper")} />
                <p className="text-sm text-muted">{detail.zone === "core" ? "Kernel authority core" : detail.zone === "ai" ? "Model, no release capability" : "Outside the kernel"}</p>
              </div>
              <h3 className="mt-2 text-xl font-semibold tracking-tight">{detail.label}</h3>
              {detail.what ? <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{detail.what}</p> : null}
              {detail.cannot ? (
                <p className="mt-3 rounded-xl bg-rose px-3.5 py-2.5 text-[14px] leading-snug text-vault">
                  <span className="font-semibold">Cannot: </span>
                  {detail.cannot}
                </p>
              ) : null}
              {detail.tech ? <p className="mt-3 text-[13px] text-muted">{detail.tech}</p> : null}
            </div>
          ) : (
            <div>
              <h3 className="text-xl font-semibold tracking-tight">Click any box</h3>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-2">Each one explains what it does and, more importantly, what it is not allowed to do.</p>
              <ul className="mt-4 space-y-2.5 text-[14px]">
                <li className="flex items-center gap-3">
                  <span className="h-4 w-6 rounded-md border border-line-2 bg-paper" />
                  People and voice: can be persuaded
                </li>
                <li className="flex items-center gap-3">
                  <span className="h-4 w-6 rounded-md border border-line-2 bg-stone" />
                  Models: propose and report, never release
                </li>
                <li className="flex items-center gap-3">
                  <span className="h-4 w-6 rounded-md vault" />
                  Kernel: deterministic rules, certificates, audit
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NodeBox({ n, index, big, active, visited, dim, selected, onClick }: { n: ArchNode; index: number | null; big: boolean; active: boolean; visited: boolean; dim: boolean; selected: boolean; onClick: () => void }) {
  const core = n.zone === "core";
  const toneStroke = n.tone === "hold" ? "#e3a64a" : n.tone === "allow" ? "#4fb784" : n.tone === "refuse" ? "#ff8f8a" : null;
  const fill = core ? (active ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.06)") : n.zone === "ai" ? "#f4f2ef" : "#ffffff";
  const stroke = active || selected ? (core ? "#ffffff" : "#790005") : core ? (toneStroke ?? "rgba(246,233,232,0.32)") : visited ? "#790005" : "#d3ccc3";
  const title = core ? "#ffffff" : "#1b1716";
  const sub = core ? "#d9b5b2" : "#6f6661";
  const tx = n.x + (big ? 22 : 14);
  const lineH = big ? 19 : 14;
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={n.label}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      style={{ cursor: "pointer", opacity: dim ? 0.4 : 1, transition: "opacity 300ms" }}
      data-testid={`node-${n.id}`}
    >
      {active ? <rect x={n.x - 5} y={n.y - 5} width={n.w + 10} height={n.h + 10} rx="18" fill="none" stroke={core ? "rgba(255,255,255,0.35)" : "rgba(121,0,5,0.25)"} strokeWidth="6" /> : null}
      <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={big ? 18 : 12} fill={fill} stroke={stroke} strokeWidth={active || selected ? 2.5 : 1.25} style={{ transition: "fill 300ms, stroke 300ms" }} />
      {n.tone && !big ? <rect x={n.x} y={n.y + 10} width="3" height={n.h - 20} rx="1.5" fill={toneStroke ?? "transparent"} /> : null}
      {index ? (
        <g>
          <circle cx={n.x + 34} cy={n.y + 36} r="14" fill={core ? "rgba(255,255,255,0.14)" : "#790005"} />
          <text x={n.x + 34} y={n.y + 41} textAnchor="middle" fontSize="14" fontWeight="600" fill="#ffffff">
            {index}
          </text>
        </g>
      ) : null}
      <text x={tx} y={n.y + (big ? 86 : 26)} fontSize={big ? 21 : n.label.length > 16 ? 12.5 : 14} fontWeight="600" fill={title} fontFamily={n.tone ? "var(--font-mono)" : undefined} letterSpacing={big ? "-0.02em" : undefined}>
        {n.label}
      </text>
      <text fontSize={big ? 14 : 11.5} fill={sub}>
        {n.sub.map((s, i) => (
          <tspan key={i} x={tx} y={n.y + (big ? 114 : 43) + i * lineH}>
            {s}
          </tspan>
        ))}
      </text>
    </g>
  );
}
