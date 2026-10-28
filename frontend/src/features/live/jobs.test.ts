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
  const { result } = renderHook(() => useConversationJobs(vi.fn()));
  expect(request).toHaveBeenCalledExactlyOnceWith("/jobs");
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
  await act(async () => { first.resolve([{ id: "clip", status: "learning" }]); });
  expect(result.current.jobsStatus).toBe("1 conversation clip(s) processing.");
  await act(async () => { await vi.advanceTimersByTimeAsync(2999); });
  expect(request).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(request).toHaveBeenCalledTimes(2);
  expect(result.current.jobsStatus).toBe("");
});

it("retains retry availability on a poll failure and recovers on the next poll", async () => {
  request
    .mockResolvedValueOnce([{ id: "clip", status: "failed" }])
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce([{ id: "clip", status: "waiting_for_attribution" }]);
  const { result } = renderHook(() => useConversationJobs(vi.fn()));
  await act(async () => {});
  expect(result.current.hasFailedJobs).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current.jobsStatus).toBe(
    "Conversation processing status is unavailable. Check the server connection.",
  );
  expect(result.current.hasFailedJobs).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(result.current.hasFailedJobs).toBe(false);
  expect(result.current.jobsStatus).toBe("Conversation transcribed; waiting to identify the visitor.");
});

it("does not schedule another poll after unmounting with an in-flight request", async () => {
  const pending = deferred<never[]>();
  request.mockReturnValueOnce(pending.promise);
  const { unmount } = renderHook(() => useConversationJobs(vi.fn()));
  unmount();
  await act(async () => { pending.resolve([]); });
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
});

it("clears a scheduled poll on unmount", async () => {
  const { unmount } = renderHook(() => useConversationJobs(vi.fn()));
  await act(async () => {});
  unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
  expect(request).toHaveBeenCalledOnce();
});

it("retries only failed jobs, in order, before showing the retry status", async () => {
  const firstRetry = deferred<object>();
  const jobs = [
    { id: "first", status: "failed" },
    { id: "working", status: "learning" },
    { id: "second", status: "failed" },
  ];
  request.mockImplementation(async (path) => path === "/jobs" ? jobs : path === "/jobs/first/retry" ? firstRetry.promise : {});
  const onError = vi.fn();
  const { result } = renderHook(() => useConversationJobs(onError));
  await act(async () => {});
  let retrying!: Promise<void>;
  await act(async () => { retrying = result.current.retryJobs(); });
  expect(request.mock.calls.map(([path]) => path)).toEqual(["/jobs", "/jobs", "/jobs/first/retry"]);
  await act(async () => {
    firstRetry.resolve({});
    await retrying;
  });
  expect(request.mock.calls.map(([path]) => path)).toEqual(["/jobs", "/jobs", "/jobs/first/retry", "/jobs/second/retry"]);
  expect(request).toHaveBeenLastCalledWith("/jobs/second/retry", { method: "POST" });
  expect(result.current.jobsStatus).toBe("Retrying failed conversations.");
  expect(result.current.hasFailedJobs).toBe(true);
  expect(onError).not.toHaveBeenCalled();
});

it("reports a failed retry through the session error callback without retrying later jobs", async () => {
  request.mockResolvedValue([{ id: "first", status: "failed" }, { id: "second", status: "failed" }]);
  const onError = vi.fn();
  const { result } = renderHook(() => useConversationJobs(onError));
  await act(async () => {});
  request.mockImplementation(async (path) => {
    if (path === "/jobs/first/retry") throw new Error("service unavailable");
    return [{ id: "first", status: "failed" }, { id: "second", status: "failed" }];
  });
  await act(async () => { await result.current.retryJobs(); });
  expect(onError).toHaveBeenCalledExactlyOnceWith("Error: service unavailable");
  expect(request.mock.calls.some(([path]) => path === "/jobs/second/retry")).toBe(false);
  expect(result.current.jobsStatus).toContain("2 conversation clip(s) could not be processed.");
});
