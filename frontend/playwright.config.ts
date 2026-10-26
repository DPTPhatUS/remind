import { defineConfig } from "@playwright/test";
import path from "node:path";

const frontendUrl = "http://127.0.0.1:15173";
const backendUrl = "http://127.0.0.1:18000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  workers: 1,
  use: {
    baseURL: frontendUrl,
    headless: true,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "chromium",
  },
  webServer: [
    {
      command: ".venv/bin/python -m uvicorn remind.app:app --host 127.0.0.1 --port 18000",
      cwd: path.resolve(import.meta.dirname, "../backend"),
      url: `${backendUrl}/api/health`,
      env: {
        REMIND_DATA_DIR: ".local/e2e",
        REMIND_OPENAI_API_KEY: "",
        REMIND_ORIGINS: JSON.stringify([frontendUrl]),
      },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 15173 --strictPort",
      url: frontendUrl,
      env: { REMIND_API_URL: backendUrl },
      reuseExistingServer: false,
    },
  ],
  reporter: "list",
});
