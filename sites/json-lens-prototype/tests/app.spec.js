import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

const API_URL = "http://127.0.0.1:8765/api/v1/keepa/run";

async function mockKeepaApi(page, onPost = () => {}) {
  await page.route(API_URL, async (route) => {
    const request = route.request();
    const corsHeaders = {
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Origin": "http://127.0.0.1:4173",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers: corsHeaders, body: "OK" });
      return;
    }
    onPost(request);
    await route.fulfill({
      status: 200,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
      json: {
        success: true,
        data: [{ asin: "B0CQM9WB7R", title: "Integration fixture", stats: 30 }],
        error: null,
      },
    });
  });
}

test("商品查询发送正确的 Authorization 与请求体", async ({ page }) => {
  let capturedRequest;
  await mockKeepaApi(page, (request) => { capturedRequest = request; });
  await page.goto("/?variant=a");

  await page.locator('[data-field="scenario"]').selectOption("product");
  await page.locator('[data-param="identifier"]').fill("B0CQM9WB7R");
  await page.locator("details.connection-options summary").click();
  await page.locator('[data-field="apiKey"]').fill("Authorization: Bearer opscli-mcp-test-key");
  await page.locator("details.common-options summary").click();
  await page.locator('[data-field="wait"]').uncheck();
  await page.getByRole("button", { name: "运行商品详情" }).click();

  await expect(page.locator(".status-line")).toContainText("请求成功");
  expect(capturedRequest).toBeTruthy();
  expect(capturedRequest.headers().authorization).toBe("Bearer opscli-mcp-test-key");
  expect(capturedRequest.postDataJSON()).toEqual({
    scenario: "product",
    site: "US",
    params: {
      asin: "B0CQM9WB7R",
      history: false,
      stats: 30,
    },
    export_format: "json",
    wait: false,
  });
});

test("切换场景会同步更新查询表单和结果数据", async ({ page }) => {
  await page.goto("/?variant=a");
  const initialScroll = await page.evaluate(() => window.scrollY);

  await page.locator('[data-field="scenario"]').selectOption("seller-finder");

  await expect(page.locator(".scenario-intro h3")).toHaveText("Seller Finder");
  await expect(page.locator("table thead")).toContainText("sellerId");
  await expect(page.locator("table tbody tr")).toHaveCount(2);
  expect(await page.evaluate(() => window.scrollY)).toBe(initialScroll);
});

test("场景标识在窄侧栏中保持单行且不溢出", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?variant=a");

  const badge = page.locator(".scenario-intro > .badge");
  const dimensions = await badge.evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight,
    whiteSpace: getComputedStyle(element).whiteSpace,
  }));
  expect(dimensions.whiteSpace).toBe("nowrap");
  expect(dimensions.scrollHeight).toBeLessThanOrEqual(dimensions.clientHeight);
});

test("桌面结果工具栏保持单行且控件等高", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?variant=a");

  const boxes = await Promise.all([
    page.locator(".result-toolbar > input").boundingBox(),
    page.locator(".result-toolbar > .tabs").boundingBox(),
    page.locator(".result-toolbar > .btn").boundingBox(),
  ]);
  expect(boxes.every(Boolean)).toBe(true);
  const yPositions = boxes.map((box) => box.y);
  const heights = boxes.map((box) => box.height);
  expect(Math.max(...yPositions) - Math.min(...yPositions)).toBeLessThanOrEqual(1);
  expect(Math.max(...heights) - Math.min(...heights)).toBeLessThanOrEqual(1);
  const header = await page.locator(".result-panel > .panel-header").boundingBox();
  expect(header.height).toBeLessThanOrEqual(70);
});

test("视图切换选项不会溢出 Tab 容器", async ({ page }) => {
  await page.goto("/?variant=a");

  const tabs = await page.locator(".result-toolbar > .tabs").boundingBox();
  const items = await page.locator(".result-toolbar .tab").all();
  const boxes = await Promise.all(items.map((item) => item.boundingBox()));
  expect(tabs).not.toBeNull();
  expect(boxes.every(Boolean)).toBe(true);
  expect(Math.max(...boxes.map((box) => box.y + box.height))).toBeLessThanOrEqual(tabs.y + tabs.height);
});

test("长文本缩略显示并保留完整悬停内容", async ({ page }) => {
  const longTitle = "这是一个用于验证表格单元格不会被超长商品标题撑开的完整商品名称".repeat(3);
  await page.goto("/?variant=a");
  await page.locator("json-lens-app").evaluate((app, title) => {
    app.state.data = [{ asin: "B0LONGTEXT", title }];
    app.render();
  }, longTitle);

  const titleCell = page.locator(".cell-value").filter({ hasText: longTitle });
  await expect(titleCell).toHaveAttribute("title", longTitle);
  const dimensions = await titleCell.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    textOverflow: getComputedStyle(element).textOverflow,
  }));
  expect(dimensions.scrollWidth).toBeGreaterThan(dimensions.clientWidth);
  expect(dimensions.textOverflow).toBe("ellipsis");
});

test("下载当前筛选后的 CSV 表格", async ({ page }) => {
  await page.goto("/?variant=a");
  await page.locator("[data-filter]").fill("Camping");
  await expect(page.locator("table tbody tr")).toHaveCount(1);

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 CSV" }).click();
  const download = await downloadPromise;
  const downloadPath = await download.path();
  const csv = await readFile(downloadPath, "utf8");

  expect(download.suggestedFilename()).toMatch(/^keepa-product-search-US-\d{4}-\d{2}-\d{2}\.csv$/);
  expect(csv).toContain("Compact Camping Lantern");
  expect(csv).not.toContain("Rechargeable Work Light");
  expect(csv).toContain('[""camping""]');
});

