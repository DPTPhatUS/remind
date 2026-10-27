import { test, expect } from "@playwright/test";
import path from "node:path";

test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-video-capture=${path.resolve("../backend/.local/e2e/camera.y4m")}`,
    ],
  },
  permissions: ["camera", "microphone"],
});

test.beforeEach(async ({ request }) => {
  // The Playwright configuration uses an isolated store for this invocation.
  const people = await (await request.get("/api/people")).json();
  for (const person of people) await request.delete(`/api/people/${person.id}`);
});

test("enroll, correct, stop, return, and forget a face", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/");
  await expect(page).toHaveTitle(/Remind/);
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator(".face-box.known")).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".face-card strong")).toHaveText("Someone you’ve met");
  await page.screenshot({ path: "/tmp/remind-live.png" });
  await page.getByRole("button", { name: "Stop camera" }).click();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await page.getByRole("link", { name: "People", exact: true }).click();
  await page
    .getByRole("link", { name: /Name not learned yet/ })
    .first()
    .click();
  await page.getByText("Correct profile details", { exact: true }).click();
  await page.getByLabel("name", { exact: true }).fill("Anna");
  await page.getByLabel("relationship", { exact: true }).fill("Daughter");
  await page.getByRole("button", { name: "Save corrections" }).click();
  await expect(
    page.getByRole("heading", { name: "Anna", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Live view" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator(".face-card strong")).toHaveText("Anna", {
    timeout: 15000,
  });
  await expect(page.locator(".face-card")).toContainText("Last met");
  await page.screenshot({ path: "/tmp/remind-return.png" });
  await page.getByRole("button", { name: "Stop camera" }).click();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "/tmp/remind-mobile.png" });
  const people = await (await request.get("/api/people")).json();
  for (const person of people) await request.delete(`/api/people/${person.id}`);
  expect(errors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
