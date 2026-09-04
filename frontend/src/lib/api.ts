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

type ApiClientOptions = {
  baseUrl?: string
  fetcher?: typeof fetch
}

type RequestOptions = {
  body?: unknown
  headers?: HeadersInit
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? getApiBaseUrl()
  const fetcher = options.fetcher ?? fetch

  async function request<T>(
    method: string,
    path: string,
    requestOptions: RequestOptions = {}
  ): Promise<T> {
    const headers: Record<string, string> = {
      ...(requestOptions.headers as Record<string, string> | undefined),
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
