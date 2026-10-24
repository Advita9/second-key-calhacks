import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const KERNEL = "http://localhost:8001";
// The isolated kernel runs with OPS_TOKEN set (playwright.config.ts) so the gated reads are exercised.
const OPS = "e2e-ops-token";
const OPS_HEADERS = { "X-Ops-Token": OPS };
const SHOTS = path.join(__dirname, "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`), fullPage: false });
}

test.describe("board", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("renders Margaret, live payment, leaderboard, scoreboard, attack panel, footer", async ({ page }) => {
    await page.goto(`/board?token=${OPS}`);
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

  test("debrief shows the three rules and the tactic list", async ({ page }) => {
    await page.goto(`/board?debrief=1&token=${OPS}`);
    const d = page.getByTestId("debrief");
    await expect(d).toBeVisible();
    await expect(d).toContainText("Slow it down.");
    await expect(d).toContainText("Spot check: call the bank or a family member yourself.");
    await expect(d).toContainText("Stop. Do not send.");
    await expect(page.getByTestId("debrief-tactic")).toHaveCount(3);
    await shot(page, "board-debrief");
    await page.getByTestId("debrief-close").click();
    await expect(d).toBeHidden();
    await page.getByTestId("debrief-toggle").click();
    await expect(page.getByTestId("debrief")).toBeVisible();
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

  test("attack panel: all four buttons show the refusal and invariant", async ({ page }) => {
    await page.goto(`/board?token=${OPS}`);
    // Settle before the first click: token adopted from ?token=, room client up, kernel WS open.
    await expect.poll(() => page.evaluate(() => window.localStorage.getItem("sk:ops:token")), { timeout: 15_000 }).toBe(OPS);
    await expect(page.getByTestId("room-backend")).toContainText(/room: (memory|spacetime) \(open\)/, { timeout: 30_000 });
    await expect(page.getByText(/Kernel WS: open/)).toBeVisible({ timeout: 30_000 });
    const cases: [string, RegExp][] = [
      ["mutate", /SETTLEMENT REFUSED · I2_FINGERPRINT/],
      ["replay", /SETTLEMENT REFUSED · I3_REPLAY/],
      ["self-approve", /REFUSED · I5_CONFLICT/],
      ["inject", /HELD · H-\d{2}/],
    ];
    for (const [name, re] of cases) {
      // Sequential: click, then wait for this attack's own refusal (the first attack on a cold
      // kernel can take several seconds) before the next click.
      const button = page.getByTestId(`attack-${name}`);
      await expect(button).toBeEnabled({ timeout: 30_000 });
      await button.click();
      await expect.poll(() => page.getByTestId("refusal").textContent(), { timeout: 30_000, message: `${name} refusal` }).toMatch(re);
      await expect(button).toBeEnabled({ timeout: 30_000 });
      if (name === "mutate") {
        await page.waitForTimeout(600); // let the refusal animation settle before the screenshot
        await shot(page, "board-attack");
      }
    }
    // inject: the policy held on facts and the rule ids are on screen
    await expect(page.getByTestId("refusal-rules")).toContainText(/H-\d{2}/);
    // the live payment card got the pushed payment state from the WS
    await expect(page.getByTestId("live-payment").getByTestId("state-pill")).toBeVisible();
    await expect(page.getByTestId("room-backend")).toContainText("room: memory");
  });

  test("fresh load seeds the live payment card from GET /payments", async ({ page }) => {
    await page.goto(`/board?token=${OPS}`);
    await expect(page.getByTestId("live-payment").getByTestId("state-pill")).toBeVisible({ timeout: 15_000 });
  });

  test("without the operator token the board shows the token notice when reads are gated", async ({ page, request }) => {
    // Kernels that gate GET /payments with OPS_TOKEN answer 401 without the header.
    const gated = (await request.get(`${KERNEL}/payments?limit=1`)).status() === 401;
    await page.goto("/board");
    if (gated) {
      await expect(page.getByTestId("token-notice")).toBeVisible({ timeout: 15_000 });
    } else {
      await expect(page.getByTestId("live-payment").getByTestId("state-pill")).toBeVisible({ timeout: 15_000 });
      await expect(page.getByTestId("token-notice")).toHaveCount(0);
    }
  });
});

test.describe("board with operator token", () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test("?token= is stored and sent as X-Ops-Token on attacks and ?token= on the WS", async ({ page }) => {
    let seenHeader: string | undefined;
    await page.route("**/attack/mutate", async (route) => {
      seenHeader = route.request().headers()["x-ops-token"];
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ name: "mutate", steps: [], refused: true, invariant: "I2_FINGERPRINT", text: "SETTLEMENT REFUSED · I2_FINGERPRINT" }) });
    });
    const wsPromise = page.waitForEvent("websocket", (ws) => ws.url().includes("role=board"));
    await page.goto("/board?room=DEMO&token=x");
    const ws = await wsPromise;
    expect(ws.url()).toContain("token=x");
    expect(await page.evaluate(() => window.localStorage.getItem("sk:ops:token"))).toBe("x");
    await page.getByTestId("attack-mutate").click();
    await expect(page.getByTestId("refusal")).toContainText("I2_FINGERPRINT");
    expect(seenHeader).toBe("x");
    // A 401 from an attack shows the token notice with the paste field.
    await page.route("**/attack/replay", (route) => route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ refused: true, reason: "ops token required" }) }));
    await page.getByTestId("attack-replay").click();
    await expect(page.getByTestId("token-notice")).toBeVisible();
    await expect(page.getByTestId("refusal")).toContainText("OPERATOR TOKEN REQUIRED");
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

  test("joins a room with a code and sends a turn", async ({ page }) => {
    await page.goto("/play?room=E2E");
    await expect(page.getByTestId("room-input")).toHaveValue("E2E");
    await page.getByTestId("handle-input").fill("smoketester");
    await page.getByTestId("join-button").click();
    await expect(page.getByTestId("turn-input")).toBeVisible();
    await expect(page.getByTestId("send-button")).toBeVisible();
    await expect(page.getByTestId("stage-bar")).toBeVisible();
    await page.getByTestId("tactic-urgency").click();
    await expect(page.getByTestId("turn-input")).not.toHaveValue("");
    await page.getByTestId("send-button").click();
    await expect(page.getByTestId("msg-you").first()).toBeVisible();
    await expect(page.getByTestId("msg-margaret").first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("stage-bar").getByRole("progressbar")).toHaveAttribute("aria-valuenow", /^(10|40|60|70|90|100)$/);
    // Attacker view never shows rule ids.
    await expect(page.getByTestId("play")).not.toContainText(/\b[HDAX]-\d{2}\b/);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(over).toBeLessThanOrEqual(0);
    await shot(page, "play-chat");
  });
});

