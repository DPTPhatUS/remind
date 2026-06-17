import { describe, expect, it, vi } from "vitest"

import {
  ApiError,
  AuthSessionStore,
  createApiClient,
  getApiBaseUrl,
} from "@/lib/api"

describe("api client", () => {
  it("uses the documented default API base URL", () => {
    expect(getApiBaseUrl()).toBe("http://localhost:8000/api/v1")
  })

  it("attaches bearer tokens and parses JSON responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ id: "user-id" }),
    })
    const session = new AuthSessionStore("test-auth")
    session.save({
      access_token: "token-123",
      token_type: "bearer",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
    })

    const client = createApiClient({ fetcher: fetchMock, session })
    const result = await client.get("/auth/me")

    expect(result).toEqual({ id: "user-id" })
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token-123",
        }),
      })
    )
  })

  it("clears expired tokens before requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ ok: true }),
    })
    const session = new AuthSessionStore("expired-auth")
    session.save({
      access_token: "old-token",
      token_type: "bearer",
      expires_at: new Date(Date.now() - 1_000).toISOString(),
    })

    await createApiClient({ fetcher: fetchMock, session }).get("/health")

    expect(session.read()).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/health",
      expect.objectContaining({
        headers: expect.not.objectContaining({
          Authorization: expect.any(String),
        }),
      })
    )
  })

  it("throws ApiError with backend detail on JSON errors", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ detail: "Bootstrap already completed." }),
    })

    await expect(
      createApiClient({ fetcher: fetchMock }).post("/auth/bootstrap-admin", {})
    ).rejects.toMatchObject(
      new ApiError(409, "Bootstrap already completed.")
    )
  })
})
