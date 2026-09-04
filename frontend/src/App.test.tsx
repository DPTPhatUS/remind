import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("@/features/live/live-session", () => ({
  useLiveSession: () => ({
    state: {
      sessionId: null,
      reminder: null,
      recognitions: [],
      media: { frameAccepted: false, audioAccepted: false },
      interaction: { status: "idle" as const, interactionId: null, reason: null },
      latestTranscript: null,
      error: null,
    },
    stream: null,
    connectionState: "idle" as const,
  }),
}))

const mockGet = vi.fn()
vi.mock("@/lib/api", () => ({
  createApiClient: () => ({
    get: (...a: unknown[]) => mockGet(...a),
    post: vi.fn(),
    patch: vi.fn(),
  }),
  ApiError: class extends Error {
    status: number
    constructor(status: number, msg: string) {
      super(msg)
      this.status = status
    }
  },
  getApiBaseUrl: () => "http://test/api/v1",
  getLiveWebSocketUrl: (id: string) => `ws://test/api/v1/live/sessions/${id}`,
}))

import App from "@/App"

const PATIENT = {
  id: "pt1",
  display_name: "Patient",
  date_of_birth: null,
  preferences: {},
  accessibility_settings: {},
  created_at: "",
  updated_at: "",
}

function renderApp(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  )
}

describe("app routes", () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue([])
  })

  it("renders LiveAssistantPage on /", () => {
    renderApp("/")
    expect(screen.getByText(/live assistant/i)).toBeInTheDocument()
    expect(screen.getByTestId("top-nav")).toBeInTheDocument()
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument()
  })

  it("renders PeoplePage on /people", async () => {
    mockGet.mockResolvedValueOnce([])
    renderApp("/people")
    await waitFor(() =>
      expect(
        screen.getAllByRole("link", { name: "People" }).length,
      ).toBeGreaterThan(0),
    )
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument()
  })

  it("renders ProfilePage on /profile", async () => {
    mockGet.mockResolvedValueOnce(PATIENT)
    renderApp("/profile")
    await waitFor(() =>
      expect(
        screen.getAllByRole("link", { name: "Profile" }).length,
      ).toBeGreaterThan(0),
    )
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument()
  })

  it("TopNav is visible on all patient routes", () => {
    renderApp("/")
    expect(screen.getByTestId("top-nav")).toBeInTheDocument()
  })

  it.each(["/admin/review", "/login", "/setup", "/unknown"])(
    "redirects %s to / (no caregiver chrome)",
    (route) => {
      renderApp(route)
      expect(screen.getByText(/live assistant/i)).toBeInTheDocument()
      expect(screen.queryByText(/admin/i)).not.toBeInTheDocument()
    },
  )
})
