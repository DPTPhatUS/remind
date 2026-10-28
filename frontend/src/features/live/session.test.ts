import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { VisionMessage } from "@/lib/api-types";
import { useLiveSession } from "./session";

const { recordClips, captureFrames } = vi.hoisted(() => ({
  recordClips: vi.fn(),
  captureFrames: vi.fn(),
}));
vi.mock("./audio", () => ({ recordClips }));
vi.mock("./capture", () => ({ captureFrames }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}

function response(data: unknown) {
  return { ok: true, json: async () => data };
}

class Socket {
  static latest: Socket;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn();
  constructor() { Socket.latest = this; }
}

const session = {
  generation: "generation",
  memory_available: true,
  voice_ready: true,
  profile_learning_available: true,
};
const stopTrack = vi.fn();
const stream = { getTracks: () => [{ stop: stopTrack }] };
const stopFrames = vi.fn();
const getUserMedia = vi.fn();
const send = vi.fn();
let updatePaused: (paused: boolean) => void;
let updateMemoryStatus: (message: string) => void;
let clips: { stop: ReturnType<typeof vi.fn>; retry: ReturnType<typeof vi.fn>; download: ReturnType<typeof vi.fn> };

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  getUserMedia.mockResolvedValue(stream);
  send.mockImplementation(async (path) => response(
    path === "/api/session" ? session : path === "/api/user/voice" ? { ready: true } : [],
  ));
  vi.stubGlobal("fetch", send);
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  clips = {
    stop: vi.fn(async () => {}),
    retry: vi.fn(async () => { updatePaused(false); }),
    download: vi.fn(),
  };
  captureFrames.mockReturnValue(stopFrames);
  recordClips.mockImplementation((_stream, _generation, onStatus, onPaused) => {
    updateMemoryStatus = onStatus;
    updatePaused = onPaused;
    return clips;
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function mountSession() {
  const hook = renderHook(useLiveSession);
  const video = document.createElement("video");
  vi.spyOn(video, "play").mockResolvedValue();
  await act(async () => { hook.result.current.attachVideo(video); });
  return { ...hook, video };
}

async function startSession() {
  const hook = await mountSession();
  await act(async () => { await hook.result.current.start(); });
  act(() => { Socket.latest.onopen?.(); });
  return hook;
}

function visionMessage(): VisionMessage {
  return {
    type: "vision", generation: session.generation, sequence: 1,
    capture_ms: performance.now(), processing_ms: 10, processed_fps: 10, dropped: 0,
    detections: [{ box: [0.1, 0.1, 0.5, 0.5], quality: true }],
    candidate: null,
    encounter: {
      id: "encounter", visitor_id: "visitor", state: "confirmed",
      learning_available: true, reason: "direct_confirmation",
      absence_deadline_ms: performance.now() + 5000, memory: null,
    },
  };
}

it("clears the upload pause when a stopped session's retained clip is retried", async () => {
  const { result } = await startSession();
  act(() => { updatePaused(true); });
  expect(result.current.uploadPaused).toBe(true);
  await act(async () => { await result.current.stop(); });
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(result.current.status).toBe("idle");
  await act(async () => { await result.current.retryUpload(); });
  expect(clips.retry).toHaveBeenCalledOnce();
  expect(result.current.uploadPaused).toBe(false);
});

it("stops a session received after Stop without opening the camera", async () => {
  const pending = deferred<ReturnType<typeof response>>();
  send.mockImplementation(async (path) => path === "/api/session" ? pending.promise : response([]));
  const { result } = await mountSession();
  let starting!: Promise<void>;
  act(() => { starting = result.current.start(); });
  expect(result.current.status).toBe("starting");
  await act(async () => { await result.current.stop(); });
  await act(async () => {
    pending.resolve(response(session));
    await starting;
  });
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(send).toHaveBeenCalledWith("/api/session/generation/stop", expect.objectContaining({ method: "POST" }));
  expect(result.current.status).toBe("idle");
});

it("releases a camera received after Stop without attaching it", async () => {
  const pending = deferred<typeof stream>();
  getUserMedia.mockReturnValue(pending.promise);
  const { result, video } = await mountSession();
  let starting!: Promise<void>;
  await act(async () => { starting = result.current.start(); });
  expect(getUserMedia).toHaveBeenCalledOnce();
  await act(async () => { await result.current.stop(); });
  await act(async () => {
    pending.resolve(stream);
    await starting;
  });
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(video.srcObject).toBeNull();
  expect(captureFrames).not.toHaveBeenCalled();
});

it("stops capture and closes resources before waiting for the final upload", async () => {
  const finalUpload = deferred<void>();
  clips.stop.mockReturnValue(finalUpload.promise);
  const { result, video } = await startSession();
  let stopping!: Promise<void>;
  act(() => { stopping = result.current.stop(); });
  expect(result.current.status).toBe("saving");
  expect(stopFrames).toHaveBeenCalledOnce();
  expect(clips.stop).toHaveBeenCalledOnce();
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(Socket.latest.close).toHaveBeenCalledOnce();
  expect(stopFrames.mock.invocationCallOrder[0]).toBeLessThan(clips.stop.mock.invocationCallOrder[0]);
  expect(clips.stop.mock.invocationCallOrder[0]).toBeLessThan(stopTrack.mock.invocationCallOrder[0]);
  expect(stopTrack.mock.invocationCallOrder[0]).toBeLessThan(Socket.latest.close.mock.invocationCallOrder[0]);
  expect(video.srcObject).toBeNull();
  expect(send.mock.calls.some(([path]) => path === "/api/session/generation/stop")).toBe(false);
  await act(async () => {
    finalUpload.resolve();
    await stopping;
  });
  expect(send).toHaveBeenCalledWith("/api/session/generation/stop", expect.objectContaining({ method: "POST" }));
  expect(result.current.status).toBe("idle");
});

it("ignores callbacks from a stopped socket and retained recorder after a new session starts", async () => {
  const { result } = await startSession();
  const oldSocket = Socket.latest;
  const oldStatus = updateMemoryStatus;
  const oldPaused = updatePaused;
  await act(async () => { await result.current.stop(); });
  clips = { ...clips };
  await act(async () => { await result.current.start(); });
  act(() => { Socket.latest.onopen?.(); });
  act(() => {
    oldSocket.onopen?.();
    oldSocket.onclose?.();
    oldSocket.onmessage?.({ data: JSON.stringify(visionMessage()) });
    oldStatus("old upload");
    oldPaused(true);
  });
  expect(captureFrames).toHaveBeenCalledTimes(2);
  expect(result.current.status).toBe("live");
  expect(result.current.view).toBeNull();
  expect(result.current.memoryStatus).toBe("");
  expect(result.current.uploadPaused).toBe(false);
  expect(result.current.error).toBe("");
});

it("pauses stale camera observations while retaining the current visitor", async () => {
  const { result } = await startSession();
  act(() => { Socket.latest.onmessage?.({ data: JSON.stringify(visionMessage()) }); });
  expect(result.current.view?.encounter.learning_available).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(750); });
  expect(result.current.view?.detections).toEqual([]);
  expect(result.current.view?.encounter).toMatchObject({
    state: "paused", reason: "stale_observations", learning_available: false, visitor_id: "visitor",
  });
});

it("stops active resources on connection loss and on unmount", async () => {
  const { result, unmount } = await startSession();
  await act(async () => { Socket.latest.onclose?.(); });
  expect(result.current.status).toBe("idle");
  expect(result.current.error).toBe("Connection lost. Start again to resume.");
  expect(stopTrack).toHaveBeenCalledOnce();
  await act(async () => { await result.current.start(); });
  act(() => { Socket.latest.onopen?.(); });
  unmount();
  expect(stopTrack).toHaveBeenCalledTimes(2);
  expect(stopFrames).toHaveBeenCalledTimes(2);
  expect(Socket.latest.close).toHaveBeenCalledOnce();
});
