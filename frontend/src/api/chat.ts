import { API_URL } from './client';
import { readNdjson } from './ndjson';
import type { AgentStep, ChartSpec, CitationItem } from '../types';

export interface ChatChunk {
  type: 'init' | 'step' | 'fallback' | 'token' | 'chart' | 'citation' | 'metadata' | 'error';
  user?: string;
  role?: string;
  mode?: string;
  thread_id?: string;
  node?: string;
  label?: string;
  status?: 'running' | 'done' | 'error';
  detail?: string;
  content?: string;
  message?: string;
  sql?: string | null;
  sql_retries?: number;
  sources?: string[];
  citations?: CitationItem[];
  chart_spec?: ChartSpec | null;
  agent_steps?: AgentStep[];
  guardrail_warnings?: string[];
  fallback?: boolean;
  cached?: boolean;
  answer?: string;
}

export const ALLOWED_CHAT_CHUNK_TYPES = new Set([
  'init',
  'step',
  'fallback',
  'token',
  'chart',
  'citation',
  'metadata',
  'error',
]);

export async function streamChat(
  question: string,
  onChunk: (chunk: ChatChunk) => void,
  onComplete: () => void,
  onError: (err: Error) => void,
  signal?: AbortSignal,
  history?: { role: string; content: string }[],
  threadId?: string | null
): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/chat-stream`, {
      method: 'POST',
      credentials: 'include',
      signal,
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question,
        history: history || [],
        thread_id: threadId || undefined,
      }),
    });

    if (!response.ok) {
      if (response.status === 401) {
        window.dispatchEvent(new CustomEvent('finsight:unauthorized'));
        window.location.assign('/login');
        return;
      }
      const errText = await response.text().catch(() => 'Unknown HTTP error');
      throw new Error(`Server returned HTTP ${response.status}: ${errText}`);
    }

    if (!response.body) {
      throw new Error('Response body is empty');
    }

    let receivedTerminalRecord = false;
    for await (const chunk of readNdjson<ChatChunk>(response.body)) {
      if (!chunk || !ALLOWED_CHAT_CHUNK_TYPES.has(chunk.type)) {
        throw new Error('The server returned an invalid response. Please try again.');
      }
      if (chunk.type === 'metadata' || chunk.type === 'error') {
        receivedTerminalRecord = true;
      }
      onChunk(chunk);
    }
    if (!receivedTerminalRecord) {
      throw new Error('The response was interrupted before completion. Please try again.');
    }

    onComplete();
  } catch (err: unknown) {
    if (signal?.aborted) return;
    onError(err instanceof Error ? err : new Error('The connection was interrupted. Please try again.'));
  }
}