test.describe("ops", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("holds queue fills from a HELD payment, approve works, verify green then tamper then red", async ({ page, request }) => {
    // Seed a HELD payment: S-03 body with an empty mule list (D-01 off, H-01/H-03 still fire).
    const s03 = JSON.parse(fs.readFileSync(path.join(__dirname, "../../fixtures/cases/S-03.json"), "utf8")) as {
      payment: Record<string, unknown>;
      account_context: Record<string, unknown>;
      conversation: unknown[];
    };
    const created = await request.post(`${KERNEL}/payments`, {
      headers: OPS_HEADERS,
      data: { ...s03.payment, conversation_id: "e2e_s03", conversation: s03.conversation, account_context: { ...s03.account_context, mule_list: [] } },
    });
    expect(created.ok()).toBeTruthy();
    const payment = (await created.json()) as { id: string; state: string };
    expect(payment.state).toBe("HELD");

    await page.goto(`/ops?token=${OPS}`);
    await expect(page.getByTestId("holds-queue")).toBeVisible();
    await expect(page.getByTestId("holds-queue")).toContainText("Holds queue");
    await expect(page.getByTestId("audit-list")).toBeVisible();
    const verify = page.getByTestId("verify-button");
    await expect(verify).toBeVisible();
    await expect(page.getByTestId("policy-panel")).toBeVisible();
    await expect(page.getByTestId("property-badge")).toContainText(/properties|Property suite/);
    await expect(page.getByTestId("property-badge")).toContainText("backend/tests/property");
    await expect(page.getByTestId("certificates-log")).toBeVisible();
    await expect(page.getByTestId("payment-history")).toBeVisible();
    await expect(page.getByTestId("ops-token")).toBeVisible();
    await expect(page.getByTestId("scripted-attack-button")).toBeVisible();

    // Holds queue shows the seeded payment; approve as BANK_REVIEW lifts it.
    const row = page.getByTestId("hold-row").filter({ hasText: payment.id.slice(0, 12) });
    await expect(row).toBeVisible();
    await expect(row).toContainText(/H-\d{2}/);
    await shot(page, "ops");
    await row.getByTestId("approve-button").click();
    await expect(row).toBeHidden({ timeout: 10_000 });
    const after = (await (await request.get(`${KERNEL}/payments/${payment.id}`, { headers: OPS_HEADERS })).json()) as { state: string };
    expect(after.state).toBe("ELIGIBLE_TO_SUBMIT");

    // Payment history replay for the approved payment.
    await page.getByTestId("payment-select").selectOption(payment.id);
    await expect(page.getByTestId("payment-history")).toContainText("ELIGIBLE TO SUBMIT");
    await expect(page.getByTestId("payment-history")).toContainText("BANK_REVIEW");

    // Audit chain: green, then tamper (demo mode), then red with the bad seq highlighted.
    // Tamper is irreversible, so on a reused kernel (reuseExistingServer) the chain may already be red.
    await verify.click();
    await expect(verify).toHaveAttribute("data-verdict", /ok|bad/);
    if ((await verify.getAttribute("data-verdict")) === "ok") {
      await page.getByTestId("tamper-button").click();
      await verify.click();
    }
    await expect(verify).toHaveAttribute("data-verdict", "bad");
    await expect(verify).toContainText(/Broken at seq \d+/);
    await expect(page.getByTestId("audit-list").locator("li.text-bad").first()).toBeVisible();
    await page.waitForTimeout(400); // let the color transition settle before the screenshot
    await shot(page, "ops-tampered");
  });
});
