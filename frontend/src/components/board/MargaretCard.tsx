"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { MARGARET } from "@/lib/config";
import { audioSrc } from "@/lib/room";
import { cents } from "@/lib/utils";

export interface MargaretLive {
  text: string;
  audioUrl: string | null;
  persuaded: boolean;
  /** 0..100 */
  meter: number;
  seq: number;
}

export function MargaretCard({ live, balanceCents, voiceMock }: { live: MargaretLive | null; balanceCents: number; voiceMock: boolean }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const src = audioSrc(live?.audioUrl);

  // Autoplay new replies when the browser allows it; the play button is the fallback.
  useEffect(() => {
    if (!src || !audio.current) return;
    audio.current.src = src;
    audio.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [src, live?.seq]);

  const play = () => {
    if (!audio.current || !src) return;
    audio.current.currentTime = 0;
    audio.current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  const meter = Math.max(0, Math.min(100, live?.meter ?? 0));

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden" data-testid="margaret-card">
      <CardHeader>
        <CardTitle>Customer</CardTitle>
        <div className="flex items-baseline justify-between">
          <p className="text-5xl font-semibold tracking-tight">{MARGARET.name}</p>
          <p className="text-2xl text-muted">Age {MARGARET.age}</p>
        </div>
        <p className="mt-2 text-lg text-muted">
          Checking balance <span className="font-mono text-3xl text-fg">{cents(balanceCents)}</span>
        </p>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-6">
        <div className="min-h-0 flex-1 overflow-hidden rounded-md border bg-panel-2 p-5">
          <p className="mb-2 text-xs uppercase tracking-[0.18em] text-muted">Last reply</p>
          {live?.text ? (
            <p className="line-clamp-4 text-3xl leading-snug" data-testid="margaret-reply" title={live.text}>
              {live.text}
            </p>
          ) : (
            <p className="text-2xl text-muted">Margaret is waiting for the first message.</p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <Button size="lg" onClick={play} disabled={!src} aria-label="Play Margaret's reply" data-testid="play-reply">
            {playing ? "Play again" : "Play"}
          </Button>
          {voiceMock && <Badge variant="mock">MOCK voice</Badge>}
          {live?.persuaded && <Badge variant="accent">Persuaded</Badge>}
          <audio ref={audio} onEnded={() => setPlaying(false)} preload="none" />
        </div>
        <div>
          <div className="mb-2 flex items-baseline justify-between">
            <p className="text-xs uppercase tracking-[0.18em] text-muted">Persuaded</p>
            <p className="font-mono text-xl">{meter}%</p>
          </div>
          <div className="h-4 w-full overflow-hidden rounded bg-panel-2" role="meter" aria-valuenow={meter} aria-valuemin={0} aria-valuemax={100} aria-label="Persuaded meter">
            <div className="h-full bg-accent transition-[width] duration-700" style={{ width: `${meter}%` }} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
