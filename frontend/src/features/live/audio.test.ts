import { afterEach, expect, it, vi } from "vitest";
import { recordClips, uploadClip } from "./audio";
import { downloadFile } from "@/lib/download";

vi.mock("@/lib/download", () => ({ downloadFile: vi.fn() }));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("retains the clip and retries a transient upload failure", async () => {
  const send = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Unavailable" }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "queued" }),
    });
  const result = await uploadClip(
    "session",
    "metadata",
    new Blob(["media"]),
    send,
    async () => {},
  );
  expect(result.status).toBe("queued");
  expect(send).toHaveBeenCalledTimes(2);
});
it("treats full storage as a recording pause", async () => {
  const send = vi
    .fn()
    .mockResolvedValue({
      ok: false,
      status: 507,
      json: async () => ({ detail: "Storage full" }),
    });
  await expect(
    uploadClip(
      "session",
      "metadata",
      new Blob(["media"]),
      send,
      async () => {},
    ),
  ).rejects.toThrow("Storage full");
  expect(send).toHaveBeenCalledTimes(1);
});

function startRecording(send: ReturnType<typeof vi.fn>) {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", send);
  vi.stubGlobal("MediaRecorder", class {
    static isTypeSupported() {
      return true;
    }
    state = "inactive";
    onstart: (() => void) | null = null;
    ondataavailable: ((event: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    start() {
      this.state = "recording";
      this.onstart?.();
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["conversation"]) });
      this.onstop?.();
    }
  });
  const onStatus = vi.fn();
  const onPaused = vi.fn();
  const recording = recordClips(
    {} as MediaStream, "session", onStatus, onPaused,
  );
  return { recording, onStatus, onPaused };
}

it("retries a retained clip after recording has stopped without duplicate requests", async () => {
  let finishUpload: (response: unknown) => void = () => {};
  const send = vi.fn()
    .mockResolvedValueOnce({
      ok: false, status: 507, json: async () => ({ detail: "Storage full" }),
    })
    .mockImplementationOnce(() => new Promise((resolve) => {
      finishUpload = resolve;
    }));
  const { recording, onPaused } = startRecording(send);
  await vi.advanceTimersByTimeAsync(8000);
  expect(onPaused).toHaveBeenLastCalledWith(true);
  await recording.stop();
  const firstRetry = recording.retry();
  const secondRetry = recording.retry();
  expect(send).toHaveBeenCalledTimes(2);
  finishUpload({ ok: true, json: async () => ({ status: "queued" }) });
  await Promise.all([firstRetry, secondRetry]);
  expect(onPaused).toHaveBeenLastCalledWith(false);
});

it("releases a downloaded retained clip so it cannot be silently retried", async () => {
  const send = vi.fn().mockResolvedValue({
    ok: false, status: 507, json: async () => ({ detail: "Storage full" }),
  });
  const { recording, onPaused, onStatus } = startRecording(send);
  await vi.advanceTimersByTimeAsync(8000);
  await recording.stop();
  recording.download();
  expect(downloadFile).toHaveBeenCalledWith(
    expect.any(Blob), "remind-unsaved-conversation.webm",
  );
  expect(onPaused).toHaveBeenLastCalledWith(false);
  expect(onStatus).toHaveBeenLastCalledWith(
    "Conversation downloaded. This clip has not been added to memory.",
  );
  await recording.retry();
  expect(send).toHaveBeenCalledTimes(1);
});
