export type MemoryNode = {
  id: string;
  kind: "entity" | "fact" | "pattern" | "summary";
  text: string;
  source_ids: string[];
  scope_key: string;
  first_seen_at: string;
  last_seen_at: string;
  group_id?: string | null;
};
export type MemoryEdge = {
  id: string;
  source_id: string;
  target_id: string;
  relation: string;
  weight: number;
};
export type SourceRecord = {
  id: string;
  text: string;
  occurred_at: string;
  available_at: string;
  metadata: Record<string, unknown>;
};
export type TraceEvent = {
  run_id: string;
  sequence: number;
  simulated_at: string;
  type: string;
  payload: Record<string, unknown>;
};
export type Context = {
  seed_ids: string[];
  source_ids: string[];
  token_count: number;
  truncated: boolean;
  context_text: string;
  nodes: MemoryNode[];
  edges: MemoryEdge[];
};
export type ResponseResult = {
  text: string;
  current_source_ids: string[];
  historical_source_ids: string[];
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
};
export type Batch = {
  number: number;
  as_of: string;
  record_ids: string[];
  node_count: number;
  edge_count: number;
  events: TraceEvent[];
};
export type DashboardData = {
  mode: "replay" | "live";
  generated_at: string;
  adapter: string;
  record_count: number;
  batch_size: number;
  batches: Batch[];
  records: SourceRecord[];
  nodes: MemoryNode[];
  edges: MemoryEdge[];
  baseline: ResponseResult;
  memory: ResponseResult;
  context: Context;
  prompt: string;
};
export type Message = {
  id: string;
  session_id: string;
  turn_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};
export type Configuration = {
  memory_api: boolean;
  model: boolean;
  model_name: string | null;
};
