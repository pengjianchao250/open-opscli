import { expect, test } from "@playwright/test";

const API_BASE = "http://127.0.0.1:8765/api/v1/seller-sprite";
const CONFIG_URL = "http://127.0.0.1:4174/api/v1/mcp-api-keys/config";
const OPERATION_TOKEN = "browser-operation-token";
const MCP_API_KEY = "browser-mcp-api-key";

async function fulfill(route, status, json) {
  await route.fulfill({ status, contentType: "application/json", json });
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{
    name: "polarisUserToken",
    value: "browser-session",
    url: "http://127.0.0.1:4174",
  }]);
  await page.addInitScript((token) => localStorage.setItem("OPERATION_TOKEN", token), OPERATION_TOKEN);
  await page.route(CONFIG_URL, (route) => fulfill(route, 200, {
    success: true,
    data: {
      api: {
        apiKey: MCP_API_KEY,
        baseUrl: "http://127.0.0.1:8765",
        tokenType: "Bearer",
      },
    },
  }));
});

function completedResult(jobId = "web-keyword-reverse-test") {
  return {
    success: true,
    data: {
      job_id: jobId,
      scenario: "keyword-reverse",
      site: "US",
      period: "30d",
      state: "succeeded",
      stage: "finished",
      row_count: 2,
      result: {
        schema_version: "2.0",
        sheet_name: "Keywords",
        columns: ["关键词", "流量占比", "月搜索量"],
        number_formats: [null, "0.00%", "#,##0"],
        rows: [["usb c charger", 0.12, 52000], ["phone charger", 0.08, 91000]],
        additional_sheets: [{
          name: "Unique Words",
          columns: ["词根", "频次"],
          number_formats: [null, "#,##0"],
          rows: [["charger", 2]],
        }],
      },
    },
    error: null,
  };
}

test("关键词反查提交 JSON 任务并显示 JSON v2 工作表", async ({ page }) => {
  let requestBody;
  let authorization;
  await page.route(`${API_BASE}/jobs`, async (route) => {
    requestBody = route.request().postDataJSON();
    authorization = route.request().headers().authorization;
    await fulfill(route, 202, {
      success: true,
      data: { job_id: requestBody.job_id, state: "queued", stage: "queued", position: 1 },
      error: null,
      quota: { limit: 5, remaining: 4 },
    });
  });
  await page.route(`${API_BASE}/jobs/*/result?*`, async (route) => {
    await fulfill(route, 200, completedResult(route.request().url().split("/jobs/")[1].split("/")[0]));
  });
  await page.goto("/");
  await page.getByLabel("ASIN必填").fill("B012345678");

  const configRequestPromise = page.waitForRequest(CONFIG_URL);
  await page.getByRole("button", { name: "提交 JSON 任务" }).click();
  const configRequest = await configRequestPromise;

  await expect(page.locator(".status-message")).toContainText("任务完成");
  await expect(page.getByRole("cell", { name: "usb c charger" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Unique Words/ })).toBeVisible();
  expect(configRequest.headers().authorization).toBe(`Bearer ${OPERATION_TOKEN}`);
  expect(configRequest.headers().cookie).toContain("polarisUserToken=browser-session");
  expect(authorization).toBe(`Bearer ${MCP_API_KEY}`);
  expect(requestBody).toMatchObject({
    scenario: "keyword-reverse",
    params: { asin: "B012345678", includeHighFrequency: true },
    site: "US",
    period: "30d",
    page_size: 100,
    export_format: "json",
  });
  expect(requestBody.job_id).toMatch(/^web-keyword-reverse-/);
});

test("选产品周期提供最近30天和动态历史月份", async ({ page }) => {
  let requestBody;
  await page.route(`${API_BASE}/jobs`, async (route) => {
    requestBody = route.request().postDataJSON();
    await fulfill(route, 202, { success: true, data: { job_id: requestBody.job_id, state: "queued" }, error: null });
  });
  await page.route(`${API_BASE}/jobs/*/result?*`, (route) => fulfill(route, 202, { success: true, data: { state: "queued", ready: false }, error: null }));
  await page.goto("/");
  await page.getByRole("button", { name: /选产品/ }).click();

  const period = page.getByLabel("月份必填");
  const values = await period.locator("option").evaluateAll((options) => options.map((option) => option.value));
  expect(values[0]).toBe("30d");
  expect(await period.locator("option").first().innerText()).toBe("最近30天");
  expect(values[1]).toMatch(/^\d{4}-\d{2}$/);
  expect(values).toHaveLength(26);

  await period.selectOption(values[1]);
  await page.getByRole("button", { name: "提交 JSON 任务" }).click();
  expect(requestBody.period).toBe(values[1]);
});

