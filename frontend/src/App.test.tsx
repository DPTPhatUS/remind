import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import App from "@/App"

function jsonResponse(body: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(body), {
    status: init?.status ?? 200,
    headers: { "content-type": "application/json" },
  })
}

describe("app flows", () => {
  it("redirects protected admin pages to caregiver login", async () => {
    render(
      <MemoryRouter initialEntries={["/admin/review"]}>
        <App />
      </MemoryRouter>
    )

    expect(await screen.findByRole("heading", { name: /caregiver login/i }))
      .toBeInTheDocument()
  })

  it("submits bootstrap setup and enters live assistant", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        access_token: "setup-token",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      })
    )
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={["/setup"]}>
        <App />
      </MemoryRouter>
    )

    await user.type(screen.getByLabelText(/caregiver email/i), "care@example.com")
    await user.type(screen.getByLabelText(/caregiver name/i), "Primary Caregiver")
    await user.type(screen.getByLabelText(/password/i), "strong-password")
    await user.type(screen.getByLabelText(/patient name/i), "Anna Patient")
    await user.click(screen.getByRole("button", { name: /create setup/i }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/auth/bootstrap-admin",
        expect.objectContaining({ method: "POST" })
      )
    )
    expect(await screen.findByRole("heading", { name: /live assistant/i }))
      .toBeInTheDocument()
  })

  it("shows live reminder correction actions behind a menu", async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={["/live"]}>
        <App />
      </MemoryRouter>
    )

    expect(screen.getByText(/waiting for a meaningful interaction/i))
      .toBeInTheDocument()
    await user.click(screen.getByLabelText(/reminder actions/i))

    expect(screen.getByRole("menuitem", { name: /wrong person/i }))
      .toBeInTheDocument()
    expect(screen.getByRole("menuitem", { name: /ask caregiver/i }))
      .toBeInTheDocument()
  })

  it("renders review inbox items and sends caregiver decisions", async () => {
    window.localStorage.setItem(
      "remind.auth",
      JSON.stringify({
        access_token: "admin-token",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      })
    )
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: "review-1",
            patient_id: "patient-1",
            item_type: "new_person_candidate",
            target_type: "person",
            target_id: "person-1",
            title: "Review new person: David",
            summary: "Introduced himself as a neighbor.",
            payload: {},
            status: "pending",
            created_at: "2026-06-16T20:00:00Z",
            updated_at: "2026-06-16T20:00:00Z",
          },
        ])
      )
      .mockResolvedValueOnce(jsonResponse({ id: "review-1", status: "approved" }))
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={["/admin/review"]}>
        <App />
      </MemoryRouter>
    )

    expect(await screen.findByText(/review new person: david/i))
      .toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /^Approve$/ }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "http://localhost:8000/api/v1/review-items/review-1",
        expect.objectContaining({ method: "PATCH" })
      )
    )
  })

  it("labels memory search results as claims until confirmed", async () => {
    window.localStorage.setItem(
      "remind.auth",
      JSON.stringify({
        access_token: "admin-token",
        token_type: "bearer",
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      })
    )
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse([
        {
          id: "claim-1",
          patient_id: "patient-1",
          subject_type: "interaction",
          subject_id: "interaction-1",
          claim_text: "David said he lives next door.",
          structured_value: {},
          source_type: "interaction",
          source_id: "interaction-1",
          confidence: 0.5,
          confirmed_by_user_id: null,
          patient_visible: true,
          created_at: "2026-06-16T20:00:00Z",
          updated_at: "2026-06-16T20:00:00Z",
        },
      ])
    )
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={["/admin/search"]}>
        <App />
      </MemoryRouter>
    )

    await user.type(screen.getByLabelText(/search memories/i), "groceries")
    await user.click(screen.getByRole("button", { name: /search/i }))

    expect(await screen.findByText(/unconfirmed claim/i)).toBeInTheDocument()
    expect(screen.getByText(/david said he lives next door/i)).toBeInTheDocument()
  })
})
