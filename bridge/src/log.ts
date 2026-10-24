// One line per hop so the terminal tells the story during the demo.
export function log(hop: string, fields: Record<string, unknown> = {}): void {
  const ts = new Date().toISOString();
  const parts = Object.entries(fields).map(([k, v]) => `${k}=${fmt(v)}`);
  console.log(`${ts} [bridge] ${hop}${parts.length ? ' ' + parts.join(' ') : ''}`);
}

export function warn(hop: string, fields: Record<string, unknown> = {}): void {
  log(`WARN ${hop}`, fields);
}

function fmt(v: unknown): string {
  if (typeof v === 'string') return v.length > 80 ? JSON.stringify(v.slice(0, 77) + '...') : JSON.stringify(v);
  if (typeof v === 'bigint') return v.toString();
  if (v instanceof Error) return JSON.stringify(v.message);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}
