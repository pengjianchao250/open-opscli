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
