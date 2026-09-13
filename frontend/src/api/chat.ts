import { API_URL } from './client';
import { readNdjson } from './ndjson';

export interface ChatChunk {
  type: 'init' | 'fallback' | 'token' | 'metadata' | 'error';
  user?: string;
  role?: string;
  mode?: string;
  content?: string;
  sql?: string | null;
  sources?: string[];
  fallback?: boolean;
  answer?: string;
}

export async function streamChat(
  question: string,
  token: string,
  onChunk: (chunk: ChatChunk) => void,
  onComplete: () => void,
  onError: (err: Error) => void,
  signal?: AbortSignal,
  history?: { role: string; content: string }[]
): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/chat-stream`, {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ question, history: history || [] }),
    });

    if (!response.ok) {
      if (response.status === 401) {
        sessionStorage.removeItem('finsight_auth');
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
      if (!chunk || !['init', 'fallback', 'token', 'metadata', 'error'].includes(chunk.type)) {
        throw new Error('The server returned an invalid response. Please try again.');
      }
      if (chunk.type === 'metadata' || chunk.type === 'error') receivedTerminalRecord = true;
      onChunk(chunk);
    }
    if (!receivedTerminalRecord) throw new Error('The response was interrupted before completion. Please try again.');

    onComplete();
  } catch (err: unknown) {
    if (signal?.aborted) return;
    onError(err instanceof Error ? err : new Error('The connection was interrupted. Please try again.'));
  }
}
