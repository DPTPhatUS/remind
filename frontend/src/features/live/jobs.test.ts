import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useConversationJobs } from "./jobs";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: request }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((finish) => { resolve = finish; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.useFakeTimers();
  request.mockReset().mockResolvedValue([]);
});
afterEach(() => { vi.useRealTimers(); });

it("polls immediately, then waits three seconds after settlement without overlapping requests", async () => {
  const first = deferred<{ id: string; status: string }[]>();
  request.mockReturnValueOnce(first.promise);
  const { result } = renderHook(() => useConversationJobs());
  expect(request).toHaveBeenCalledExactlyOnceWith("/jobs");
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
  await act(async () => { first.resolve([{ id: "clip", status: "running" }]); });
  expect(result.current).toBe("1 conversation clip(s) processing.");
  await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
  expect(request).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(request).toHaveBeenCalledTimes(2);
  expect(result.current).toBe("");
});

it("reports a poll failure and recovers on the next poll", async () => {
  request
    .mockResolvedValueOnce([{ id: "clip", status: "failed" }])
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce([{ id: "clip", status: "waiting_for_attribution" }]);
  const { result } = renderHook(() => useConversationJobs());
  await act(async () => {});
  expect(result.current).toContain("could not be processed");
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current).toBe(
    "Conversation processing status is unavailable. Check the server connection.",
  );
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current).toBe("Conversation transcribed; waiting to identify the visitor.");
});

it("does not schedule another poll after unmounting with an in-flight request", async () => {
  const pending = deferred<never[]>();
  request.mockReturnValueOnce(pending.promise);
  const { unmount } = renderHook(() => useConversationJobs());
  unmount();
  await act(async () => { pending.resolve([]); });
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
});

it("clears a scheduled poll on unmount", async () => {
  const { unmount } = renderHook(() => useConversationJobs());
  await act(async () => {});
  unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
});
