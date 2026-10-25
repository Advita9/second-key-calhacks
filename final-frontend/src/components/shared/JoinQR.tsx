"use client";

import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { isLoopbackHost } from "@/lib/host";
import { cn } from "@/lib/utils";

/** Join URL for phones. The projector usually opens the board on localhost, which a phone cannot reach:
 *  NEXT_PUBLIC_PLAY_ORIGIN (the laptop's LAN address) replaces a loopback origin in the QR code. */
export function useJoinUrl(roomCode: string) {
  const [joinUrl, setJoinUrl] = useState("");
  useEffect(() => {
    const lan = process.env.NEXT_PUBLIC_PLAY_ORIGIN;
    const origin = lan && isLoopbackHost(window.location.hostname) ? lan.replace(/\/$/, "") : window.location.origin;
    setJoinUrl(`${origin}/play?room=${encodeURIComponent(roomCode)}`);
  }, [roomCode]);
  return joinUrl;
}

export function QR({ value, size = 120, className }: { value: string; size?: number; className?: string }) {
  return (
    <div className={cn("rounded-xl bg-white p-2.5 ring-1 ring-line", className)} style={{ width: size + 20, height: size + 20 }}>
      {value ? <QRCodeSVG value={value} size={size} level="M" fgColor="#1b1716" bgColor="#ffffff" /> : null}
    </div>
  );
}
