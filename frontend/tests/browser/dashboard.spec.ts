import { test, expect } from "@playwright/test";

test("workflow, comparison, graph evidence and navigation work without configuration", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Workflow overview." }),
  ).toBeVisible();
  await expect(page.getByText("Recorded demo", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: /Retrieve Find historical context/ })
    .click();
  await expect(page.getByText("Inspect event payload")).toBeVisible();
  await page.getByRole("combobox", { name: "Inspect batch" }).selectOption("0");
  await expect(page.getByText("Batch 1 complete")).toBeVisible();
  await page
    .getByRole("button", { name: "Response evaluation", exact: true })
    .click();
  await expect(page).toHaveURL(/view=evaluation/);
  await expect(
    page.getByRole("heading", { name: "Normal response" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Our response" }),
  ).toBeVisible();
  await expect(
    page.getByText("The recommendation is unchanged.", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Not scored", { exact: true })).toHaveCount(2);
  await page
    .getByRole("button", { name: "New comparison", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page
    .getByRole("button", { name: "Memory explorer", exact: true })
    .click();
  await page.getByRole("button", { name: "Retrieved", exact: true }).click();
  await expect(page.locator(".graph-node").first()).toBeVisible();
  await page.locator(".graph-node").first().click();
  await expect(page.locator(".node-detail")).toBeVisible();
  await page.locator(".node-detail .source-chips button").first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("Original 311 record")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page
    .getByRole("textbox", { name: "Search sources" })
    .fill("this-source-does-not-exist");
  await expect(
    page.getByText("No sources match", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Event trace", exact: false }).click();
  await page
    .getByRole("combobox", { name: "Filter event type" })
    .selectOption("grouped");
  await expect(page.locator(".event-row")).toHaveCount(9);
  await page.locator(".event-row summary").first().click();
  await expect(page.locator(".event-row pre").first()).toBeVisible();
  expect(errors).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("failed replay retains visible data and shows an actionable error", async ({
  page,
}) => {
  await page.route("**/api/replay", (route) =>
    route.fulfill({
      status: 503,
      json: {
        error: "Replay unavailable. Your recorded snapshot is still available.",
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Run replay", exact: true }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Replay unavailable" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Normal response" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Run replay", exact: true }),
  ).toBeEnabled();
});

test("real Python replay refreshes the dashboard", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Run replay", exact: true }).click();
  await expect(
    page.getByText("Replay complete.", { exact: false }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole("heading", { name: "Normal response" }),
  ).toBeVisible();
});

test("live empty-context comparison does not invent graph data or claim an improvement", async ({
  page,
}) => {
  await page.route("**/api/config", (route) =>
    route.fulfill({
      json: { memory_api: true, model: true, model_name: "test-model" },
    }),
  );
  const result = {
    text: "There is insufficient evidence to identify a pattern.",
    current_source_ids: [],
    historical_source_ids: [],
    latency_ms: 100,
    input_tokens: 20,
    output_tokens: 12,
  };
  await page.route("**/api/evaluate", (route) =>
    route.fulfill({
      json: {
        mode: "live",
        generated_at: "2026-09-26T21:00:00Z",
        adapter: "test-model",
        record_count: 0,
        batch_size: 0,
        batches: [],
        records: [],
        nodes: [],
        edges: [],
        baseline: result,
        memory: result,
        prompt: "What should we investigate?",
        context: {
          seed_ids: [],
          source_ids: [],
          nodes: [],
          edges: [],
          context_text: "",
          token_count: 0,
          truncated: false,
        },
      },
    }),
  );
  await page.goto("/?view=evaluation");
  await page.getByRole("button", { name: "New comparison" }).click();
  await page.getByLabel("Your question").fill("What should we investigate?");
  await page
    .getByRole("button", { name: "Compare responses", exact: true })
    .click();
  await expect(
    page.getByText("Live comparison", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No response difference observed in this run.", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("The deterministic adapter returns", { exact: false }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Memory explorer", exact: true })
    .click();
  await expect(page.getByText("No memory nodes in this view")).toBeVisible();
  await page.getByRole("button", { name: "Event trace", exact: false }).click();
  await expect(
    page.getByText("No pipeline trace events in this run"),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("all response evidence can be expanded", async ({ page }) => {
  await page.goto("/?view=evaluation");
  const memoryCard = page.locator(".memory-response");
  await memoryCard.getByRole("button", { name: /\+\d+ more/ }).click();
  await expect(
    memoryCard.getByRole("button", { name: "Show fewer" }),
  ).toBeVisible();
  await expect(memoryCard.locator(".source-chips button")).toHaveCount(22);
});
