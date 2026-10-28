import { downloadFile } from "@/lib/download";

type Receipt = { clip_id: string; status: string };
class UploadError extends Error {
  retryable: boolean;
  constructor(message: string, retryable: boolean) {
    super(message);
    this.retryable = retryable;
  }
}
export async function uploadClip(
  generation: string,
  metadata: string,
  clip: Blob,
  send: typeof fetch = fetch,
  wait = (ms: number) =>
    new Promise<void>((resolve) => setTimeout(resolve, ms)),
): Promise<Receipt> {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await send(
        `/api/live/${generation}/clips?metadata=${metadata}`,
        { method: "POST", body: clip, signal: AbortSignal.timeout(15000) },
      );
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Memory upload failed" }));
        throw new UploadError(
          typeof error.detail === "string" ? error.detail : "Memory upload failed",
          [429, 500, 502, 503, 504].includes(response.status),
        );
      }
      return await response.json();
    } catch (error) {
      if (attempt === 2 || (error instanceof UploadError && !error.retryable))
        throw error;
      await wait(500 * 2 ** attempt);
    }
  }
  throw new Error("Memory upload failed");
}
export function recordClips(
  stream: MediaStream,
  generation: string,
  onStatus: (text: string) => void,
  onPaused: (paused: boolean) => void,
) {
  let active = true;
  let recorder: MediaRecorder | null = null;
  let timer = 0;
  let uploadPromise: Promise<void> | null = null;
  let retained: { metadata: string; clip: Blob } | null = null;
  let finished: Promise<void> = Promise.resolve();
  const mime = ["video/webm;codecs=vp8,opus", "video/webm"].find((type) =>
    MediaRecorder.isTypeSupported(type),
  );
  if (!mime)
    throw new Error(
      "This browser cannot record synchronized WebM audio and video.",
    );
  async function sendRetained(clip: { metadata: string; clip: Blob }) {
    try {
      const receipt = await uploadClip(generation, clip.metadata, clip.clip);
      retained = null;
      onPaused(false);
      onStatus(
        receipt.status === "waiting_for_attribution"
          ? "Conversation transcribed; waiting to identify the visitor."
          : "Conversation received for processing.",
      );
      if (active) begin();
    } catch (error) {
      onPaused(true);
      onStatus(
        `Conversation capture paused: ${String(error)}. One clip is retained in this tab; retry or download it before leaving.`,
      );
    }
  }
  function upload() {
    if (uploadPromise) return uploadPromise;
    if (!retained) return Promise.resolve();
    uploadPromise = sendRetained(retained).finally(() => {
      uploadPromise = null;
    });
    return uploadPromise;
  }

  function begin() {
    if (!active || retained) return;
    const chunks: Blob[] = [];
    const current = new MediaRecorder(stream, {
      mimeType: mime,
      videoBitsPerSecond: 1_000_000,
      audioBitsPerSecond: 64_000,
    });
    recorder = current;
    let start = performance.now();
    current.onstart = () => {
      start = performance.now();
    };
    current.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    current.onerror = () => {
      active = false;
      onStatus("Conversation recording failed. Stop and restart to try again.");
    };
    finished = new Promise<void>((resolve) => {
      current.onstop = () => {
        const end = performance.now();
        const clip = new Blob(chunks, { type: mime });
        if (clip.size && end - start > 300) {
          const metadata = encodeURIComponent(
            JSON.stringify({
              window_id: crypto.randomUUID(),
              start_ms: start,
              end_ms: end,
            }),
          );
          retained = { metadata, clip };
          void upload();
        } else if (active) begin();
        resolve();
      };
    });
    current.start(1000);
    timer = window.setTimeout(() => {
      if (current.state !== "inactive") current.stop();
    }, 8000);
  }
  begin();
  return {
    retry: upload,
    download: () => {
      if (!retained) return;
      if (uploadPromise) {
        onStatus(
          "The conversation upload is in progress. Wait for it to finish before downloading.",
        );
        return;
      }
      downloadFile(retained.clip, "remind-unsaved-conversation.webm");
      retained = null;
      onPaused(false);
      onStatus("Conversation downloaded. This clip has not been added to memory.");
      if (active) begin();
    },
    stop: async () => {
      active = false;
      clearTimeout(timer);
      if (recorder && recorder.state !== "inactive") recorder.stop();
      await finished;
      await uploadPromise;
    },
  };
}
