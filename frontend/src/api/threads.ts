import client from './client';
import type { ChatThread, ThreadMessageRecord } from '../types';

export async function fetchThreads(): Promise<ChatThread[]> {
  const res = await client.get<{ threads: ChatThread[] }>('/threads');
  return res.data.threads || [];
}

export async function createThread(title = 'New Conversation'): Promise<ChatThread> {
  const res = await client.post<ChatThread>('/threads', { title });
  return res.data;
}

export async function fetchThreadMessages(threadId: string): Promise<{
  thread: ChatThread;
  messages: ThreadMessageRecord[];
}> {
  const res = await client.get<{ thread: ChatThread; messages: ThreadMessageRecord[] }>(
    `/threads/${encodeURIComponent(threadId)}`
  );
  return res.data;
}

export async function renameThread(threadId: string, title: string): Promise<ChatThread> {
  const res = await client.patch<ChatThread>(`/threads/${encodeURIComponent(threadId)}`, { title });
  return res.data;
}

export async function deleteThread(threadId: string): Promise<void> {
  await client.delete(`/threads/${encodeURIComponent(threadId)}`);
}