test("Top Sellers 字符串数组显示 Seller ID 并限制单页行数", async ({ page }) => {
  await page.goto("/?variant=a");
  await page.locator('[data-field="scenario"]').selectOption("top-seller");
  await page.locator("json-lens-app").evaluate((app) => {
    app.state.data = Array.from({ length: 100_000 }, (_, index) => `SELLER-${String(index + 1).padStart(6, "0")}`);
    app.render();
  });

  await expect(page.locator("table thead")).toContainText("sellerId");
  await expect(page.locator("table tbody tr")).toHaveCount(100);
  await expect(page.locator("table tbody tr").first()).toContainText("SELLER-000001");
  await expect(page.locator(".table-pagination")).toContainText("100,000 条");
  await expect(page).toHaveScreenshot("top-sellers-desktop.png");

  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.locator("table tbody tr").first()).toContainText("SELLER-000101");

  await page.locator("[data-filter]").fill("SELLER-100000");
  await expect(page.locator("table tbody tr")).toHaveCount(1);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "下载 CSV" }).click();
  const download = await downloadPromise;
  const csv = await readFile(await download.path(), "utf8");
  expect(csv).toContain('"sellerId"');
  expect(csv).toContain('"SELLER-100000"');
});

test("默认使用明亮主题并记住暗色选择", async ({ page }) => {
  await page.goto("/?variant=a");

  const themeToggle = page.getByRole("switch", { name: "切换明暗主题" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "corporate");
  await expect(themeToggle).not.toBeChecked();

  await themeToggle.check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "business");
  expect(await page.evaluate(() => localStorage.getItem("json-lens-theme"))).toBe("business");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "business");
  await expect(page.getByRole("switch", { name: "切换明暗主题" })).toBeChecked();
});

test("历史查询只保存查询条件并可重新载入", async ({ page }) => {
  await mockKeepaApi(page);
  await page.goto("/?variant=a");
  await page.locator("details.connection-options summary").click();
  await page.locator('[data-field="apiKey"]').fill("opscli-mcp-history-test-key");
  await page.getByRole("button", { name: "运行商品关键词搜索" }).click();
  await expect(page.locator(".status-line")).toContainText("请求成功");

  const records = await page.evaluate(() => JSON.parse(localStorage.getItem("json-lens-query-history")));
  expect(records).toHaveLength(1);
  expect(records[0]).toMatchObject({ scenario: "product-search", site: "US", wait: true, params: { keyword: "flashlight" } });
  const serialized = JSON.stringify(records);
  expect(serialized).not.toContain("history-test-key");
  expect(serialized).not.toContain("Integration fixture");
  expect(serialized).not.toContain(API_URL);

  const historyPanel = page.locator("[data-history-panel]");
  const historyContent = page.locator("[data-history-content]");
  await expect(historyContent).toHaveCSS("max-height", "0px");
  await historyPanel.hover();
  await expect(historyContent).toHaveCSS("max-height", "340px");

  await page.locator('[data-field="scenario"]').selectOption("seller-finder");
  await historyPanel.hover();
  await page.getByRole("button", { name: "重新载入 商品关键词搜索 US" }).click();
  await expect(page.locator('[data-field="scenario"]')).toHaveValue("product-search");
  await expect(page.locator('[data-param="keyword"]')).toHaveValue("flashlight");

  await page.getByRole("button", { name: "清空历史" }).click();
  expect(await page.evaluate(() => localStorage.getItem("json-lens-query-history"))).toBeNull();
  await expect(page.locator("[data-history-panel] .badge")).toHaveText("0");
});

test("桌面端布局视觉基线", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?variant=a");
  await expect(page).toHaveScreenshot("variant-a-desktop.png", { fullPage: true });
});

test("移动端布局视觉基线", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?variant=a");
  const runButtonBox = await page.getByRole("button", { name: "运行商品关键词搜索" }).boundingBox();
  const switcherBox = await page.locator(".prototype-switcher").boundingBox();
  expect(runButtonBox).toBeTruthy();
  expect(switcherBox).toBeTruthy();
  expect(switcherBox.y).toBeGreaterThanOrEqual(runButtonBox.y + runButtonBox.height);
  await expect(page).toHaveScreenshot("variant-a-mobile.png", { fullPage: true });
});

test("暗色主题视觉基线", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?variant=a");
  await page.getByRole("switch", { name: "切换明暗主题" }).check();
  await expect(page).toHaveScreenshot("variant-a-dark-desktop.png", { fullPage: true });
});

test("历史查询展开视觉基线", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?variant=a");
  await page.locator("json-lens-app").evaluate((app) => {
    app.state.history = [
      { id: "history-product", createdAt: "2026-08-28T04:20:00.000Z", scenario: "product-search", site: "US", wait: true, params: { keyword: "flashlight", stats: 30 } },
      { id: "history-seller", createdAt: "2026-08-28T03:45:00.000Z", scenario: "seller-finder", site: "DE", wait: true, params: { search: "AUKEY", currentRating_gte: 95 } },
      { id: "history-deals", createdAt: "2026-08-27T09:10:00.000Z", scenario: "deals", site: "GB", wait: false, params: { priceTypes: "0", isDrop: true } },
    ];
    app.render();
  });
  await page.locator("[data-history-panel]").hover();
  await expect(page.locator("[data-history-content]")).toHaveCSS("max-height", "340px");
  await expect(page).toHaveScreenshot("history-expanded-desktop.png", { fullPage: true });
});
