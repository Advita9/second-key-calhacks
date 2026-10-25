/** Hosts that mean "this machine". On a phone they mean the phone, not the laptop. */
const LOOPBACK = new Set(["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1"]);

export function isLoopbackHost(host: string): boolean {
  return LOOPBACK.has(host.toLowerCase());
}

/**
 * Addresses baked in at build time point at the phone itself when the page is opened from another
 * device on the venue Wi-Fi. In the browser, a loopback host is swapped for the host the page was
 * loaded from (the laptop's LAN address, the one in the QR code).
 */
export function reachable(url: string): string {
  if (typeof window === "undefined") return url;
  const here = window.location.hostname;
  if (!here || isLoopbackHost(here)) return url;
  try {
    const u = new URL(url);
    if (!isLoopbackHost(u.hostname)) return url;
    u.hostname = here;
    const out = u.toString();
    return !url.endsWith("/") && u.pathname === "/" && out.endsWith("/") ? out.slice(0, -1) : out;
  } catch {
    return url;
  }
}
