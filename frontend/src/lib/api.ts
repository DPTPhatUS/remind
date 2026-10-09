export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : message;
    } catch {
      /* retain status */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
