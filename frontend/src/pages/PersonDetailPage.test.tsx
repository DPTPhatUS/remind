import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import type { Fact, PersonMemory } from "@/lib/api-types";
import { PersonDetailPage } from "./PersonDetailPage";

const now = "2026-10-26T12:00:00Z";
const fact = (id: string, overrides: Partial<Fact> = {}): Fact => ({
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
const profile = (): PersonMemory => ({
  id: "anna",
  name: "Anna",
  relationship: "Daughter",
  age: null,
  notes: null,
  version: 2,
  created_at: now,
  profile_summary: "Anna enjoys gardening.",
  highlights: ["Enjoys gardening"],
  last_encounter: null,
  encounters: [],
  facts: [
    fact("f1"),
    fact("f2", {
      subject: "related:brother",
      category: "work",
      predicate: "occupation",
      value: "Teacher",
    }),
    fact("f3", {
      category: "work",
      predicate: "occupation",
      value: "Bank teller",
      temporal_status: "past",
    }),
    fact("f4", {
      category: "identity",
      predicate: "name",
      value: "Anne",
      status: "conflict",
    }),
  ],
});
function mount() {
  render(
    <MemoryRouter initialEntries={["/people/anna"]}>
      <Routes>
        <Route path="/people/:id" element={<PersonDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}
afterEach(() => vi.unstubAllGlobals());

it("separates current, related, past, and unresolved facts and exposes quotes", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => profile() }),
  );
  mount();
  await screen.findByRole("heading", { name: "Anna" });
  expect(
    screen.getByRole("heading", { name: "Interests and routines" }),
  ).toBeVisible();
  const related = screen
    .getByRole("heading", { name: "Related people" })
    .closest("section")!;
  expect(within(related).getByText("Teacher")).toBeInTheDocument();
  const past = screen
    .getByRole("heading", { name: "Past information and plans" })
    .closest("section")!;
  expect(within(past).getByText("Bank teller")).toBeInTheDocument();
  expect(screen.getByText("Unresolved information (1)")).toBeInTheDocument();
  fireEvent.click(screen.getByText("Gardening", { exact: true }));
  const gardening = screen
    .getByText("Gardening", { exact: true })
    .closest("details")!;
  expect(
    within(gardening).getByText("“I love gardening.”", {
      exact: true,
      selector: "blockquote",
    }),
  ).toBeVisible();
});

it("saves and removes an individual fact using the current profile version", async () => {
  const person = profile();
  const fetcher = vi.fn().mockImplementation(async (path, options) => {
    if (options?.method === "PATCH") {
      const change = JSON.parse(options.body);
      expect(change).toEqual({ version: 2, value: "Cooking" });
      person.facts[0].value = "Cooking";
      person.facts[0].manual = true;
      person.facts[0].updated_at = "2026-10-26T12:01:00Z";
      person.version = 3;
    }
    if (options?.method === "DELETE") {
      expect(path).toBe("/api/people/anna/facts/f1");
      expect(JSON.parse(options.body)).toEqual({ version: 3 });
      person.facts = person.facts.filter((item) => item.id !== "f1");
    }
    return { ok: true, json: async () => structuredClone(person) };
  });
  vi.stubGlobal("fetch", fetcher);
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mount();
  await screen.findByRole("heading", { name: "Anna" });
  const details = screen
    .getByText("Gardening", { exact: true })
    .closest("details")!;
  fireEvent.click(screen.getByText("Gardening", { exact: true }));
  fireEvent.click(
    within(details).getByRole("button", { name: "Correct fact" }),
  );
  fireEvent.change(within(details).getByLabelText("Correct enjoys"), {
    target: { value: "Cooking" },
  });
  fireEvent.click(
    within(details).getByRole("button", { name: "Save fact correction" }),
  );
  const corrected = await screen.findByText("Cooking", { exact: true });
  fireEvent.click(
    within(corrected.closest("details")!).getByRole("button", {
      name: "Remove fact",
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByText("Cooking", { exact: true }),
    ).not.toBeInTheDocument(),
  );
  expect(
    fetcher.mock.calls.some(([, options]) => options?.method === "DELETE"),
  ).toBe(true);
});
