import { expect, it, vi } from "vitest";
import { uploadClip } from "./audio";
it("retains the clip and retries a transient upload failure", async () => {
  const send = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({ detail: "Unavailable" }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "queued" }),
    });
  const result = await uploadClip(
    "session",
    "metadata",
    new Blob(["media"]),
    send,
    async () => {},
  );
  expect(result.status).toBe("queued");
  expect(send).toHaveBeenCalledTimes(2);
});
it("treats full storage as a recording pause", async () => {
  const send = vi
    .fn()
    .mockResolvedValue({
      ok: false,
      status: 507,
      json: async () => ({ detail: "Storage full" }),
    });
  await expect(
    uploadClip(
      "session",
      "metadata",
      new Blob(["media"]),
      send,
      async () => {},
    ),
  ).rejects.toThrow("Storage full");
  expect(send).toHaveBeenCalledTimes(1);
});
