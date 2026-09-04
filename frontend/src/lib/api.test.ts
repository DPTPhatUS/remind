import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError, createApiClient, getLiveWebSocketUrl } from "@/lib/api"

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it("calls fetch without an Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ id: "user-id" }),
    })

    const client = createApiClient({ fetcher: fetchMock })
    const result = await client.get("/auth/me")

    expect(result).toEqual({ id: "user-id" })
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/me",
      expect.objectContaining({
        headers: expect.not.objectContaining({
          Authorization: expect.any(String),
        }),
      }),
    )
  })

  it("throws ApiError on non-2xx responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Internal error" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      }),
    )

    const client = createApiClient({ fetcher: fetchMock })
    await expect(client.get("/health")).rejects.toThrow(ApiError)
  })

  it("getLiveWebSocketUrl rewrites http to ws", () => {
    vi.stubEnv("VITE_API_BASE_URL", "http://test/api/v1")
    expect(getLiveWebSocketUrl("abc")).toBe(
      "ws://test/api/v1/live/sessions/abc",
    )
  })
})
