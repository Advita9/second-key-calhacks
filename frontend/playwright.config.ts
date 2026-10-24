import { defineConfig, devices } from "@playwright/test";

// Both servers are started here because scripts/acceptance.sh starts nothing itself.
// Port 3000 belongs to SpacetimeDB, so Next runs on 3001 and the kernel on 8000.
const KERNEL_ENV = "KERNEL_DB=:memory: MOCK_EXTRACTOR=1 MOCK_MARGARET=1 ROOM_BACKEND=memory DEMO_MODE=1 TTS_PROVIDER=mock STT_PROVIDER=mock";

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
    baseURL: "http://localhost:3001",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `cd ../backend && ${KERNEL_ENV} uv run uvicorn api.main:app --port 8000`,
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "test -f .next/BUILD_ID || npm run build; npx next start -p 3001",
      url: "http://localhost:3001/board",
      reuseExistingServer: true,
      timeout: 180_000,
      stdout: "ignore",
      stderr: "pipe",
      env: { NEXT_PUBLIC_KERNEL_URL: "http://localhost:8000" },
    },
  ],
});
