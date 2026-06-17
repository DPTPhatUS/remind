import type { AuthTokenResponse } from "@/lib/api-types"

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export function getApiBaseUrl() {
  return (
    import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ??
    "http://localhost:8000/api/v1"
  )
}

export class AuthSessionStore {
  private key: string

  constructor(key = "remind.auth") {
    this.key = key
  }

  read(): AuthTokenResponse | null {
    const raw = window.localStorage.getItem(this.key)
    if (!raw) return null

    try {
      const parsed = JSON.parse(raw) as AuthTokenResponse
      if (!parsed.access_token || !parsed.expires_at) return null
      return parsed
    } catch {
      return null
    }
  }

  save(session: AuthTokenResponse) {
    window.localStorage.setItem(this.key, JSON.stringify(session))
  }

  clear() {
    window.localStorage.removeItem(this.key)
  }

  current(): AuthTokenResponse | null {
    const session = this.read()
    if (!session) return null

    if (new Date(session.expires_at).getTime() <= Date.now()) {
      this.clear()
      return null
    }

    return session
  }
}

type ApiClientOptions = {
  baseUrl?: string
  fetcher?: typeof fetch
  session?: AuthSessionStore
}

type RequestOptions = {
  body?: unknown
  headers?: HeadersInit
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? getApiBaseUrl()
  const fetcher = options.fetcher ?? fetch
  const session = options.session ?? new AuthSessionStore()

  async function request<T>(
    method: string,
    path: string,
    requestOptions: RequestOptions = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...(requestOptions.headers as Record<string, string> | undefined),
    }
    const token = session.current()

    if (token) {
      headers.Authorization = `Bearer ${token.access_token}`
    }

    const isFormData = requestOptions.body instanceof FormData
    if (requestOptions.body !== undefined && !isFormData) {
      headers["Content-Type"] = "application/json"
    }

    const body: BodyInit | undefined =
      requestOptions.body === undefined
        ? undefined
        : isFormData
          ? (requestOptions.body as BodyInit)
          : JSON.stringify(requestOptions.body)

    const response = await fetcher(`${baseUrl}${path}`, {
      method,
      headers,
      body,
    })

    if (!response.ok) {
      throw new ApiError(response.status, await readError(response))
    }

    if (response.status === 204) {
      return undefined as T
    }

    const contentType = response.headers.get("content-type")
    if (!contentType?.includes("application/json")) {
      return undefined as T
    }

    return (await response.json()) as T
  }

  return {
    get: <T>(path: string) => request<T>("GET", path),
    post: <T>(path: string, body?: unknown, headers?: HeadersInit) =>
      request<T>("POST", path, { body, headers }),
    patch: <T>(path: string, body?: unknown, headers?: HeadersInit) =>
      request<T>("PATCH", path, { body, headers }),
  }
}

async function readError(response: Response) {
  const contentType = response.headers.get("content-type")
  if (!contentType?.includes("application/json")) {
    return response.statusText || "Request failed"
  }

  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail ?? "Request failed"
  } catch {
    return "Request failed"
  }
}

export function getLiveWebSocketUrl(sessionId: string) {
  const base = getApiBaseUrl()
  const wsBase = base.replace(/^http:/, "ws:").replace(/^https:/, "wss:")
  return `${wsBase}/live/sessions/${sessionId}`
}
