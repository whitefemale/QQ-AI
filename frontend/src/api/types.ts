/** 与后端 public 序列化字段保持一致的宽松类型定义。 */

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface CapabilityFlags {
  receive_group_message?: boolean
  receive_private_message?: boolean
  send_text?: boolean
  send_image?: boolean
  send_reply?: boolean
  mention_support?: boolean
  group_member_info?: boolean
  group_list?: boolean
  message_recall_event?: boolean
  file_upload?: boolean
  voice_message?: boolean
  video_message?: boolean
  typing_indicator?: boolean
  official_api?: boolean
}

export interface AdapterInstance {
  id: string
  account_id: string
  name: string
  connection_mode: string
  endpoint: string | null
  api_endpoint: string | null
  token_configured: boolean
  token_masked: string
  allow_remote: boolean
  auto_connect: boolean
  enabled: boolean
  capabilities: CapabilityFlags
  status: string
  last_heartbeat_at: string | null
  last_received_at: string | null
  last_sent_at: string | null
  heartbeat_age_seconds: number | null
  last_error_code: string | null
  last_error_message: string | null
  created_at: string
  updated_at: string
}

export interface Account {
  id: string
  display_name: string
  platform: string
  adapter_type: string
  self_platform_user_id: string | null
  enabled: boolean
  allow_private: boolean
  status: string
  notes: string | null
  instances: AdapterInstance[]
  created_at: string
  updated_at: string
}

export interface Group {
  id: string
  account_id: string
  account_name?: string | null
  platform_group_id: string
  name: string | null
  enabled: boolean
  paused: boolean
  reply_mode: string
  persona_id: string | null
  persona_name?: string | null
  llm_provider_id: string | null
  llm_provider_name?: string | null
  llm_provider_type?: string | null
  llm_provider_state: string
  llm_fallback_provider_id: string | null
  llm_fallback_provider_name?: string | null
  llm_fallback_provider_type?: string | null
  llm_fallback_provider_state: string
  allow_memory: boolean
  auto_memory_extraction: boolean
  memory_extraction_last_run_at?: string | null
  memory_extraction_last_error?: string | null
  memory_extraction_watermark_at?: string | null
  memory_extraction_watermark_message_id?: string | null
  allow_tools: boolean
  allow_proactive: boolean
  admin_user_ids: string[]
  quiet_hours: Record<string, unknown>
  rate_limit: Record<string, number>
  keywords: string[]
  group_rules_text: string | null
  timezone: string
  created_at?: string
  updated_at?: string
}

export interface Persona {
  id: string
  name: string
  mode: string
  mode_label?: string
  template_key: string | null
  self_description: string
  authored_fields: Record<string, string>
  system_prompt_overlay: string
  growth_policy: string
  growth_enabled: boolean
  learning_scope: string
  thresholds: Record<string, number>
  locked_fields: string[]
  enabled: boolean
  notes: string | null
  last_growth_at: string | null
  stable_trait_count: number
  candidate_trait_count: number
  latest_version: number
  created_at: string
  updated_at: string
}

export interface PersonaTrait {
  id: string
  persona_id: string
  trait_key: string
  trait_value: string
  category: string
  confidence: number
  evidence_count: number
  evidence_message_ids: string[]
  source_scope: string
  status: string
  locked_by_user: boolean
  created_at: string | null
}

export interface EvolutionEvent {
  id: string
  persona_id: string
  trigger_type: string
  trigger_message_id: string | null
  group_id: string | null
  summary: string
  diff_summary: string | null
  evidence_summary: string
  confidence: number
  result: string
  error_message: string | null
  reviewed_at: string | null
  created_at: string | null
  proposal: Record<string, unknown>
}

export interface PersonaVersion {
  id: string
  persona_id: string
  version_no: number
  change_summary: string
  created_by: string
  restorable: boolean
  created_at: string | null
}

export interface PersonaTemplate {
  key: string
  name: string
  description: string
  self_description: string
}

export interface LLMProvider {
  id: string
  name: string
  provider_type: string
  base_url: string | null
  model: string
  api_key_configured: boolean
  api_key_masked: string
  timeout_seconds: number
  max_output_tokens: number
  temperature: number
  is_default: boolean
  enabled: boolean
  status: string
  last_tested_at?: string | null
  last_error?: string | null
  cost_tracking?: 'configured' | 'mock_zero' | 'unconfigured'
  cost_pricing_configured?: boolean
  created_at?: string
}

export interface MediaProvider {
  id: string
  name: string
  capability: string
  provider_type: string
  is_mock: boolean
  enabled: boolean
  state: string
  note?: string
  [key: string]: unknown
}

export interface CapabilityEntry {
  capability: string
  provider_type: string
  state: string
  available_provider_ids: string[]
  providers: MediaProvider[]
  note: string
}

export interface MediaJob {
  id: string
  job_type: string
  capability: string
  media_ref: string
  provider_id: string | null
  status: string
  attempts: number
  max_attempts: number
  error_code: string | null
  error_message: string | null
  output_ref: string | null
  created_at: string | null
  finished_at: string | null
}

