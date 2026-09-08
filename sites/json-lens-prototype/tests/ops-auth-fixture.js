export const CONFIG_URL = "http://127.0.0.1:4173/api/v1/mcp-api-keys/config";
export const OPERATION_TOKEN = "browser-operation-token";
export const MCP_API_KEY = "browser-mcp-api-key";

export async function installOpsAuthMocks(context, page) {
  await context.addCookies([{
    name: "polarisUserToken",
    value: "browser-session",
    url: "http://127.0.0.1:4173",
  }]);
  await page.addInitScript((token) => localStorage.setItem("OPERATION_TOKEN", token), OPERATION_TOKEN);
  await page.route(CONFIG_URL, (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    json: {
      success: true,
      data: {
        api: {
          apiKey: MCP_API_KEY,
          baseUrl: "http://127.0.0.1:8765",
          tokenType: "Bearer",
        },
      },
    },
  }));
}
