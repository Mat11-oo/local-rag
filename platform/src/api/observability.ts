import { apiFetch } from './client';

export type RunStatus = 'running' | 'success' | 'failed';

export type RunItem = {
  id: string;
  trace_id: string;
  app_id: string | null;
  app_name: string | null;
  conversation_id: string | null;
  message_id: string | null;
  query: string;
  status: RunStatus;
  channel: string;
  model_name: string | null;
  app_version: number | null;
  app_version_id: string | null;
  duration_ms: number | null;
  tokens: { input: number | null; output: number | null; total: number | null };
  cost: number | null;
  currency: string;
  error_message: string | null;
  handoff: boolean;
  simulated: boolean;
  feedback: number | null;
  started_at: string;
  finished_at: string | null;
  step_count: number;
  model_calls: number;
  tool_calls: number;
  retrievals: number;
  errors: number;
};

export type Span = {
  id: string;
  ordinal: number;
  kind: 'context' | 'retrieval' | 'model' | 'tool' | 'handoff' | 'guardrail' | 'harness' | 'error' | string;
  name: string;
  status: string;
  duration_ms: number;
  detail: string;
  metadata: Record<string, unknown>;
};

export type RunDetail = RunItem & {
  input_values: Record<string, unknown>;
  output: string | null;
  citations: Array<{ filename: string; title: string; content: string; score: number; page_number: number | null }>;
  history_messages: number;
  run_metadata: Record<string, unknown>;
  feedback_items: Array<{ rating: number; comment: string; created_at: string }>;
  spans: Span[];
};

export type Overview = {
  days: number;
  runs: { total: number; success: number; failed: number; success_rate: number | null; p50_ms: number | null; p95_ms: number | null; handoff: number };
  tokens: { input: number; output: number; total: number };
  cost: { total: number | null; priced_runs: number; unpriced_runs: number };
  feedback: { up: number; down: number };
  builds: { total: number; completed: number; failed: number; running: number };
  daily: Array<{ date: string; runs: number; failed: number; tokens: number; cost: number }>;
  top_apps: Array<{ app_id: string; app_name: string; runs: number; failed: number }>;
  recent_failures: Array<{ trace_id: string; app_id: string | null; app_name: string | null; query: string; error_message: string | null; started_at: string; channel: string }>;
};

export type ConversationItem = {
  id: string;
  app_id: string;
  app_name: string;
  title: string;
  user_id: string | null;
  demo_role: string;
  turns: number;
  tokens: number;
  cost: number | null;
  failed_runs: number;
  feedback: { up: number; down: number };
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = Omit<ConversationItem, 'turns' | 'tokens' | 'cost' | 'failed_runs' | 'feedback'> & {
  messages: Array<{
    id: string;
    role: 'user' | 'assistant';
    content: string;
    citations: RunDetail['citations'];
    input_values: Record<string, unknown>;
    tokens: { input: number | null; output: number | null };
    duration_ms: number | null;
    trace_id: string | null;
    cost: number | null;
    feedback: number | null;
    created_at: string;
  }>;
  failed_runs: Array<{ trace_id: string; query: string; error_message: string | null; started_at: string }>;
};

export type BuildJob = {
  id: string;
  file_id: string;
  filename: string;
  extension: string;
  size_bytes: number;
  knowledge_base_id: string;
  knowledge_base_name: string;
  status: string;
  progress: number;
  current_stage: string;
  stage_details: Array<{ name: string; status: string; detail: string }>;
  error_message: string | null;
  chunk_count: number;
  chunk_method: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type UsageRow = { key: string; name: string; runs: number; failed: number; input_tokens: number; output_tokens: number; total_tokens: number; cost: number | null; priced_runs: number; avg_duration_ms: number | null };
export type Usage = { days: number; group_by: string; currency: string; totals: { runs: number; input_tokens: number; output_tokens: number; total_tokens: number; cost: number | null; priced_runs: number }; items: UsageRow[] };

type Params = Record<string, string | number | undefined | null>;

function qs(params: Params) {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '');
  return entries.length ? `?${new URLSearchParams(entries.map(([key, value]) => [key, String(value)])).toString()}` : '';
}

export const obsApi = {
  overview: (params: Params = {}) => apiFetch<Overview>(`/observability/overview${qs(params)}`),
  runs: (params: Params = {}) => apiFetch<{ total: number; items: RunItem[] }>(`/observability/runs${qs(params)}`),
  run: (traceId: string) => apiFetch<RunDetail>(`/observability/runs/${traceId}`),
  conversations: (params: Params = {}) => apiFetch<{ total: number; items: ConversationItem[] }>(`/observability/conversations${qs(params)}`),
  conversation: (id: string) => apiFetch<ConversationDetail>(`/observability/conversations/${id}`),
  buildJobs: (params: Params = {}) => apiFetch<{ total: number; summary: { total: number; completed: number; failed: number; running: number }; items: BuildJob[] }>(`/observability/build-jobs${qs(params)}`),
  usage: (params: Params = {}) => apiFetch<Usage>(`/observability/usage${qs(params)}`),
};

export const CHANNEL_LABEL: Record<string, string> = { web: '工作台', debug: '调试', share: '分享链接', api: 'API', evaluation: '评测' };
