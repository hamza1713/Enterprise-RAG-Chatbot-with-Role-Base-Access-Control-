import { API_URL } from './client';

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
  onError: (err: any) => void
): Promise<void> {
  try {
    const response = await fetch(`${API_URL}/chat-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => 'Unknown HTTP error');
      throw new Error(`Server returned HTTP ${response.status}: ${errText}`);
    }

    if (!response.body) {
      throw new Error('Response body is empty');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      
      // Keep the last partial line in the buffer
      buffer = lines.pop() || '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const parsed: ChatChunk = JSON.parse(trimmed);
          onChunk(parsed);
        } catch (e) {
          console.error('Failed to parse NDJSON line:', trimmed, e);
        }
      }
    }

    // Process remaining buffer
    if (buffer.trim()) {
      try {
        const parsed: ChatChunk = JSON.parse(buffer.trim());
        onChunk(parsed);
      } catch (e) {
        console.error('Failed to parse final buffer line:', buffer, e);
      }
    }

    onComplete();
  } catch (err: any) {
    onError(err);
  }
}
