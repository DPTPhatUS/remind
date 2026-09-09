import { useEffect, useReducer, useRef, useState } from "react"

import {
  createInitialLiveState,
  normalizeLiveEvents,
  reduceLiveEvent,
} from "@/features/live/live-events"
import type { LiveServerMessage } from "@/lib/api-types"
import { getLiveWebSocketUrl } from "@/lib/api"

const FRAME_INTERVAL_MS = 167
const FRAME_TARGET_WIDTH = 480
const FRAME_TARGET_HEIGHT = 270
const FRAME_JPEG_QUALITY = 0.6
const MAX_RECONNECT_ATTEMPTS = 8
const RECONNECT_BASE_MS = 500
const RECONNECT_MAX_MS = 8_000

function liveReducer(
  state: ReturnType<typeof createInitialLiveState>,
  events: LiveServerMessage[]
) {
  return events.reduce(reduceLiveEvent, state)
}

export function useLiveSession() {
  const [state, dispatch] = useReducer(liveReducer, undefined, createInitialLiveState)
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [connectionState, setConnectionState] = useState<
    "idle" | "connecting" | "connected" | "error"
  >("idle")
  const socketRef = useRef<WebSocket | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const sequenceRef = useRef({ video: 0, audio: 0 })
  const startedAtRef = useRef<number>(0)
  const stoppedRef = useRef(false)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    stoppedRef.current = false
    let rafHandle: number | undefined
    let audioContext: AudioContext | undefined
    let processor: ScriptProcessorNode | undefined
    const offscreen = document.createElement("canvas")
    offscreen.width = FRAME_TARGET_WIDTH
    offscreen.height = FRAME_TARGET_HEIGHT
    const offscreenCtx = offscreen.getContext("2d", { alpha: false })

    function sendVideoFrame(mediaStream: MediaStream, sequence: number, startedAt: number) {
      const socket = socketRef.current
      if (!socket || socket.readyState !== WebSocket.OPEN || !offscreenCtx) return

      const video = document.querySelector("video[data-live-video]") as
        | HTMLVideoElement
        | null
      if (!video || video.readyState < 2) return

      offscreenCtx.drawImage(
        video,
        0,
        0,
        video.videoWidth || FRAME_TARGET_WIDTH,
        video.videoHeight || FRAME_TARGET_HEIGHT,
        0,
        0,
        FRAME_TARGET_WIDTH,
        FRAME_TARGET_HEIGHT,
      )
      const dataUrl = offscreen.toDataURL("image/jpeg", FRAME_JPEG_QUALITY)
      const commaIdx = dataUrl.indexOf(",")
      const imageBase64 = commaIdx >= 0 ? dataUrl.slice(commaIdx + 1) : dataUrl

      socket.send(
        JSON.stringify({
          type: "video.frame",
          payload: {
            image_base64: imageBase64,
            content_type: "image/jpeg",
            filename: "frame.jpg",
            sequence,
            captured_at_ms: Date.now() - startedAt,
          },
        }),
      )
      void mediaStream
    }

    function connectSocket() {
      const sessionId = crypto.randomUUID()
      const socket = new WebSocket(getLiveWebSocketUrl(sessionId))
      socketRef.current = socket

      socket.addEventListener("open", () => {
        reconnectAttemptRef.current = 0
        setConnectionState("connected")
        socket.send(JSON.stringify({ type: "session.start", payload: {} }))
      })

      socket.addEventListener("message", (message) => {
        try {
          dispatch(normalizeLiveEvents(JSON.parse(message.data) as LiveServerMessage))
        } catch {
          // swallow malformed payloads so one bad frame doesn't kill the session
        }
      })

      socket.addEventListener("close", () => {
        socketRef.current = null
        if (stoppedRef.current) return
        scheduleReconnect()
      })

      socket.addEventListener("error", () => {
        // close fires after error; let it drive reconnect
      })
    }

    function scheduleReconnect() {
      if (stoppedRef.current) return
      if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
        setConnectionState("error")
        return
      }
      const attempt = reconnectAttemptRef.current
      reconnectAttemptRef.current += 1
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, attempt),
        RECONNECT_MAX_MS,
      )
      setConnectionState("connecting")
      reconnectTimerRef.current = window.setTimeout(connectSocket, delay)
    }

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setConnectionState("error")
        return
      }

      setConnectionState("connecting")
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: FRAME_TARGET_WIDTH },
          height: { ideal: FRAME_TARGET_HEIGHT },
        },
        audio: true,
      })
      if (stoppedRef.current) {
        mediaStream.getTracks().forEach((track) => track.stop())
        return
      }

      setStream(mediaStream)
      streamRef.current = mediaStream
      startedAtRef.current = Date.now()

      connectSocket()

      let lastFrameAt = 0
      const tick = (now: number) => {
        if (stoppedRef.current) return
        if (now - lastFrameAt >= FRAME_INTERVAL_MS) {
          lastFrameAt = now
          sendVideoFrame(
            mediaStream,
            sequenceRef.current.video++,
            startedAtRef.current,
          )
        }
        rafHandle = requestAnimationFrame(tick)
      }
      rafHandle = requestAnimationFrame(tick)

      audioContext = new AudioContext({ sampleRate: 16_000 })
      const source = audioContext.createMediaStreamSource(mediaStream)
      processor = audioContext.createScriptProcessor(2048, 1, 1)
      processor.onaudioprocess = (event) => {
        const socket = socketRef.current
        if (!socket || socket.readyState !== WebSocket.OPEN) return
        const pcm = floatTo16BitPcm(event.inputBuffer.getChannelData(0))
        socket.send(
          JSON.stringify({
            type: "audio.chunk",
            payload: {
              content_type: "audio/pcm",
              sample_rate_hz: audioContext?.sampleRate ?? 16_000,
              channels: 1,
              sample_width_bits: 16,
              sequence: sequenceRef.current.audio++,
              captured_at_ms: Date.now() - startedAtRef.current,
              data: bytesToBase64(new Uint8Array(pcm.buffer)),
            },
          }),
        )
      }
      source.connect(processor)
    }

    start().catch(() => setConnectionState("error"))

    return () => {
      stoppedRef.current = true
      if (rafHandle !== undefined) cancelAnimationFrame(rafHandle)
      if (reconnectTimerRef.current !== undefined)
        window.clearTimeout(reconnectTimerRef.current)
      processor?.disconnect()
      void audioContext?.close()
      const socket = socketRef.current
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "session.stop", payload: {} }))
      }
      socket?.close()
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }, [])

  return { state, stream, connectionState }
}

function floatTo16BitPcm(input: Float32Array) {
  const output = new Int16Array(input.length)
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]))
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }
  return output
}

const BASE64_CHUNK = 0x8000
function bytesToBase64(bytes: Uint8Array): string {
  let binary = ""
  for (let i = 0; i < bytes.length; i += BASE64_CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + BASE64_CHUNK))
  }
  return window.btoa(binary)
}
