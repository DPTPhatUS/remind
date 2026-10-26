import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SetupPage } from "./SetupPage";

const noVoice = {
  ready: false,
  version: 0,
  model: null,
  sample_count: 0,
  updated_at: null,
};
const savedVoice = {
  ready: true,
  version: 1,
  model: "ecapa-test",
  sample_count: 3,
  updated_at: "2026-10-26T12:00:00Z",
};

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function recorders() {
  const stopTrack = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi
        .fn()
        .mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }),
    },
  });
  vi.stubGlobal(
    "MediaRecorder",
    class {
      static isTypeSupported() {
        return true;
      }
      state = "inactive";
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() {
        this.state = "recording";
      }
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({
          data: new Blob(["voice bytes"], { type: "audio/webm" }),
        });
        this.onstop?.();
      }
    },
  );
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn(() => "blob:voice-test"),
    revokeObjectURL: vi.fn(),
  });
  return stopTrack;
}

it("records three samples, submits raw base64, and removes the saved voice", async () => {
  const stopTrack = recorders();
  const fetcher = vi.fn().mockImplementation(async (_path, options) => ({
    ok: true,
    json: async () => (options?.method === "POST" ? savedVoice : noVoice),
  }));
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<SetupPage />);
  await screen.findByText("User’s voice has not been set up");
  expect(
    screen.getByRole("button", { name: "Save user’s voice" }),
  ).toBeDisabled();
  vi.useFakeTimers();
  for (let index = 1; index <= 3; index++) {
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: `Record sample ${index}` }),
      );
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Recording… 8 seconds left",
    );
    await act(async () => {
      vi.advanceTimersByTime(8000);
    });
    expect(
      screen.getByRole("button", { name: `Retake sample ${index}` }),
    ).toBeEnabled();
  }
  expect(stopTrack).toHaveBeenCalledTimes(3);
  vi.useRealTimers();
  fireEvent.click(screen.getByRole("button", { name: "Save user’s voice" }));
  await screen.findByText("User’s voice is ready");
  const submission = fetcher.mock.calls.find(
    ([, options]) => options?.method === "POST",
  );
  expect(submission?.[0]).toBe("/api/user/voice");
  expect(JSON.parse(submission?.[1].body).samples).toEqual([
    "dm9pY2UgYnl0ZXM=",
    "dm9pY2UgYnl0ZXM=",
    "dm9pY2UgYnl0ZXM=",
  ]);
  fireEvent.click(screen.getByRole("button", { name: "Remove saved voice" }));
  await screen.findByText("User’s voice has not been set up");
  expect(fetcher).toHaveBeenCalledWith(
    "/api/user/voice",
    expect.objectContaining({ method: "DELETE" }),
  );
});

it("stops a late microphone response when the helper leaves setup", async () => {
  let finish: (stream: unknown) => void = () => {};
  const stopTrack = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      ),
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => noVoice }),
  );
  const { unmount } = render(<SetupPage />);
  await screen.findByText("User’s voice has not been set up");
  fireEvent.click(screen.getByRole("button", { name: "Record sample 1" }));
  unmount();
  await act(async () => {
    finish({ getTracks: () => [{ stop: stopTrack }] });
  });
  expect(stopTrack).toHaveBeenCalledOnce();
});

it("keeps setup usable after microphone permission is denied", async () => {
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi
        .fn()
        .mockRejectedValue(new Error("Microphone permission denied")),
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => noVoice }),
  );
  render(<SetupPage />);
  await screen.findByText("User’s voice has not been set up");
  fireEvent.click(screen.getByRole("button", { name: "Record sample 1" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Microphone permission denied",
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Record sample 1" }),
    ).toBeEnabled(),
  );
});

it("retains removal controls when a saved reference cannot currently be used", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...savedVoice,
        ready: false,
        reference_saved: true,
        model_available: false,
        error: "Missing ECAPA assets",
      }),
    }),
  );
  render(<SetupPage />);
  await screen.findByText("Saved voice is temporarily unavailable");
  expect(
    screen.getByRole("button", { name: "Remove saved voice" }),
  ).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "Record sample 1" }),
  ).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent(
    "saved voice reference is retained",
  );
});
