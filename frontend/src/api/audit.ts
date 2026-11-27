import client from './client';
import type { AuditLogRecord, AuditSummary } from '../types';

export interface AuditLogFilters {
  username?: string;
  event_type?: string;
  outcome?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface AuditLogsPage {
  total: number;
  limit: number;
  offset: number;
  records: AuditLogRecord[];
}

export async function fetchAuditLogs(filters: AuditLogFilters = {}): Promise<AuditLogsPage> {
  const params = Object.fromEntries(
    Object.entries(filters).filter(([, v]) => v !== undefined && v !== null && v !== '')
  );
  const res = await client.get<AuditLogsPage>('/audit-logs', { params });
  return res.data;
}

export async function fetchAuditSummary(days = 30): Promise<AuditSummary> {
  const res = await client.get<AuditSummary>('/audit-logs/summary', { params: { days } });
  return res.data;
}

export async function downloadAuditExport(
  format: 'csv' | 'ndjson',
  filters: Omit<AuditLogFilters, 'limit' | 'offset'> = {}
): Promise<void> {
  const params = Object.fromEntries(
    Object.entries({ ...filters, format }).filter(([, v]) => v !== undefined && v !== null && v !== '')
  );
  const response = await client.get('/audit-logs/export', {
    params,
    responseType: 'blob',
  });
  const mime = format === 'csv' ? 'text/csv;charset=utf-8' : 'application/x-ndjson';
  const url = URL.createObjectURL(new Blob([response.data], { type: mime }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `finsight-audit-logs.${format}`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 10000);
}
