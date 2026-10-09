import { it, expect } from "vitest";
import { acceptResult } from "./protocol";
it("rejects old session, duplicate, and stale results", () => {
  expect(
    acceptResult(
      { generation: "old", sequence: 2, capture_ms: 50 },
      "new",
      1,
      100,
    ),
  ).toBe(false);
  expect(
    acceptResult(
      { generation: "new", sequence: 1, capture_ms: 50 },
      "new",
      1,
      100,
    ),
  ).toBe(false);
  expect(
    acceptResult(
      { generation: "new", sequence: 2, capture_ms: 50 },
      "new",
      1,
      1000,
    ),
  ).toBe(false);
  expect(
    acceptResult(
      { generation: "new", sequence: 2, capture_ms: 50 },
      "new",
      1,
      100,
    ),
  ).toBe(true);
});