export type MediaCostStatus = 'complete' | 'partial' | 'unknown' | 'no_calls'

export interface MediaUsageBucket {
  provider_id?: string | null
  provider_name?: string
  capability?: string
  calls: number
  requests: number
  successful_calls: number
  failed_calls: number
  mock_calls: number
  latency_ms_avg: number
  external_cost: number | null
  cost_status: MediaCostStatus
}

export interface MediaUsageSummary {
  hours: number
  window_start: string
  window_end: string
  calls: number
  requests: number
  successful_calls: number
  failed_calls: number
  mock_calls: number
  latency_ms_avg: number
  external_cost: number | null
  cost_status: MediaCostStatus
  by_provider: MediaUsageBucket[]
  by_capability: MediaUsageBucket[]
  note: string
}

export interface MessageRecord {
  id: string
  platform_message_id: string
  account_id: string
  account_name: string | null
  group_id: string | null
  group_name: string | null
  conversation_id: string
  conversation_type: string
  sender_id: string
  sender_name: string | null
  is_self: boolean
  direction: string
  content_text: string
  segments: Array<Record<string, unknown>>
  reply_to_message_id: string | null
  event_timestamp: string
  processing_status: string
  trigger_reason: string | null
  error_code: string | null
  error_message: string | null
  model_latency_ms: number | null
  input_tokens: number | null
  output_tokens: number | null
  created_at: string
}

export interface OutboxRecord {
  id: string
  account_id: string
  group_id: string | null
  conversation_id: string
  conversation_type: string
  content: string
  status: string
  attempts: number
  max_attempts: number
  next_attempt_at: string | null
  last_error_code: string | null
  last_error_message: string | null
  sent_platform_message_id: string | null
  sent_at: string | null
  created_at: string
}

export interface UsageRecord {
  id: string
  provider_id: string | null
  provider_type: string
  model: string
  purpose: string
  group_id: string | null
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  latency_ms: number | null
  estimated_cost: number | null
  currency: string
  status: string
  error_code: string | null
  created_at: string
}

export type CostStatus = 'complete' | 'partial' | 'unconfigured' | 'not_applicable' | 'no_calls'

export interface UsageBucket {
  provider_id?: string | null
  provider_name?: string
  provider_type?: string
  model?: string | null
  is_mock?: boolean
  cost_tracking?: 'configured' | 'mock_zero' | 'unconfigured'
  group_id?: string | null
  group_name?: string
  requests: number
  successful_requests: number
  failed_requests: number
  tokens: number
  cost: number | null
  currency: string
  priced_success_requests: number
  unpriced_success_requests: number
  cost_status: CostStatus
}

export interface UsageSummary {
  hours?: number | null
  window_start: string
  window_end: string
  requests: number
  successful_requests: number
  failed_requests: number
  tokens: number
  cost: number | null
  currency: string
  priced_success_requests: number
  unpriced_success_requests: number
  cost_status: CostStatus
  cost_note: string
  by_provider: UsageBucket[]
  by_group: UsageBucket[]
}

export interface UsageTrendPoint extends UsageBucket {
  bucket_start: string
  bucket_end: string
  bucket_label: string
}

export interface UsageTrends {
  bucket: 'hour' | 'day'
  periods: number
  timezone: string
  window_start: string
  window_end: string
  items: UsageTrendPoint[]
  requests: number
  successful_requests: number
  failed_requests: number
  tokens: number
  cost: number | null
  currency: string
  priced_success_requests: number
  unpriced_success_requests: number
  cost_status: CostStatus
  cost_note: string
}

export interface BudgetAlert {
  id: string
  policy_id: string
  scope_type: string
  scope_id: string
  scope_name: string
  window: string
  metric: string
  level: 'warning' | 'exceeded'
  period_key: string
  period_start: string | null
  used: number
  limit: number
  warn_threshold: number
  usage_ratio: number
  message: string
  created_at: string
}

export interface BudgetAlertList extends Paginated<BudgetAlert> {
  note: string
}

export interface BudgetPolicy {
  id: string
  scope_type: string
  scope_id: string
  window: string
  metric: string
  limit_value: number
  warn_threshold: number
  action: string
  enabled: boolean
  used?: number
  remaining?: number
  usage_ratio?: number
  state?: 'ok' | 'warning' | 'exceeded' | 'disabled'
  period_start?: string | null
  cost_status?: CostStatus | null
  unpriced_success_requests?: number
}

export interface BudgetBlock {
  policy_id: string
  scope_type: string
  scope_id: string
  window: string
  metric: string
  limit: number
  used: number
  reason: 'limit_reached' | 'cost_unavailable'
}

export interface BudgetCheck {
  allowed: boolean
  blocks: BudgetBlock[]
  note?: string
}

export interface MemoryRecord {
  id: string
  account_id: string
  group_id: string | null
  member_id: string | null
  memory_type: string
  content: string
  source_message_ids: string[]
  confidence: number
  sensitivity: string
  is_pinned: boolean
  expires_at: string | null
  expired: boolean
  auto_injectable: boolean
  created_at: string
  updated_at: string
}

