import { WsRoomClient } from "./ws";
import type { RoomBackend, RoomClient } from "./types";

export * from "./types";
export { audioSrc } from "./ws";

/** NEXT_PUBLIC_ROOM_BACKEND=spacetime selects SpacetimeDB (needs generated bindings, see next.config.ts). Default: kernel memory room. */
export function roomBackend(): RoomBackend {
  const v = process.env.NEXT_PUBLIC_ROOM_BACKEND;
  if (v === "spacetime" && process.env.NEXT_PUBLIC_HAS_BINDINGS === "1") return "spacetime";
  return "memory";
}

/** Picks the backend from NEXT_PUBLIC_ROOM_BACKEND. SpacetimeDB is loaded lazily on connect. */
export function makeRoomClient(): RoomClient {
  if (roomBackend() === "spacetime") return makeLazySpacetime();
  return new WsRoomClient();
}

function makeLazySpacetime(): RoomClient {
  let inner: RoomClient | null = null;
  const fallback = new WsRoomClient();
  const pending: Array<(c: RoomClient) => void> = [];
  const get = () => inner ?? fallback;
  return {
    backend: "spacetime",
    async connect(o) {
      const mod = await import("./spacetime");
      const c = new mod.SpacetimeRoomClient();
      try {
        await c.connect(o);
        inner = c;
      } catch {
        // Bindings or server missing: fall back to the kernel memory room.
        await fallback.connect(o);
        inner = fallback;
      }
      for (const p of pending) p(inner);
      pending.length = 0;
    },
    join: (h) => get().join(h),
    submitTurn: (t, a) => get().submitTurn(t, a),
    subscribe(cb) {
      let un = get().subscribe(cb);
      if (!inner) pending.push((c) => {
        un();
        un = c.subscribe(cb);
      });
      return () => un();
    },
    onStatus(cb) {
      let un = get().onStatus(cb);
      if (!inner) pending.push((c) => {
        un();
        un = c.onStatus(cb);
      });
      return () => un();
    },
    myId: () => get().myId(),
    close: () => {
      inner?.close();
      fallback.close();
    },
  };
}
