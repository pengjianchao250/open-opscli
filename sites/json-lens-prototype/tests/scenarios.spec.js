import { expect, test } from "@playwright/test";

const API_URL = "http://127.0.0.1:8765/api/v1/keepa/run";

const scenarioCases = [
  {
    id: "product",
    title: "商品详情",
    prepare: async (page) => {
      await page.getByLabel("ASIN 或商品编码必填").fill("B0TESTPRODUCT");
    },
    params: { asin: "B0TESTPRODUCT", history: true, stats: 30 },
  },
  {
    id: "product-search",
    title: "商品关键词搜索",
    prepare: async (page) => {
      await page.getByLabel("搜索关键词必填").fill("usb c charger");
    },
    params: { keyword: "usb c charger" },
  },
  {
    id: "product-finder",
    title: "Product Finder",
    prepare: async (page) => {
      await page.getByLabel("标题包含").fill("rechargeable lamp");
    },
    params: { selection: { title: "rechargeable lamp", perPage: 50, page: 0 } },
  },
  {
    id: "category-search",
    title: "类目搜索",
    prepare: async (page) => {
      await page.getByLabel("类目关键词必填").fill("home office");
    },
    params: { keyword: "home office" },
  },
  {
    id: "category-lookup",
    title: "类目详情",
    prepare: async (page) => {
      await page.getByLabel("类目 ID必填").fill("172282");
    },
    params: { categories: "172282", parents: false },
  },
  {
    id: "seller",
    title: "卖家详情",
    prepare: async (page) => {
      await page.getByLabel("Seller ID必填").fill("A1TESTSELLER");
    },
    params: { sellers: "A1TESTSELLER", storefront: false },
  },
  {
    id: "seller-finder",
    title: "Seller Finder",
    prepare: async (page) => {
      await page.getByLabel("搜索关键词").fill("AUKEY");
    },
    params: { selection: { search: "AUKEY", perPage: 50, page: 0 } },
  },
  {
    id: "top-seller",
    title: "Top Sellers",
    params: {},
  },
  {
    id: "bestsellers",
    title: "Best Sellers",
    prepare: async (page) => {
      await page.getByLabel("类目 ID / Product Group必填").fill("172282");
    },
    params: { category: "172282" },
  },
  {
    id: "deals",
    title: "Deals",
    params: { selection: { priceTypes: [0] } },
  },
  {
    id: "lightning-deals",
    title: "Lightning Deals",
    params: {},
  },
];

async function mockSuccessfulRequest(page, scenarioId, capture) {
  await page.route(API_URL, async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await route.fallback();
      return;
    }
    capture(request.postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      json: {
        success: true,
        data: [{ scenario: scenarioId, result: `integration-${scenarioId}` }],
        error: null,
      },
    });
  });
}

for (const scenario of scenarioCases) {
  test(`${scenario.title} 可从页面提交正确请求并显示结果`, async ({ page }) => {
    let requestBody;
    await mockSuccessfulRequest(page, scenario.id, (body) => { requestBody = body; });
    await page.goto("/?variant=a");
    await page.getByLabel("查询场景").selectOption(scenario.id);
    await scenario.prepare?.(page);

    await page.getByRole("button", { name: `运行${scenario.title}` }).click();

    await expect(page.locator(".status-line")).toContainText("请求成功 · HTTP 200");
    await expect(page.getByRole("cell", { name: `integration-${scenario.id}`, exact: true })).toBeVisible();
    expect(requestBody).toEqual({
      scenario: scenario.id,
      site: "US",
      params: scenario.params,
      export_format: "json",
      wait: true,
    });
  });
}

test("必填业务参数为空时不会发送请求", async ({ page }) => {
  let requestCount = 0;
  await page.route(API_URL, async (route) => {
    requestCount += 1;
    await route.fulfill({ status: 200, contentType: "application/json", json: { data: [] } });
  });
  await page.goto("/?variant=a");
  await page.getByLabel("查询场景").selectOption("product");

  const identifier = page.getByLabel("ASIN 或商品编码必填");
  await page.getByRole("button", { name: "运行商品详情" }).click();

  expect(requestCount).toBe(0);
  expect(await identifier.evaluate((input) => input.validity.valueMissing)).toBe(true);
  await expect(identifier).toBeFocused();
});
