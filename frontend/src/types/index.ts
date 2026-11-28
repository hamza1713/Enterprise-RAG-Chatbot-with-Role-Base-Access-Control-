export interface User {
  username: string;
  role: string;
  auth_provider?: string;
}

export interface AuthProvidersResponse {
  local_enabled: boolean;
  oidc_enabled: boolean;
  provider_name: string;
}

export interface AgentStep {
  node: string;
  label: string;
  status: 'running' | 'done' | 'error';
  detail?: string;
}

export interface CitationItem {
  index: number;
  chunk_id: string;
  doc_id?: number | null;
  source: string;
  page_number?: string | null;
  section_title?: string | null;
  chunk_type?: string | null;
  parser_used?: string | null;
  snippet: string;
}

export interface ChartSpec {
  type: 'bar' | 'line' | 'area' | 'pie' | 'none';
  title: string;
  xKey: string;
  yKeys: string[];
  rows: Record<string, string | number | boolean | null>[];
}

export interface ChatThread {
  id: string;
  username: string;
  title: string;
  archived: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ThreadMessageRecord {
  id: number;
  thread_id: string;
  role: MessageRole;
  content: string;
  mode?: string | null;
  sql?: string | null;
  chart_spec?: ChartSpec | null;
  citations?: CitationItem[];
  agent_steps?: AgentStep[];
  created_at?: string | null;
}

export interface DocumentPermission {
  id: number;
  subject: string;
  relation: string;
  object_type: string;
  object_id: string;
  created_by?: string | null;
  created_at?: string | null;
}

export interface SemanticMetric {
  name: string;
  label?: string;
  expression: string;
  column?: string;
  description?: string;
}

export interface SemanticModel {
  id?: number;
  table_name: string;
  doc_id?: number | null;
  display_name: string;
  description: string;
  metrics: SemanticMetric[];
  dimensions: { name: string; type?: string; description?: string }[];
  synonyms: Record<string, string>;
  joins: { target_table: string; condition: string }[];
  updated_by?: string | null;
  updated_at?: string | null;
}

export interface RoleDetail {
  id?: number;
  role_name: string;
  is_system: boolean;
}

export interface UserRecord {
  id: number;
  username: string;
  role: string;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export type MessageRole = 'user' | 'assistant';

export interface Message {
  role: MessageRole;
  content: string;
  mode?: string;
  sql?: string | null;
  sources?: string[];
  citations?: CitationItem[];
  chart_spec?: ChartSpec | null;
  agent_steps?: AgentStep[];
  fallback?: boolean;
}

export interface Document {
  id?: number;
  filename: string;
  role: string;
  filepath: string;
  object_key?: string;
  headers_str: string | null;
  embedded?: number;
  parser_used?: string | null;
  size_bytes?: number;
  created_at?: string | null;
}

export interface SystemMetrics {
  docs: number;
  users: number;
  roles: number;
  tables: number;
  active_jobs?: number;
}

export interface DocIndexingDetail {
  id: number;
  filename: string;
  role: string;
  status: 'indexed' | 'pending' | 'failed' | 'unknown';
  total_chunks: number;
  embedded_chunks: number;
  parser_used?: string | null;
  last_error?: string | null;
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

export interface JobRecord {
  id: string;
  job_type: 'index_doc' | 'full_reindex' | 'retry_indexing' | 'evaluation' | string;
  target_doc_id?: number | null;
  requested_by?: string | null;
  status: 'queued' | 'running' | 'cancel_requested' | 'cancelled' | 'completed' | 'failed' | string;
  attempts: number;
  max_attempts: number;
  progress_current: number;
  progress_total: number;
  progress_message?: string | null;
  payload?: Record<string, any> | null;
  result?: Record<string, any> | null;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
}

export interface RagasScores {
  context_precision?: number;
  faithfulness?: number;
  answer_relevancy?: number;
  context_recall?: number;
  [key: string]: number | undefined;
}

export interface EvalStatusResponse {
  status: 'never_run' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  job_status?: string | null;
  job_id?: string | null;
  run_id?: string | null;
  mode?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  overall?: RagasScores;
  per_role?: Record<string, RagasScores>;
  pass_fail?: Record<string, 'pass' | 'fail' | 'warn'>;
  rbac_overall?: string;
  report_available: boolean;
  error?: string | null;
}

export interface RagasEvalRecord {
  user_input: string;
  response: string;
  retrieved_contexts: string | string[];
  reference: string;
  faithfulness?: number;
  answer_relevancy?: number;
  context_precision?: number;
  context_recall?: number;
  answer_correctness?: number;
  role: string;
  source?: string;
}

export interface AuditLogRecord {
  id: number;
  event_id: string;
  request_id: string;
  thread_id?: string | null;
  username: string;
  user_role: string;
  auth_provider: string;
  event_type: string;
  mode?: string | null;
  model_name?: string | null;
  authorized_doc_count: number;
  authorized_dataset_names: string[];
  cited_doc_ids: number[];
  cited_chunk_ids: string[];
  sql_executed?: string | null;
  sql_retries: number;
  guardrail_flags: string[];
  outcome: 'allow' | 'block' | 'redact' | 'cached' | 'deny' | string;
  latency_ms: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  prompt_sha256?: string | null;
  prompt_preview?: string | null;
  ai_disclosure: boolean;
  created_at?: string | null;
}

export interface AuditSummary {
  window_days: number;
  total_events: number;
  chat_turns: number;
  blocked_injections: number;
  pii_redactions: number;
  sql_executions: number;
  sql_retries: number;
  sql_retry_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  outcomes: Record<string, number>;
  event_types: Record<string, number>;
}
