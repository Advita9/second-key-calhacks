// Retry policy for the kernel hop. Pure except for sleeping and logging.
//
// - transport errors (connection refused, reset, socket closed mid-request) and
//   5xx: retry quickly, backoff 1 s, 2 s, 4 s (capped), at most `attempts`.
// - timeout (kernel accepted the request and never answered within the budget):
//   never retried; a second 25 s wait would only delay the fail-closed row.
// - parse errors and 4xx: never retried.
// `withDeadline` is a last-resort watchdog so the caller always gets an answer
// even if something below swallows an abort.
import { KernelError } from './kernel.js';
import { warn } from './log.js';

export const sleep = (ms: number): Promise<void> => new Promise(r => setTimeout(r, ms));

export interface RetryOptions {
  attempts: number;
  baseMs: number;
  maxMs?: number;
  retryIf?: (e: unknown) => boolean;
  sleepImpl?: (ms: number) => Promise<void>;
}

export async function withRetry<T>(label: string, fn: () => Promise<T>, opts: RetryOptions): Promise<T> {
  const doSleep = opts.sleepImpl ?? sleep;
  let attempt = 0;
  for (;;) {
    attempt += 1;
    try {
      return await fn();
    } catch (err) {
      const retry = attempt < opts.attempts && (opts.retryIf ? opts.retryIf(err) : true);
      const msg = err instanceof Error ? err.message : String(err);
      if (!retry) throw err;
      const delay = Math.min(opts.maxMs ?? 10_000, opts.baseMs * 2 ** (attempt - 1));
      warn(`${label}.retry`, { attempt, delayMs: delay, error: msg });
      await doSleep(delay);
    }
  }
}

/** Kernel turn policy: retry transport errors and 5xx fast; never retry a timeout. */
export function shouldRetryKernel(err: unknown): boolean {
  if (!(err instanceof KernelError)) return true;
  if (err.isTimeout) return false;
  if (err.isTransport) return true;
  return err.kind === 'http' && (err.status ?? 0) >= 500;
}

export const KERNEL_RETRY: RetryOptions = { attempts: 3, baseMs: 1_000, maxMs: 4_000, retryIf: shouldRetryKernel };

export class DeadlineError extends Error {
  constructor(ms: number) {
    super(`watchdog: no answer after ${ms}ms`);
    this.name = 'DeadlineError';
  }
}

export function withDeadline<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const guard = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new DeadlineError(ms)), ms);
  });
  return Promise.race([promise, guard]).finally(() => clearTimeout(timer));
}