export interface MemoryListPayload extends Paginated<MemoryRecord> {
  note: string
}

export interface MemoryCandidateRecord {
  id: string
  account_id: string
  group_id: string
  member_id: string | null
  memory_type: string
  content: string
  source_message_ids: string[]
  confidence: number
  status: string
  provider_id: string | null
  provider_type: string | null
  extraction_model: string | null
  is_mock: boolean
  reviewed_at: string | null
  reviewed_by: string | null
  memory_id: string | null
  created_at: string
  updated_at: string
}

export interface MemoryCandidateListPayload extends Paginated<MemoryCandidateRecord> {
  note: string
}

export interface MemoryExtractionResult {
  scanned_messages: number
  created: MemoryCandidateRecord[]
  created_count: number
  skipped: number
  skipped_reasons: Record<string, number>
  provider_id: string | null
  provider_type: string | null
  model: string | null
  is_mock: boolean
  message: string
  note: string
}

export interface MemoryCandidateApproval {
  candidate: MemoryCandidateRecord
  memory: MemoryRecord
  note: string
}

export interface MemberRecord {
  id: string
  account_id: string
  platform_user_id: string
  display_name: string | null
  labels: string[]
  excluded_from_memory: boolean
  muted: boolean
  muted_until: string | null
  created_at: string
}

export interface ToolRecord {
  id?: string
  name: string
  description: string
  risk_level: string
  required_permissions: string[]
  timeout_seconds: number
  input_schema: Record<string, unknown>
  enabled?: boolean
  runtime_status?: string
}

export interface PluginHealthcheck {
  type: 'builtin' | 'http'
  path: string
  interval_seconds: number
  timeout_seconds: number
}

export interface PluginRecord {
  id: string
  name: string
  version: string
  description: string
  plugin_type: string
  permissions: string[]
  high_risk_permissions: string[]
  enabled: boolean
  permission_approved: boolean
  healthcheck: PluginHealthcheck | null
  healthcheck_note: string
  health_status: string
  runtime_status: string
  runtime_note: string
  entrypoint?: string | null
  last_error?: string | null
  manifest_path?: string | null
  is_builtin?: boolean
}

export interface BackupRecord {
  id: string
  filename: string
  sha256: string
  size_bytes: number
  app_version: string
  schema_version: string
  status: string
  includes_secrets: boolean
  created_at: string
  download_path: string
}

export interface GlobalPause {
  paused: boolean
  reason: string
  updated_at: string | null
  actor: string | null
}

export interface RetentionRunSummary {
  status: string
  trigger: string
  actor: string
  started_at: string | null
  finished_at: string | null
  global_pause: boolean
  truncated: boolean
  error: string | null
  retention_days: Record<string, number>
  counts: Record<string, number>
}

export interface RetentionStatus {
  auto: { enabled: boolean; source: string; config_enabled: boolean }
  running: boolean
  interval_seconds: number
  batch_size: number
  max_batches_per_run: number
  retention_days: Record<string, number>
  last_run: RetentionRunSummary | null
  scheduler: { running: boolean; interval_seconds: number; next_run_at: string | null } | null
  notes: string[]
}

export interface AppSettings {
  runtime: Record<string, unknown>
  app: { name: string; version: string; env: string; api_prefix: string }
  global_pause: GlobalPause
  retention: Record<string, number>
  retention_status: RetentionStatus
  security: {
    allow_remote_admin: boolean
    admin_token_configured: boolean
    credential_key_configured: boolean
    cors_origins: string[]
  }
  privacy: {
    counts: Record<string, number>
    notes: string[]
  }
}

export interface BusEvent {
  seq: number
  type: string
  at: string
  payload: Record<string, unknown>
}

export interface DashboardPayload {
  app: { name: string; version: string; env: string }
  accounts: { total: number; online: number }
  groups: { total: number; active: number }
  messages: { inbound_today: number; outbound_today: number; errors_today: number }
  outbox: Record<string, number>
  providers: {
    total: number
    enabled: number
    default: {
      id: string
      name: string
      model: string
      provider_type: string
      is_mock: boolean
      status: string
    } | null
  }
  usage_today: {
    requests: number
    successful_requests: number
    failed_requests: number
    tokens: number
    cost: number | null
    currency: string
    cost_status: CostStatus
    cost_note: string
    priced_success_requests: number
    unpriced_success_requests: number
    by_provider: UsageBucket[]
    by_group: UsageBucket[]
    last_24h: UsageSummary
  }
  capabilities: CapabilityEntry[]
  recent_events: BusEvent[]
  recent_messages: Array<{
    id: string
    direction: string
    sender_name: string | null
    group_id: string | null
    group_name: string | null
    preview: string
    status: string
    at: string
  }>
  usage_events: Array<{ metric: string; amount: number }>
  global_pause: GlobalPause
}

export interface CapabilitiesPayload {
  media: CapabilityEntry[]
  llm: { available: string[]; planned: string[]; note: string }
  connections: Array<{
    mode: string
    name: string
    state: string
    note: string
    capabilities?: Record<string, unknown>
  }>
  features: Array<{ key: string; state: string; note: string }>
}
