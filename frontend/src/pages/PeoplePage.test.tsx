import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { PeoplePage } from "./PeoplePage";
afterEach(() => vi.unstubAllGlobals());
it("shows automatically enrolled people without requiring a name", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: "p",
            name: null,
            relationship: null,
            created_at: "2026-10-09T00:00:00Z",
          },
        ],
      }),
  );
  render(
    <MemoryRouter>
      <PeoplePage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("link", { name: /Name not learned yet/ }),
  ).toHaveAttribute("href", "/people/p");
});
it("shows backend failure instead of an empty people list", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Offline")));
  render(
    <MemoryRouter>
      <PeoplePage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
});