test("复用 DaisyUI 组件并保留桌面场景侧边栏", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "corporate");
  await expect(page.locator(".request-panel")).toHaveClass(/card/);
  await expect(page.getByRole("button", { name: "提交 JSON 任务" })).toHaveClass(/btn-primary/);
  await expect(page.getByLabel("站点必填")).toHaveClass(/select-bordered/);
  await expect(page.locator(".sidebar")).toBeVisible();

  const sidebarWidth = await page.locator(".sidebar").evaluate((element) => element.getBoundingClientRect().width);
  expect(sidebarWidth).toBe(248);

  await page.getByLabel("暗色").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "business");
});

test("排队任务可以手动续查且不会重新提交", async ({ page }) => {
  let submitCount = 0;
  let resultCount = 0;
  await page.route(`${API_BASE}/jobs`, async (route) => {
    submitCount += 1;
    const body = route.request().postDataJSON();
    await fulfill(route, 202, { success: true, data: { job_id: body.job_id, state: "queued", stage: "queued" }, error: null });
  });
  await page.route(`${API_BASE}/jobs/*/result?*`, async (route) => {
    resultCount += 1;
    if (resultCount === 1) {
      await fulfill(route, 202, { success: true, data: { job_id: "job-pending", state: "running", stage: "collect", ready: false }, error: null });
      return;
    }
    await fulfill(route, 200, completedResult("job-pending"));
  });
  await page.goto("/");
  await page.getByLabel("ASIN必填").fill("B012345678");
  await page.getByRole("button", { name: "提交 JSON 任务" }).click();
  await expect(page.locator(".status-message")).toContainText("执行中");

  await page.getByRole("button", { name: "刷新状态" }).click();

  await expect(page.locator(".status-message")).toContainText("任务完成");
  expect(submitCount).toBe(1);
  expect(resultCount).toBe(2);
});

test("连接检查读取服务端场景和额度", async ({ page }) => {
  await page.route(`${API_BASE}/scenarios`, (route) => fulfill(route, 200, { success: true, data: [{ scenario_id: "keyword-reverse" }, { scenario_id: "product-research" }], error: null }));
  await page.route(`${API_BASE}/quota`, (route) => fulfill(route, 200, { success: true, data: { limit: 5, remaining: 3 }, error: null }));
  await page.goto("/");
  await page.locator("details.connection summary").click();

  await page.getByRole("button", { name: "验证连接" }).click();

  await expect(page.locator(".status-message")).toContainText("服务端开放 2 个场景");
  await expect(page.locator(".quota")).toContainText("3 / 5");
});

test("MCP API Key 不写入 localStorage，任务编号可在刷新后恢复", async ({ page }) => {
  await page.route(`${API_BASE}/jobs`, async (route) => {
    const body = route.request().postDataJSON();
    await fulfill(route, 202, { success: true, data: { job_id: body.job_id, state: "queued" }, error: null });
  });
  await page.route(`${API_BASE}/jobs/*/result?*`, (route) => fulfill(route, 202, { success: true, data: { job_id: "pending", state: "queued", ready: false }, error: null }));
  await page.goto("/");
  await page.getByLabel("ASIN必填").fill("B012345678");
  await page.getByRole("button", { name: "提交 JSON 任务" }).click();
  await expect(page.locator(".job-item")).toHaveCount(1);
  const stored = await page.evaluate(() => JSON.stringify(localStorage));
  expect(stored).toContain(OPERATION_TOKEN);
  expect(stored).not.toContain(MCP_API_KEY);

  await page.reload();

  await expect(page.locator(".job-item")).toHaveCount(1);
  await expect(page.locator(".job-item")).toContainText("关键词反查");
  await page.locator("details.connection summary").click();
  await expect(page.getByLabel("MCP API 地址")).toHaveValue("");
  await expect(page.getByLabel("API Key")).toHaveCount(0);
});

test("结果支持筛选、排序、辅助工作表和原始 JSON", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("筛选当前工作表").fill("phone");
  await expect(page.locator("table tbody tr")).toHaveCount(1);
  await expect(page.getByRole("cell", { name: "phone charger" })).toBeVisible();
  await page.getByRole("button", { name: /Unique Words/ }).click();
  await expect(page.getByRole("cell", { name: "charger" })).toBeVisible();
  await page.getByRole("button", { name: "原始" }).click();
  await expect(page.locator(".raw-json")).toContainText('"schema_version": "2.0"');
});

test("移动端表单和场景导航不会重叠", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "打开场景导航" }).click();
  await expect(page.locator(".sidebar")).toHaveClass(/open/);
  await page.getByRole("button", { name: /关键词挖掘/ }).click();
  await expect(page.locator(".sidebar")).not.toHaveClass(/open/);
  await expect(page.getByRole("heading", { name: "关键词挖掘", exact: true })).toBeVisible();
  await expect(page.getByLabel("核心关键词必填")).toBeVisible();
});
