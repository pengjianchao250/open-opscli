import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.js",
  fullyParallel: true,
  forbidOnly: true,
  retries: 0,
  reporter: [
    ["line"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:4174",
    browserName: "chromium",
    colorScheme: "light",
    locale: "zh-CN",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:4174/",
    reuseExistingServer: true,
    timeout: 15_000,
  },
});
