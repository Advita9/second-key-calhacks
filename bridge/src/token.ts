// The SDK keeps the auth token in memory only. We persist it so the bridge
// keeps the same identity across restarts (the identity the owner authorized
// with `set_worker_identity`). The hex identity is written next to it so
// scripts/dev.sh and the e2e can read it without parsing logs.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const BRIDGE_DIR = resolve(here, '..');
export const TOKEN_FILE = process.env.BRIDGE_TOKEN_FILE ?? resolve(BRIDGE_DIR, '.spacetimedb-token');
export const IDENTITY_FILE = process.env.BRIDGE_IDENTITY_FILE ?? resolve(BRIDGE_DIR, '.identity.hex');

export function loadToken(file: string = TOKEN_FILE): string | undefined {
  if (!existsSync(file)) return undefined;
  const tok = readFileSync(file, 'utf8').trim();
  return tok.length > 0 ? tok : undefined;
}

export function saveToken(token: string, file: string = TOKEN_FILE): void {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, token + '\n', { mode: 0o600 });
}

export function saveIdentityHex(hex: string, file: string = IDENTITY_FILE): void {
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, hex + '\n');
}
