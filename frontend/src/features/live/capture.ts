import { packet } from "./protocol";
export function captureFrames(
  video: HTMLVideoElement,
  socket: WebSocket,
  generation: string,
) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("This browser cannot prepare camera frames.");
  canvas.width = 640;
  let running = true,
    encoding = false,
    sequence = 0,
    handle = 0;
  const tick = () => {
    if (!running) return;
    handle = video.requestVideoFrameCallback(tick);
    if (
      encoding ||
      socket.readyState !== WebSocket.OPEN ||
      socket.bufferedAmount > 256_000 ||
      !video.videoWidth
    )
      return;
    encoding = true;
    const capture_ms = performance.now();
    const height = Math.round((640 * video.videoHeight) / video.videoWidth);
    if (canvas.height !== height) canvas.height = height;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      async (blob) => {
        try {
          if (blob && running && socket.readyState === WebSocket.OPEN) {
            const bytes = await packet(
              {
                version: 1,
                generation,
                sequence: sequence++,
                capture_ms,
                width: canvas.width,
                height: canvas.height,
              },
              blob,
            );
            if (
              running &&
              socket.readyState === WebSocket.OPEN &&
              socket.bufferedAmount < 256_000
            )
              socket.send(bytes);
          }
        } finally {
          encoding = false;
        }
      },
      "image/jpeg",
      0.85,
    );
  };
  if ("requestVideoFrameCallback" in video)
    handle = video.requestVideoFrameCallback(tick);
  else
    throw new Error(
      "This browser needs video frame callback support. Use a current Chrome or Firefox.",
    );
  return () => {
    running = false;
    video.cancelVideoFrameCallback(handle);
  };
}
