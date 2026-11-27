import type React from 'react';
import type { RagasEvalRecord } from '../../types';

export const ROLE_COLORS: Record<string, string> = {
  'c-level': '#F59E0B',
  clevel: '#F59E0B',
  hr: '#10B981',
  finance: '#3B82F6',
  engineering: '#A78BFA',
  marketing: '#EC4899',
  general: '#64748B',
};

export const THRESHOLDS: Record<string, { pass: number; warn: number }> = {
  faithfulness: { pass: 0.75, warn: 0.85 },
  answer_relevancy: { pass: 0.70, warn: 0.75 },
  context_precision: { pass: 0.65, warn: 0.70 },
  context_recall: { pass: 0.70, warn: 0.75 },
  answer_correctness: { pass: 0.60, warn: 0.65 },
};

export const METRIC_KEYS = [
  'faithfulness',
  'answer_relevancy',
  'context_precision',
  'context_recall',
  'answer_correctness',
] as const;

export const checkMetricStatus = (
  metric: string,
  val: number | undefined
): 'pass' | 'warn' | 'fail' | 'neutral' => {
  if (val === undefined || val === null) return 'neutral';
  const key = metric.toLowerCase().replace(/\s+/g, '_');
  const t = THRESHOLDS[key];
  if (!t) return 'neutral';
  if (val >= t.warn) return 'pass';
  if (val >= t.pass) return 'warn';
  return 'fail';
};

export const getMetricColor = (status: 'pass' | 'warn' | 'fail' | 'neutral') => {
  switch (status) {
    case 'pass':
      return '#10B981';
    case 'warn':
      return '#F59E0B';
    case 'fail':
      return '#EF4444';
    default:
      return '#64748B';
  }
};

export const getMetricBgClass = (status: 'pass' | 'warn' | 'fail' | 'neutral') => {
  switch (status) {
    case 'pass':
      return 'rgba(16, 185, 129, 0.1)';
    case 'warn':
      return 'rgba(245, 158, 11, 0.1)';
    case 'fail':
      return 'rgba(239, 68, 68, 0.1)';
    default:
      return 'rgba(255, 255, 255, 0.03)';
  }
};

export const getStatusBadgeStyle = (status: string): React.CSSProperties => {
  const clean = status.toLowerCase();
  if (clean === 'completed' || clean === 'passed' || clean === 'safe' || clean === 'allow') {
    return {
      background: 'rgba(16, 185, 129, 0.12)',
      color: '#34D399',
      border: '1px solid rgba(16, 185, 129, 0.25)',
    };
  }
  if (clean === 'running' || clean === 'queued' || clean === 'cancel_requested' || clean === 'redact') {
    return {
      background: 'rgba(245, 158, 11, 0.12)',
      color: '#FBBF24',
      border: '1px solid rgba(245, 158, 11, 0.25)',
    };
  }
  if (clean === 'failed' || clean === 'block' || clean === 'deny') {
    return {
      background: 'rgba(239, 68, 68, 0.12)',
      color: '#F87171',
      border: '1px solid rgba(239, 68, 68, 0.25)',
    };
  }
  if (clean === 'cached') {
    return {
      background: 'rgba(59, 130, 246, 0.12)',
      color: '#93C5FD',
      border: '1px solid rgba(59, 130, 246, 0.25)',
    };
  }
  return {
    background: 'rgba(255, 255, 255, 0.05)',
    color: 'var(--text-muted)',
    border: '1px solid rgba(255,255,255,0.08)',
  };
};

export const getOverallRecordStatus = (rec: RagasEvalRecord): 'pass' | 'warn' | 'fail' => {
  let hasFail = false;
  let hasWarn = false;
  let hasAnyMetric = false;

  for (const m of METRIC_KEYS) {
    const val = rec[m as keyof RagasEvalRecord] as number | undefined;
    if (val !== undefined && val !== null) {
      hasAnyMetric = true;
      const status = checkMetricStatus(m, val);
      if (status === 'fail') hasFail = true;
      if (status === 'warn') hasWarn = true;
    }
  }

  if (!hasAnyMetric) return 'pass';
  if (hasFail) return 'fail';
  if (hasWarn) return 'warn';
  return 'pass';
};
