type Receipt = { status: string };
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
          error.detail ?? "Memory upload failed",
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
  let active = true,
    recorder: MediaRecorder | null = null,
    timer = 0,
    pending = Promise.resolve();
  let retained: { metadata: string; clip: Blob } | null = null;
  let finished: Promise<void> = Promise.resolve();
  const mime = ["video/webm;codecs=vp8,opus", "video/webm"].find((type) =>
    MediaRecorder.isTypeSupported(type),
  );
  if (!mime)
    throw new Error(
      "This browser cannot record synchronized WebM audio and video.",
    );
  async function upload() {
    if (!retained) return;
    try {
      const receipt = await uploadClip(
        generation,
        retained.metadata,
        retained.clip,
      );
      retained = null;
      onPaused(false);
      onStatus(
        receipt.status === "queued"
          ? "Conversation saved for processing."
          : "No single sustained encounter in this clip.",
      );
      if (active) begin();
    } catch (error) {
      onPaused(true);
      onStatus(
        `Conversation capture paused: ${String(error)}. One clip is retained in this tab; retry or download it before leaving.`,
      );
    }
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
          pending = upload();
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
    retry: async () => {
      await pending;
      pending = upload();
      await pending;
    },
    download: () => {
      if (!retained) return;
      const url = URL.createObjectURL(retained.clip),
        link = document.createElement("a");
      link.href = url;
      link.download = "remind-unsaved-conversation.webm";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    stop: async () => {
      active = false;
      clearTimeout(timer);
      if (recorder && recorder.state !== "inactive") recorder.stop();
      await finished;
      await pending;
    },
  };
}
