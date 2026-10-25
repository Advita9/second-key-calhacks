"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";

export type Mood = "calm" | "happy" | "worried" | "distressed" | "angry";

export const MOOD_LABEL: Record<Mood, string> = {
  calm: "On the line",
  worried: "Under pressure",
  distressed: "Talked into it",
  angry: "Caught the scam",
  happy: "Money safe",
};

/**
 * Margaret's face follows the call. The kernel never looks at her mood; it is there so the room can
 * read the story at a glance.
 *   calm        nothing happening, or a fresh conversation
 *   worried     a caller is pressing her
 *   distressed  she is persuaded and about to send
 *   angry       the bank held, denied or refused the payment: the scam is exposed
 *   happy       a legitimate payment went through
 */
export function moodFor(o: { meter?: number; persuaded?: boolean; state?: string | null; refused?: boolean }): Mood {
  const s = (o.state ?? "").toUpperCase();
  if (s === "SUBMITTED") return "happy";
  if (o.refused || s === "HELD" || s === "DENIED" || s === "CANCELLED" || s === "PENDING_REVIEW") return "angry";
  if (o.persuaded || (o.meter ?? 0) >= 75) return "distressed";
  if ((o.meter ?? 0) > 0) return "worried";
  return "calm";
}

export function Margaret({ mood, className, alt, shadow = false }: { mood: Mood; className?: string; alt?: string; shadow?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <div className={cn("relative aspect-square", className)}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.img
          key={mood}
          src={`/margaret/${mood}.png`}
          alt={alt ?? `Margaret, ${MOOD_LABEL[mood].toLowerCase()}`}
          className={cn("absolute inset-0 h-full w-full object-contain", shadow && "drop-shadow-[0_10px_18px_rgba(60,3,6,0.18)]")}
          initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.92, rotate: -3, y: 8 }}
          animate={{ opacity: 1, scale: 1, rotate: 0, y: 0 }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
          transition={{ type: "spring", stiffness: 260, damping: 22 }}
          draggable={false}
        />
      </AnimatePresence>
    </div>
  );
}
