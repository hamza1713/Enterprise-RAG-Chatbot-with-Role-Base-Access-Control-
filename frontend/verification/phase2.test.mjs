import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { readNdjson } from '../src/api/ndjson.ts';

const encoder = new TextEncoder();

test('parses Phase 2 agentic step, chart, and citation NDJSON frames cleanly', async () => {
  const payload = [
    JSON.stringify({ type: 'init', thread_id: '1111-2222', mode: 'HYBRID', cached: false }),
    JSON.stringify({ type: 'step', node: 'input_guard', label: 'Authorized ReBAC scope', status: 'done' }),
    JSON.stringify({ type: 'chart', chart_spec: { type: 'bar', title: 'Dept Spend', xKey: 'dept', yKeys: ['spend'], rows: [{ dept: 'HR', spend: 1200 }] } }),
    JSON.stringify({ type: 'token', content: 'HR spend was $1,200 [1].' }),
    JSON.stringify({ type: 'citation', citations: [{ index: 1, chunk_id: '5_0', doc_id: 5, source: 'hr.md', snippet: 'Total spend $1,200' }] }),
    JSON.stringify({ type: 'metadata', thread_id: '1111-2222', mode: 'HYBRID', sources: ['hr.md'] }),
  ].join('\n') + '\n';

  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(payload));
      controller.close();
    },
  });

  const frames = [];
  for await (const frame of readNdjson(body)) {
    frames.push(frame);
  }

  assert.equal(frames.length, 6);
  assert.deepEqual(
    frames.map((f) => f.type),
    ['init', 'step', 'chart', 'token', 'citation', 'metadata'],
  );
  assert.equal(frames[2].chart_spec.type, 'bar');
  assert.equal(frames[4].citations[0].source, 'hr.md');
});

test('frontend auth files never store JWT tokens in browser storage and send cookies with requests', () => {
  const srcRoot = path.resolve(import.meta.dirname, '..', 'src');
  const authStoreSrc = fs.readFileSync(path.join(srcRoot, 'store', 'authStore.ts'), 'utf8');
  const clientSrc = fs.readFileSync(path.join(srcRoot, 'api', 'client.ts'), 'utf8');
  const chatSrc = fs.readFileSync(path.join(srcRoot, 'api', 'chat.ts'), 'utf8');

  assert.equal(authStoreSrc.includes('sessionStorage'), false);
  assert.equal(authStoreSrc.includes('localStorage'), false);
  assert.equal(authStoreSrc.includes('/auth/me'), true);
  assert.equal(authStoreSrc.includes('/auth/login'), true);

  assert.equal(clientSrc.includes('withCredentials: true'), true);
  assert.equal(clientSrc.includes('sessionStorage'), false);

  assert.equal(chatSrc.includes("credentials: 'include'"), true);
  assert.equal(chatSrc.includes('sessionStorage'), false);
});
