const { randomUUID } = require("node:crypto");
const { defineConfig } = require("@playwright/test");

const port = 8767;
const origin = "http://127.0.0.1:" + port;
const python = process.platform === "win32" ? "python" : "python3";
const database = ".data/browser-tests/" + randomUUID() + ".sqlite3";

module.exports = defineConfig({
  testDir: "./tests/browser",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: "list",
  use: {
    baseURL: origin,
    browserName: "chromium",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `${python} -m job_workspace --port ${port} --db ${database}`,
    url: origin + "/api/jobs",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
