export function acceptResult(
  message: { generation: string; sequence: number; capture_ms: number },
  generation: string,
  last: number,
  now: number,
) {
  return (
    message.generation === generation &&
    message.sequence > last &&
    now - message.capture_ms <= 500 &&
    now >= message.capture_ms
  );
}
export async function packet(header: object, blob: Blob) {
  const encoded = new TextEncoder().encode(JSON.stringify(header));
  const size = new ArrayBuffer(4);
  new DataView(size).setUint32(0, encoded.byteLength);
  return new Blob([size, encoded, blob]).arrayBuffer();
}
