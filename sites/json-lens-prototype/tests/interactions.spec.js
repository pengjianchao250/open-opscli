import { expect, test } from "@playwright/test";

const API_URL = "http://127.0.0.1:8765/api/v1/keepa/run";
const LOCALHOST_API_URL = "http://localhost:8765/api/v1/keepa/run";

async function fulfillJson(route, status, json) {
  await route.fulfill({ status, contentType: "application/json", json });
}

test("缺少 crypto.randomUUID 时仍可提交并记录历史", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window.crypto, "randomUUID", {
      configurable: true,
      value: undefined,
    });
  });
  await page.route(API_URL, async (route) => {
    await fulfillJson(route, 200, { success: true, data: [{ asin: "B0FALLBACK" }], error: null });
  });
  await page.goto("/?variant=a");

  await page.getByRole("button", { name: "运行商品关键词搜索" }).click();

  await expect(page.locator(".status-line")).toContainText("请求成功");
  await expect(page.locator("[data-history-panel] .badge")).toHaveText("1");
});

test("默认 API 地址跟随页面主机名", async ({ page }) => {
  await page.route(LOCALHOST_API_URL, async (route) => {
    await fulfillJson(route, 200, { success: true, data: [{ asin: "B0LOCALHOST" }], error: null });
  });
  await page.goto("http://localhost:4173/?variant=a");
  await page.locator("details.connection-options summary").click();

  await expect(page.getByLabel("接口地址")).toHaveValue(LOCALHOST_API_URL);
  await page.getByRole("button", { name: "运行商品关键词搜索" }).click();
  await expect(page.locator(".status-line")).toContainText("请求成功");
});

test("Product Finder 会转换并合并复杂筛选参数", async ({ page }) => {
  let requestBody;
  await page.route(API_URL, async (route) => {
    requestBody = route.request().postDataJSON();
    await fulfillJson(route, 200, { success: true, data: [{ asin: "B0FILTERED" }], error: null });
  });
  await page.goto("/?variant=a");
  await page.getByLabel("查询场景").selectOption("product-finder");
  await page.getByLabel("品牌").fill("AUKEY, Anker");
  await page.getByLabel("根类目 ID").fill("172282, 1055398");
  await page.getByLabel("必须有评论").check();
  await page.locator("details.advanced-options summary").click();
  await page.getByLabel("返回数量").selectOption("500");
  await page.getByLabel("自定义筛选 JSON").fill('{"variationCount":{"gte":2}}');

  await page.getByRole("button", { name: "运行Product Finder" }).click();

  await expect(page.locator(".status-line")).toContainText("请求成功");
  expect(requestBody.params).toEqual({
    perPage: "500",
    selection: {
      brand: ["AUKEY", "Anker"],
      rootCategory: [172282, 1055398],
      hasReviews: true,
      variationCount: { gte: 2 },
    },
  });
});

test("筛选校验失败会保留在页面且不发送请求", async ({ page }) => {
  let requestCount = 0;
  await page.route(API_URL, async (route) => {
    requestCount += 1;
    await fulfillJson(route, 200, { data: [] });
  });
  await page.goto("/?variant=a");
  await page.getByLabel("查询场景").selectOption("product-finder");

  await page.getByRole("button", { name: "运行Product Finder" }).click();
  await expect(page.locator(".status-line")).toContainText("请至少填写一项筛选条件");

  await page.getByLabel("根类目 ID").fill("172282, invalid");
  await page.getByRole("button", { name: "运行Product Finder" }).click();
  await expect(page.locator(".status-line")).toContainText("根类目 ID必须是用逗号分隔的正整数");

  await page.getByLabel("根类目 ID").fill("172282");
  await page.locator("details.advanced-options summary").click();
  await page.getByLabel("自定义筛选 JSON").fill("{");
  await page.getByRole("button", { name: "运行Product Finder" }).click();
  await expect(page.locator(".status-line")).toContainText("筛选条件不是有效 JSON");
  expect(requestCount).toBe(0);
});

for (const responseCase of [
  {
    name: "JSON 错误响应",
    response: async (route) => fulfillJson(route, 422, { error: { message: "参数组合不受支持" } }),
    message: "请求失败：参数组合不受支持",
  },
  {
    name: "意外 HTML 响应",
    response: async (route) => route.fulfill({ status: 502, contentType: "text/html", body: "<h1>Bad gateway</h1>" }),
    message: "接口地址返回了网页而不是 JSON",
  },
]) {
  test(`${responseCase.name}会显示可操作的失败提示`, async ({ page }) => {
    await page.route(API_URL, responseCase.response);
    await page.goto("/?variant=a");

    await page.getByRole("button", { name: "运行商品关键词搜索" }).click();

    await expect(page.locator(".status-line")).toContainText(responseCase.message);
    await expect(page.locator(".status-line")).toHaveAttribute("data-tone", "error");
  });
}

test("用户可以排序、筛选并切换三种结果视图", async ({ page }) => {
  await page.goto("/?variant=a");

  await page.getByRole("button", { name: "price ↕" }).click();
  await expect(page.locator("table tbody tr").first()).toContainText("Motion Sensor Night Light");
  await page.getByRole("button", { name: "price ↕" }).click();
  await expect(page.locator("table tbody tr").first()).toContainText("Rechargeable Work Light");

  await page.getByRole("button", { name: "原始" }).click();
  await expect(page.locator("pre.raw-json")).toContainText('"Rechargeable Work Light"');
  await page.getByRole("button", { name: "树形" }).click();
  await expect(page.locator("ul.tree").first()).toContainText("metrics");
  await page.getByRole("button", { name: "表格" }).click();

  await page.getByPlaceholder("筛选当前结果").fill("not-present");
  await expect(page.locator(".empty-state")).toContainText("没有匹配的数据");
  await expect(page.getByRole("button", { name: "下载 CSV" })).toHaveCount(0);
  await page.getByRole("button", { name: "载入样例" }).click();
  await expect(page.getByPlaceholder("筛选当前结果")).toHaveValue("");
  await expect(page.locator("table tbody tr")).toHaveCount(3);
});

test("布局切换按钮和键盘会同步 URL 与工作区", async ({ page }) => {
  await page.goto("/?variant=a");

  await page.getByTitle("下一个布局").click();
  await expect(page).toHaveURL(/\?variant=b$/);
  await expect(page.getByRole("heading", { name: "先看数据，再决定下一步。" })).toBeVisible();

  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/\?variant=c$/);
  await expect(page.getByRole("heading", { name: "数据检查器" })).toBeVisible();

  await page.keyboard.press("ArrowLeft");
  await page.getByTitle("上一个布局").click();
  await expect(page).toHaveURL(/\?variant=a$/);
  await expect(page.getByRole("heading", { name: "查询结果" })).toBeVisible();
});

test("场景切换会保留输入，并为不支持的场景回退巴西站点", async ({ page }) => {
  await page.goto("/?variant=a");
  await page.getByLabel("搜索关键词必填").fill("remember this query");
  await page.locator(".site-selector select").selectOption("BR");

  await page.getByLabel("查询场景").selectOption("seller-finder");
  await expect(page.locator(".site-selector select")).toHaveValue("US");
  await expect(page.locator('.site-selector option[value="BR"]')).toHaveAttribute("disabled", "");

  await page.getByLabel("查询场景").selectOption("product-search");
  await expect(page.getByLabel("搜索关键词必填")).toHaveValue("remember this query");
  await expect(page.locator('.site-selector option[value="BR"]')).not.toHaveAttribute("disabled", "");
});
