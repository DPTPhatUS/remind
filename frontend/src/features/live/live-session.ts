import { useEffect, useReducer, useRef, useState } from "react"

import {
  createInitialLiveState,
  normalizeLiveEvents,
  reduceLiveEvent,
} from "@/features/live/live-events"
import type { LiveServerMessage } from "@/lib/api-types"
import { getLiveWebSocketUrl } from "@/lib/api"

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

  useEffect(() => {
    let stopped = false
    let frameTimer: number | undefined
    let audioContext: AudioContext | undefined
    let processor: ScriptProcessorNode | undefined

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setConnectionState("error")
        return
      }

      setConnectionState("connecting")
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      })
      if (stopped) {
        mediaStream.getTracks().forEach((track) => track.stop())
        return
      }

      setStream(mediaStream)
      streamRef.current = mediaStream
      startedAtRef.current = Date.now()
      const sessionId = crypto.randomUUID()
      const socket = new WebSocket(getLiveWebSocketUrl(sessionId))
      socketRef.current = socket

      socket.addEventListener("open", () => {
        setConnectionState("connected")
        socket.send(JSON.stringify({ type: "session.start", payload: {} }))
      })
      socket.addEventListener("message", (message) => {
        dispatch(normalizeLiveEvents(JSON.parse(message.data) as LiveServerMessage))
      })
      socket.addEventListener("error", () => setConnectionState("error"))
      socket.addEventListener("close", () => {
        if (!stopped) setConnectionState("idle")
      })

      frameTimer = window.setInterval(() => {
        sendVideoFrame(
          socket,
          mediaStream,
          sequenceRef.current.video++,
          startedAtRef.current
        )
      }, 1000)

      audioContext = new AudioContext({ sampleRate: 16_000 })
      const source = audioContext.createMediaStreamSource(mediaStream)
      processor = audioContext.createScriptProcessor(2048, 1, 1)
      processor.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return
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
              data: arrayBufferToBase64(pcm.buffer),
            },
          })
        )
      }
      source.connect(processor)
    }

    start().catch(() => setConnectionState("error"))

    return () => {
      stopped = true
      if (frameTimer !== undefined) window.clearInterval(frameTimer)
      processor?.disconnect()
      void audioContext?.close()
      socketRef.current?.send(JSON.stringify({ type: "session.stop", payload: {} }))
      socketRef.current?.close()
      streamRef.current?.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }, [])

  return { state, stream, connectionState }
}

function sendVideoFrame(
  socket: WebSocket,
  stream: MediaStream,
  sequence: number,
  startedAt: number
) {
  if (socket.readyState !== WebSocket.OPEN) return

  const track = stream.getVideoTracks()[0]
  if (!track) return

  const settings = track.getSettings()
  const canvas = document.createElement("canvas")
  canvas.width = settings.width ?? 640
  canvas.height = settings.height ?? 360
  const video = document.querySelector("video[data-live-video]") as
    | HTMLVideoElement
    | null
  if (!video) return

  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height)
  const [, imageBase64] = canvas.toDataURL("image/jpeg", 0.75).split(",")

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
    })
  )
}

function floatTo16BitPcm(input: Float32Array) {
  const output = new Int16Array(input.length)
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index]))
    output[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
  }
  return output
}

function arrayBufferToBase64(buffer: ArrayBufferLike) {
  const bytes = new Uint8Array(buffer)
  let binary = ""
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte)
  })
  return window.btoa(binary)
}
