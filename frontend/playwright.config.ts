import { defineConfig, devices } from "@playwright/test";

// Both servers are started here because scripts/acceptance.sh starts nothing itself.
// The smoke uses its own ports (kernel 8001, Next 3002) and its own build dir (.next-e2e) so it
// never reuses a token-protected dev stack on 8000/3001 (SpacetimeDB owns 3000).
const KERNEL_ENV = "KERNEL_DB=:memory: MOCK_EXTRACTOR=1 MOCK_MARGARET=1 ROOM_BACKEND=memory DEMO_MODE=1 TTS_PROVIDER=mock STT_PROVIDER=mock KERNEL_LOAD_DOTENV=0 OPS_TOKEN=e2e-ops-token";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["line"]],
  outputDir: "test-results",
  use: {
    baseURL: "http://localhost:3002",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `cd ../backend && ${KERNEL_ENV} uv run uvicorn api.main:app --port 8001`,
      url: "http://localhost:8001/health",
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      // Always a fresh build: NEXT_PUBLIC_* and the /kernel rewrite target are inlined at build time.
      command: "npx next build && npx next start -p 3002",
      url: "http://localhost:3002/board",
      reuseExistingServer: true,
      timeout: 240_000,
      stdout: "ignore",
      stderr: "pipe",
      env: {
        NEXT_DIST_DIR: ".next-e2e",
        KERNEL_URL: "http://localhost:8001",
        NEXT_PUBLIC_KERNEL_URL: "http://localhost:8001",
        NEXT_PUBLIC_ROOM_BACKEND: "memory",
      },
    },
  ],
});
