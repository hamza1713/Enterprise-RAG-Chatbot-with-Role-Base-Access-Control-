/** Decode streamed JSON without dropping split UTF-8 characters or malformed records. */
export async function* readNdjson<T>(body: ReadableStream<Uint8Array>): AsyncGenerator<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      if (buffer.length > 1024 * 1024) throw new Error('The response exceeded the supported message size.');
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line) as T;
      }
      if (done) break;
    }
    if (buffer.trim()) yield JSON.parse(buffer) as T;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
