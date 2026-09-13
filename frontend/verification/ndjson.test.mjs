import test from 'node:test';
import assert from 'node:assert/strict';
import { readNdjson } from '../src/api/ndjson.ts';

const encoder = new TextEncoder();
function stream(chunks) {
  return new ReadableStream({ start(controller) { chunks.forEach(chunk => controller.enqueue(chunk)); controller.close(); } });
}
async function collect(body) {
  const items = [];
  for await (const item of readNdjson(body)) items.push(item);
  return items;
}
test('handles arbitrarily split records and multibyte text', async () => {
  const bytes = encoder.encode('{"type":"token","content":"Olá 🌿"}\n{"type":"metadata"}\n');
  const result = await collect(stream(Array.from(bytes, byte => new Uint8Array([byte]))));
  assert.deepEqual(result, [{ type: 'token', content: 'Olá 🌿' }, { type: 'metadata' }]);
});
test('accepts blank lines and an unterminated final record', async () => {
  assert.deepEqual(await collect(stream([encoder.encode('\n{"type":"metadata"}') ])), [{ type: 'metadata' }]);
});
test('rejects malformed JSON instead of silently completing', async () => {
  await assert.rejects(() => collect(stream([encoder.encode('{broken}\n')])), SyntaxError);
});
test('releases the reader when consumption is cancelled', async () => {
  let cancelled = false;
  const body = new ReadableStream({ start(controller) { controller.enqueue(encoder.encode('{"type":"token"}\n')); }, cancel() { cancelled = true; } });
  for await (const item of readNdjson(body)) { assert.equal(item.type, 'token'); break; }
  assert.equal(cancelled, true);
  assert.equal(body.locked, false);
});
test('bounds incomplete records', async () => {
  await assert.rejects(() => collect(stream([encoder.encode('x'.repeat(1024 * 1024 + 1))])), /message size/);
});
