import { defineConfig } from "@playwright/test";
import path from "node:path";
import { lstatSync, mkdirSync, mkdtempSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";

const frontendUrl = "http://127.0.0.1:15173";
const backendUrl = "http://127.0.0.1:18000";
// One isolated store per test invocation, shared by its server and workers.
const dataDirectory = process.env.REMIND_E2E_DATA_DIR
  ? path.resolve(process.env.REMIND_E2E_DATA_DIR)
  : mkdtempSync(path.join(tmpdir(), "remind-e2e-"));
process.env.REMIND_E2E_DATA_DIR = dataDirectory;
mkdirSync(dataDirectory, { recursive: true });
const modelsLink = path.join(dataDirectory, "models");
if (!lstatSync(modelsLink, { throwIfNoEntry: false })) {
  symlinkSync(path.resolve(import.meta.dirname, "../backend/.local/models"), modelsLink, "dir");
}

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
        REMIND_DATA_DIR: dataDirectory,
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
