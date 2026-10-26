import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useLiveSession } from "./session";

const { recordClips, captureFrames } = vi.hoisted(() => ({
  recordClips: vi.fn(),
  captureFrames: vi.fn(() => vi.fn()),
}));
vi.mock("./audio", () => ({ recordClips }));
vi.mock("./capture", () => ({ captureFrames }));

afterEach(() => vi.unstubAllGlobals());

it("clears the upload pause when a stopped session's retained clip is retried", async () => {
  let updatePaused: (paused: boolean) => void = () => {};
  const clips = {
    stop: vi.fn(async () => {}),
    retry: vi.fn(async () => { updatePaused(false); }),
    download: vi.fn(),
  };
  recordClips.mockImplementation((_stream, _generation, _onStatus, onPaused) => {
    updatePaused = onPaused;
    return clips;
  });
  class Socket {
    static latest: Socket;
    onopen: (() => void) | null = null;
    close = vi.fn();
    constructor() { Socket.latest = this; }
  }
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("fetch", vi.fn(async (path) => ({
    ok: true,
    json: async () => {
      if (path === "/api/session") {
        return {
          generation: "generation",
          memory_available: true,
          voice_ready: true,
          profile_learning_available: true,
        };
      }
      return path === "/api/user/voice" ? { ready: true } : [];
    },
  })));
  const stopTrack = vi.fn();
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [{ stop: stopTrack }],
      })),
    },
  });
  const video = document.createElement("video");
  vi.spyOn(video, "play").mockResolvedValue();
  const { result } = renderHook(useLiveSession);
  await waitFor(() => expect(result.current.voiceReady).toBe(true));
  await act(async () => {
    result.current.attachVideo(video);
    await result.current.start();
  });
  act(() => {
    Socket.latest.onopen?.();
    updatePaused(true);
  });
  expect(result.current.uploadPaused).toBe(true);
  await act(async () => { await result.current.stop(); });
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(result.current.status).toBe("idle");
  await act(async () => { await result.current.retryUpload(); });
  expect(clips.retry).toHaveBeenCalledOnce();
  expect(result.current.uploadPaused).toBe(false);
});
