import client from './client';
import type { JobRecord } from '../types';

export async function fetchJobs(params?: {
  job_type?: string;
  status?: string;
  limit?: number;
}): Promise<JobRecord[]> {
  const res = await client.get<{ jobs: JobRecord[] }>('/jobs', { params });
  return res.data.jobs || [];
}

export async function cancelJob(jobId: string): Promise<JobRecord> {
  const res = await client.post<JobRecord>(`/jobs/${encodeURIComponent(jobId)}/cancel`);
  return res.data;
}

export async function retryJob(jobId: string): Promise<JobRecord> {
  const res = await client.post<JobRecord>(`/jobs/${encodeURIComponent(jobId)}/retry`);
  return res.data;
}
