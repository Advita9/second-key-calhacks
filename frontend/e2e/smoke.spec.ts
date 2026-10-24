import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const KERNEL = "http://localhost:8000";
const SHOTS = path.join(__dirname, "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
}

async function routeExists(request: APIRequestContext, method: "get" | "post", url: string) {
  const res = method === "get" ? await request.get(url) : await request.post(url, { data: {} });
  return res.status() !== 404;
}

test.describe("board", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("renders Margaret, live payment, leaderboard, scoreboard, attack panel, footer", async ({ page }) => {
    await page.goto("/board");
    await expect(page.getByTestId("margaret-card")).toBeVisible();
    await expect(page.getByTestId("margaret-card")).toContainText("Margaret");
    await expect(page.getByTestId("margaret-card")).toContainText("Age 72");
    await expect(page.getByTestId("live-payment")).toBeVisible();
    await expect(page.getByTestId("leaderboard")).toBeVisible();
    await expect(page.getByTestId("scoreboard")).toContainText("Unauthorized releases");
    await expect(page.getByTestId("scoreboard")).toContainText("Legitimate completed");
    await expect(page.getByTestId("attack-panel")).toBeVisible();
    for (const a of ["inject", "mutate", "replay", "self-approve"]) {
      await expect(page.getByTestId(`attack-${a}`)).toBeVisible();
    }
    await expect(page.getByTestId("room-code")).toHaveText(/\w{2,}/);
    await expect(page.getByTestId("board-footer").locator("svg")).toBeVisible(); // QR
    await shot(page, "board");
  });

  test("MOCK badge visible when /health reports any mock", async ({ page, request }) => {
    const health = (await (await request.get(`${KERNEL}/health`)).json()) as { mode?: Record<string, string> };
    const anyMock = Object.values(health.mode ?? {}).some((v) => v === "mock" || v === "memory");
    await page.goto("/board");
    if (anyMock) {
      await expect(page.getByTestId("mock-badges").first()).toBeVisible();
      await expect(page.getByTestId("mock-badges").first()).toContainText("MOCK");
    } else {
      await expect(page.getByText("All providers real").first()).toBeVisible();
    }
  });

  test("attack panel button shows a refusal when the route is live", async ({ page, request }) => {
    const live = await routeExists(request, "post", `${KERNEL}/attack/mutate`);
    await page.goto("/board");
    await page.getByTestId("attack-mutate").click();
    if (live) {
      await expect(page.getByTestId("refusal")).toContainText(/SETTLEMENT REFUSED · I2/);
    } else {
      await expect(page.getByTestId("refusal")).toContainText("ATTACK ROUTE NOT LIVE YET");
    }
    await page.waitForTimeout(600); // let the refusal animation settle before the screenshot
    await shot(page, "board-attack");
  });
});

test.describe("play", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("mobile viewport has no horizontal scroll", async ({ page }) => {
    await page.goto("/play?room=DEMO");
    await expect(page.getByTestId("join-form")).toBeVisible();
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
    await shot(page, "play-join");
  });

  test("joins a room with a code and sends a turn", async ({ page, request }) => {
    const joinLive = await routeExists(request, "post", `${KERNEL}/rooms/E2E/join`);
    await page.goto("/play?room=E2E");
    await expect(page.getByTestId("room-input")).toHaveValue("E2E");
    await page.getByTestId("handle-input").fill("smoketester");
    await page.getByTestId("join-button").click();
    if (!joinLive) {
      // TODO(lead): remove this branch once POST /rooms/{room}/join lands; keep the strict path below.
      await expect(page.getByRole("alert")).toBeVisible();
      await expect(page.getByTestId("join-button")).toBeVisible();
      return;
    }
    await expect(page.getByTestId("turn-input")).toBeVisible();
    await expect(page.getByTestId("send-button")).toBeVisible();
    await expect(page.getByTestId("stage-bar")).toBeVisible();
    await page.getByTestId("tactic-urgency").click();
    await expect(page.getByTestId("turn-input")).not.toHaveValue("");
    await page.getByTestId("send-button").click();
    await expect(page.getByTestId("msg-you").first()).toBeVisible();
    const submitLive = await routeExists(request, "post", `${KERNEL}/rooms/E2E/submit`);
    if (submitLive) {
      await expect(page.getByTestId("msg-margaret").first()).toBeVisible({ timeout: 20_000 });
    } else {
      // TODO(lead): drop this branch once POST /rooms/{room}/submit is mounted in api/main.py.
      await expect(page.getByTestId("notice")).toBeVisible();
    }
    // Attacker view never shows rule ids.
    await expect(page.getByTestId("play")).not.toContainText(/\b[HDAX]-\d{2}\b/);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
    await shot(page, "play-chat");
  });
});

test.describe("ops", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("shows holds queue and audit verify button; verify turns green or red", async ({ page, request }) => {
    const verifyLive = await routeExists(request, "get", `${KERNEL}/audit/verify`);
    await page.goto("/ops");
    await expect(page.getByTestId("holds-queue")).toBeVisible();
    await expect(page.getByTestId("holds-queue")).toContainText("Holds queue");
    await expect(page.getByTestId("audit-list")).toBeVisible();
    const verify = page.getByTestId("verify-button");
    await expect(verify).toBeVisible();
    await expect(page.getByTestId("policy-panel")).toBeVisible();
    await expect(page.getByTestId("certificates-log")).toBeVisible();
    await expect(page.getByTestId("payment-history")).toBeVisible();
    await verify.click();
    if (verifyLive) {
      await expect(verify).toHaveAttribute("data-verdict", /ok|bad/);
    } else {
      await expect(page.getByRole("alert").first()).toBeVisible();
    }
    await shot(page, "ops");
  });
});
