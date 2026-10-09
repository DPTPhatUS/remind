import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    channel: "chromium",
  },
  reporter: "list",
});
