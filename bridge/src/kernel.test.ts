import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { KernelClient, KernelError } from './kernel.js';
import { KERNEL_RETRY, shouldRetryKernel, withDeadline, withRetry } from './retry.js';

const turn = { turn_id: '1', player_id: 'abc', text: 'hi' };

function listen(server: Server): Promise<string> {
  return new Promise(resolve => {
    server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${(server.address() as AddressInfo).port}`));
  });
}

async function closedPortUrl(): Promise<string> {
  const s = createServer();
  const url = await listen(s);
  await new Promise<void>(r => s.close(() => r()));
  return url;
}

test('hung kernel (accepts, never responds): rejects as timeout at the budget, no retry', async () => {
  const sockets = new Set<import('node:net').Socket>();
  const server = createServer((req, _res) => {
    req.on('data', () => {});
    // never respond
  });
  server.on('connection', s => sockets.add(s));
  const url = await listen(server);
  try {
    const kernel = new KernelClient({ baseUrl: url, timeoutMs: 300 });
    const t0 = Date.now();
    let attempts = 0;
    await assert.rejects(
      withRetry('t', () => { attempts += 1; return kernel.postTurn('DEMO', turn); }, { ...KERNEL_RETRY, sleepImpl: async () => {} }),
      (e: unknown) => e instanceof KernelError && e.isTimeout && /timeout after 300ms/.test(e.message)
    );
    const ms = Date.now() - t0;
    assert.equal(attempts, 1, 'a timeout is never retried');
    assert.ok(ms >= 280 && ms < 1500, `took ${ms}ms`);
  } finally {
    for (const s of sockets) s.destroy();
    server.close();
  }
});

test('kernel down (ECONNREFUSED): rejects fast as transport, retried 3 times with backoff', async () => {
  const url = await closedPortUrl();
  const kernel = new KernelClient({ baseUrl: url, timeoutMs: 5_000 });
  const delays: number[] = [];
  let attempts = 0;
  const t0 = Date.now();
  await assert.rejects(
    withRetry('t', () => { attempts += 1; return kernel.postTurn('DEMO', turn); }, { ...KERNEL_RETRY, sleepImpl: async ms => { delays.push(ms); } }),
    (e: unknown) => e instanceof KernelError && e.isTransport && /ECONNREFUSED/.test(e.message)
  );
  assert.equal(attempts, 3);
  assert.deepEqual(delays, [1000, 2000], 'backoff 1 s then 2 s');
  assert.ok(Date.now() - t0 < 2000, 'connection refused does not wait for the timeout');
});

test('kernel dies mid-request (socket closed before response): transport error, immediate', async () => {
  const server = createServer((req, res) => {
    req.on('data', () => {});
    req.on('end', () => setTimeout(() => res.socket?.destroy(), 50));
  });
  const url = await listen(server);
  try {
    const kernel = new KernelClient({ baseUrl: url, timeoutMs: 5_000 });
    const t0 = Date.now();
    await assert.rejects(kernel.postTurn('DEMO', turn), (e: unknown) => e instanceof KernelError && e.isTransport);
    assert.ok(Date.now() - t0 < 1500);
  } finally {
    server.close();
  }
});

test('5xx retries, 4xx and parse errors do not, timeouts do not', () => {
  assert.equal(shouldRetryKernel(new KernelError('x', 'http', 503)), true);
  assert.equal(shouldRetryKernel(new KernelError('x', 'http', 400)), false);
  assert.equal(shouldRetryKernel(new KernelError('x', 'parse')), false);
  assert.equal(shouldRetryKernel(new KernelError('x', 'timeout')), false);
  assert.equal(shouldRetryKernel(new KernelError('x', 'transport')), true);
  assert.equal(shouldRetryKernel(new Error('something else')), true);
});

test('withDeadline: a promise that never settles is rejected by the watchdog', async () => {
  const t0 = Date.now();
  await assert.rejects(withDeadline(new Promise<never>(() => {}), 100), /watchdog: no answer after 100ms/);
  assert.ok(Date.now() - t0 < 1000);
  assert.equal(await withDeadline(Promise.resolve(7), 100), 7);
});

test('malformed turn body fails closed as a parse error (not retried)', async () => {
  const server = createServer((_req, res) => {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ margaret_text: 'hi', stage: 55 }));
  });
  const url = await listen(server);
  try {
    const kernel = new KernelClient({ baseUrl: url });
    await assert.rejects(kernel.postTurn('DEMO', turn), (e: unknown) => e instanceof KernelError && e.kind === 'parse' && !shouldRetryKernel(e));
  } finally {
    server.close();
  }
});
