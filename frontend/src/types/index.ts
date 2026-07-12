export interface User {
  username: string;
  role: string;
  token: string;
}

export type MessageRole = 'user' | 'assistant';

export interface Message {
  role: MessageRole;
  content: string;
  mode?: string;
  sql?: string | null;
  sources?: string[];
  fallback?: boolean;
}

export interface Document {
  filename: string;
  role: string;
  filepath: string;
  headers_str: string | null;
}

export interface SystemMetrics {
  docs: number;
  users: number;
  roles: number;
  tables: number;
}

export interface DocIndexingDetail {
  id: number;
  filename: string;
  role: string;
  status: 'indexed' | 'pending' | 'failed' | 'unknown';
  total_chunks: number;
  embedded_chunks: number;
}

export interface BulkStatusResponse {
  summary: {
    total: number;
    done: number;
    failed: number;
    pending: number;
    complete: boolean;
  };
  documents: DocIndexingDetail[];
}

export interface RagasScores {
  context_precision?: number;
  faithfulness?: number;
  answer_relevancy?: number;
  context_recall?: number;
  [key: string]: number | undefined;
}

export interface EvalStatusResponse {
  status: 'never_run' | 'running' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  overall?: RagasScores;
  pass_fail?: Record<string, 'pass' | 'fail'>;
  rbac_overall?: string;
  report_available: boolean;
  error?: string;
}
