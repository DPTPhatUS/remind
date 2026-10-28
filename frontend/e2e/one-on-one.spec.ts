import { expect, test } from "@playwright/test";
import type { Fact, PersonMemory, VoiceStatus } from "../src/lib/api-types";

// This suite exercises the real UI and recording transport against deterministic
// API/WebSocket contract fixtures. It does not measure model accuracy.
test.use({
  launchOptions: {
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  },
  permissions: ["camera", "microphone"],
});

test("helper voice setup, automatic learning, return reminder, correction, and forget", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const errors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  const now = "2026-10-26T12:00:00Z";
  let voice: VoiceStatus = {
    ready: false,
    reference_saved: false,
    model_available: true,
    error: null,
    version: 0,
    model: null,
    sample_count: 0,
    updated_at: null,
  };
  let person: PersonMemory | null = {
    id: "anna",
    name: null,
    relationship: null,
    age: null,
    notes: null,
    version: 0,
    created_at: now,
    profile_summary: null,
    highlights: [],
    last_encounter: null,
    encounters: [],
    facts: [],
  };
  let session = 0;
  let faceMode: "visible" | "absent" | "multiple" | "replacement" | "stale" = "visible";
  let learned = false;
  let samplesReceived = 0;
  const fact = (id: string, overrides: Partial<Fact>): Fact => ({
    id,
    subject: "visitor",
    category: "interests",
    predicate: "enjoys",
    value: "Gardening",
    temporal_status: "current",
    valid_from: null,
    valid_to: null,
    status: "accepted",
    manual: false,
    evidence: [{ segment_id: "s1", quote: "I love gardening." }],
    created_at: now,
    updated_at: now,
    ...overrides,
  });

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    const pathname = url.pathname;
    let response: unknown = {};
    if (pathname === "/api/user/voice") {
      if (method === "POST") {
        const body = route.request().postDataJSON();
        expect(body.samples).toHaveLength(3);
        expect(
          body.samples.every(
            (sample: string) =>
              sample.length > 0 && !sample.startsWith("data:"),
          ),
        ).toBe(true);
        samplesReceived = body.samples.length;
        voice = {
          ready: true,
          reference_saved: true,
          model_available: true,
          error: null,
          version: voice.version + 1,
          model: "fixture-ecapa",
          sample_count: 3,
          updated_at: now,
        };
      } else if (method === "DELETE")
        voice = {
          ready: false,
          reference_saved: false,
          model_available: true,
          error: null,
          version: voice.version + 1,
          model: null,
          sample_count: 0,
          updated_at: null,
        };
      response = voice;
    } else if (pathname === "/api/session") {
      session++;
      response = {
        generation: `fixture-${session}`,
        memory_available: true,
        voice_ready: voice.ready,
        profile_learning_available: voice.ready,
      };
    } else if (pathname.endsWith("/stop")) {
      if (person && learned) {
        const encounter = {
          id: "encounter-1",
          started_at: now,
          ended_at: now,
          summary: "You talked about Anna’s garden and her brother’s teaching.",
        };
        person.encounters = [encounter];
        person.last_encounter = encounter;
      }
    } else if (pathname.includes("/clips")) {
      if (person && voice.ready) {
        learned = true;
        person.name = "Anna";
        person.relationship = "Daughter";
        person.version++;
        person.profile_summary =
          "Anna is your daughter. She enjoys gardening and cooking.";
        person.highlights = [
          "Enjoys gardening",
          "Enjoys cooking",
          "Works at the primary school",
          "This fourth highlight should stay out of live view",
        ];
        person.facts = [
          fact("gardening", {}),
          fact("cooking", {
            value: "Cooking",
            evidence: [{ segment_id: "s2", quote: "I enjoy cooking too." }],
          }),
          fact("brother", {
            subject: "related:brother",
            category: "work",
            predicate: "occupation",
            value: "Teacher",
            evidence: [{ segment_id: "s3", quote: "My brother teaches." }],
          }),
          fact("old-job", {
            category: "work",
            predicate: "occupation",
            value: "Bank teller",
            temporal_status: "past",
            evidence: [
              { segment_id: "s4", quote: "I used to work at a bank." },
            ],
          }),
          fact("visit", {
            category: "plans",
            predicate: "visit",
            value: "Visit on Friday",
            temporal_status: "planned",
            valid_from: "2026-10-30",
            evidence: [{ segment_id: "s5", quote: "I will visit on Friday." }],
          }),
          fact("conflict", {
            category: "identity",
            predicate: "name",
            value: "Anne",
            status: "conflict",
            evidence: [{ segment_id: "s6", quote: "My name is Anne." }],
          }),
        ];
      }
      response = { clip_id: "fixture-clip", status: "transcribing" };
    } else if (pathname === "/api/jobs") response = [];
    else if (pathname === "/api/people") response = person ? [person] : [];
    else if (pathname.endsWith("/thumbnail")) {
      await route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="70" height="70"><rect width="70" height="70" fill="#c1d2b7"/></svg>',
      });
      return;
    } else if (pathname.includes("/facts/")) {
      const target = person?.facts.find(
        (item) => item.id === pathname.split("/").pop(),
      );
      expect(route.request().postDataJSON().version).toBe(person?.version);
      if (person && target) {
        if (method === "PATCH") {
          target.value = route.request().postDataJSON().value;
          target.manual = true;
          target.updated_at = "2026-10-26T12:01:00Z";
        } else target.status = "dismissed";
        person.version++;
      }
      response = person;
    } else if (pathname === "/api/people/anna") {
      if (method === "DELETE") person = null;
      response = person ?? {};
    }
    await route.fulfill({ status: 200, json: response });
  });
  await page.routeWebSocket("**/api/live/*/vision", (socket) => {
    socket.onMessage((data) => {
      if (faceMode === "stale") return;
      const bytes = Buffer.isBuffer(data) ? data : Buffer.from(data);
      const headerLength = bytes.readUInt32BE(0);
      const header = JSON.parse(bytes.subarray(4, 4 + headerLength).toString());
      socket.send(
        JSON.stringify({
          type: "vision",
          generation: header.generation,
          sequence: header.sequence,
          capture_ms: header.capture_ms,
          detections: faceMode === "absent" ? [] : faceMode === "multiple"
            ? [{ box: [0.3, 0.3, 0.25, 0.4], quality: true }, { box: [0.7, 0.3, 0.2, 0.3], quality: false }]
            : [{ box: [0.3, 0.3, 0.25, 0.4], quality: true }],
          candidate: faceMode === "visible" && person ? {
            id: "candidate-1", person_id: person.id, box: [0.3, 0.3, 0.25, 0.4],
            confirmed: true, quality: true,
          } : faceMode === "replacement" ? {
            id: "candidate-2", person_id: null, box: [0.7, 0.3, 0.2, 0.3],
            confirmed: false, quality: true,
          } : null,
          encounter: {
            id: person ? "encounter-1" : null, visitor_id: person?.id ?? null,
            state: faceMode === "absent" ? "absent" : (faceMode === "multiple" || faceMode === "replacement") ? "paused" : "confirmed",
            learning_available: faceMode !== "multiple" && faceMode !== "replacement", reason: faceMode === "absent" ? "absence_allowance"
              : faceMode === "multiple" ? "multiple_faces" : faceMode === "replacement" ? "new_candidate" : "direct_confirmation",
            absence_deadline_ms: header.capture_ms + 5000, memory: person,
          },
          processing_ms: 10,
          processed_fps: 15,
          dropped: 0,
        }),
      );
    });
  });

  await page.goto("/");
  await expect(page).toHaveTitle(/Remind/);
  await expect(
    page.getByText(/Personal details learning is paused/),
  ).toBeVisible();
  await page.getByRole("link", { name: "Voice setup", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Set up the user’s voice" }),
  ).toBeVisible();
  for (let index = 1; index <= 3; index++) {
    await page
      .getByRole("button", { name: `Record sample ${index}`, exact: true })
      .click();
    await expect(page.getByText(/Recording…/)).toBeVisible();
    await expect(
      page.getByRole("button", { name: `Retake sample ${index}`, exact: true }),
    ).toBeEnabled({ timeout: 12_000 });
  }
  await page.getByRole("button", { name: "Save user’s voice" }).click();
  await expect(
    page.getByText("User’s voice is ready", { exact: true }),
  ).toBeVisible();
  expect(samplesReceived).toBe(3);
  await page.screenshot({
    path: "/tmp/remind-voice-setup.png",
    fullPage: true,
  });
  await page.getByRole("link", { name: "Live view" }).click();
  await expect(
    page.getByText(/Personal details learning is paused/),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator(".face-card strong")).toHaveText(
    "Someone you’ve met",
  );
  await expect(page.locator(".face-card strong")).toHaveText("Anna", {
    timeout: 15_000,
  });
  await expect(page.locator(".face-card .face-highlights li")).toHaveCount(3);
  await expect(page.locator(".face-card")).not.toContainText("Bank teller");
  await expect(page.locator(".face-card")).not.toContainText("Anne");
  faceMode = "absent";
  await expect(page.locator(".face-card")).toContainText("Temporarily out of view");
  await expect(page.locator(".face-box")).toHaveCount(0);
  await expect(page.locator(".face-card strong")).toHaveText("Anna");
  await page.screenshot({ path: "/tmp/remind-absence.png" });
  faceMode = "multiple";
  await expect(page.locator(".face-card")).toContainText("Personal details learning is paused");
  await expect(page.locator(".face-box")).toHaveCount(2);
  faceMode = "replacement";
  await expect(page.locator(".face-box")).toHaveCount(1);
  await expect(page.locator(".face-card")).toContainText("Personal details learning is paused");
  await expect(page.locator(".face-card")).toHaveCSS("left", "12px");
  faceMode = "visible";
  await expect(page.locator(".face-box")).toHaveCount(1);
  faceMode = "stale";
  await expect(page.locator(".face-card")).toContainText("Personal details learning is paused");
  await expect(page.locator(".face-card")).toHaveCount(0, { timeout: 7000 });
  faceMode = "visible";
  await expect(page.locator(".face-card strong")).toHaveText("Anna");

  await page.getByRole("button", { name: "Stop camera" }).click();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await page.reload();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.locator(".face-card strong")).toHaveText("Anna");
  await expect(page.locator(".face-card")).toContainText("Last met");
  const stage = await page.locator(".camera-frame").boundingBox();
  const reminder = await page.locator(".face-card").boundingBox();
  expect(reminder!.y).toBeGreaterThanOrEqual(stage!.y);
  expect(reminder!.y + reminder!.height).toBeLessThanOrEqual(
    stage!.y + stage!.height,
  );
  await page.screenshot({ path: "/tmp/remind-one-on-one-live.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".mobile-reminders")).toContainText("Last met");
  await expect(
    page.locator(".mobile-reminders .face-highlights li"),
  ).toHaveCount(3);
  await page.screenshot({
    path: "/tmp/remind-one-on-one-live-mobile.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole("button", { name: "Stop camera" }).click();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await page.getByRole("link", { name: "People", exact: true }).click();
  await page.getByRole("link", { name: /Anna/ }).click();
  await expect(
    page.getByRole("heading", { name: "Related people" }),
  ).toBeVisible();
  await expect(page.getByText("Teacher", { exact: true })).toBeVisible();
  await expect(page.getByText("Bank teller", { exact: true })).toBeVisible();
  await page.getByText("Unresolved information (1)").click();
  await expect(page.getByText("Anne", { exact: true })).toBeVisible();
  const gardening = page
    .locator("details.fact")
    .filter({ has: page.locator(".fact-value", { hasText: /^Gardening$/ }) });
  await gardening.locator("summary").click();
  await expect(gardening.getByText("“I love gardening.”")).toBeVisible();
  await gardening.getByRole("button", { name: "Correct fact" }).click();
  await gardening.getByLabel("Correct enjoys").fill("Vegetable gardening");
  await gardening.getByRole("button", { name: "Save fact correction" }).click();
  await expect(
    page.getByText("Vegetable gardening", { exact: true }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "/tmp/remind-one-on-one-profile-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Forget this person" }).click();
  await expect(
    page.getByText("Your memories start with a hello."),
  ).toBeVisible();
  await page.getByRole("link", { name: "Voice setup", exact: true }).click();
  await page.getByRole("button", { name: "Remove saved voice" }).click();
  await expect(
    page.getByText("User’s voice has not been set up", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
