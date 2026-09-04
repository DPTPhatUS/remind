import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useLiveSession } from "@/features/live/live-session"

function createMockMediaStream() {
  const tracks = [
    { stop: vi.fn(), getSettings: () => ({ width: 640, height: 360 }) },
    { stop: vi.fn() },
  ]
  return {
    getTracks: () => tracks,
    getVideoTracks: () => [tracks[0]],
    getAudioTracks: () => [tracks[1]],
  } as unknown as MediaStream
}

function createMockWebSocket() {
  return {
    readyState: 0,
    send: vi.fn(),
    close: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }
}

function installWebSocketMock(mockSocket: ReturnType<typeof createMockWebSocket>) {
  const WebSocketMock = vi.fn().mockImplementation(function () {
    queueMicrotask(() => {
      mockSocket.readyState = 1
      const openHandlers = (
        mockSocket.addEventListener.mock.calls as [string, () => void][]
      )
        .filter((call) => call[0] === "open")
        .map((call) => call[1])
      openHandlers.forEach((handler) => handler())
    })
    return mockSocket
  })
  // @ts-expect-error vitest mock does not have WebSocket static properties
  WebSocketMock.OPEN = 1
  // @ts-expect-error vitest mock does not have WebSocket static properties
  WebSocketMock.CONNECTING = 0
  // @ts-expect-error vitest mock does not have WebSocket static properties
  WebSocketMock.CLOSING = 2
  // @ts-expect-error vitest mock does not have WebSocket static properties
  WebSocketMock.CLOSED = 3
  vi.stubGlobal("WebSocket", WebSocketMock)
}

describe("useLiveSession", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue(createMockMediaStream()),
      },
      configurable: true,
      writable: true,
    })

    Object.defineProperty(globalThis, "crypto", {
      value: {
        randomUUID: vi.fn().mockReturnValue("test-session-id"),
        getRandomValues: vi.fn(),
      },
      configurable: true,
    })

    vi.stubGlobal(
      "AudioContext",
      vi.fn().mockImplementation(function () {
        return {
          sampleRate: 16000,
          createMediaStreamSource: vi.fn().mockReturnValue({
            connect: vi.fn(),
          }),
          createScriptProcessor: vi.fn().mockReturnValue({
            connect: vi.fn(),
            disconnect: vi.fn(),
            onaudioprocess: null as
              | ((event: AudioProcessingEvent) => void)
              | null,
          }),
          close: vi.fn(),
        }
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("dispatches websocket messages to the live event reducer", async () => {
    const mockSocket = createMockWebSocket()
    installWebSocketMock(mockSocket)

    const { result } = renderHook(() => useLiveSession())

    await waitFor(() =>
      expect(result.current.connectionState).toBe("connected"),
    )

    const messageCalls = (
      mockSocket.addEventListener.mock.calls as [
        string,
        (event: { data: string }) => void,
      ][]
    ).filter((call) => call[0] === "message")
    const messageHandler = messageCalls[0][1]

    messageHandler({
      data: JSON.stringify({
        type: "reminder.update",
        payload: {
          title: "This may be David.",
          lines: ["He introduced himself as your neighbor."],
          patient_visible: true,
        },
      }),
    })

    await waitFor(() =>
      expect(result.current.state.reminder?.title).toBe("This may be David."),
    )

    messageHandler({
      data: JSON.stringify([
        {
          type: "session.error",
          payload: { message: "Recognition model timeout" },
        },
      ]),
    })

    await waitFor(() =>
      expect(result.current.state.error).toBe("Recognition model timeout"),
    )
  })

  it("returns exactly state, stream, and connectionState (no submitCorrection)", async () => {
    const mockSocket = createMockWebSocket()
    installWebSocketMock(mockSocket)

    const { result } = renderHook(() => useLiveSession())

    await waitFor(() =>
      expect(result.current.connectionState).toBe("connected"),
    )

    expect(Object.keys(result.current).sort()).toEqual([
      "connectionState",
      "state",
      "stream",
    ])
    expect(result.current).not.toHaveProperty("submitCorrection")
  })
})
