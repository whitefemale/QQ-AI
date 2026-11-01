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
  live_health: LiveHealth | null
  created_at: string
  updated_at: string
}

/** 进程内适配器的即时状态；数据库中的 status 可能滞后，不能单独当作真实在线证据。 */
export interface LiveHealth {
  status?: string
  mode?: string
  connected?: boolean
  connected_at?: string | null
  heartbeat_age_seconds?: number | null
  identity_verified?: boolean
  identity_verified_at?: string | null
  self_platform_user_id?: string | null
  status_source?: string
  observed_at?: string | null
  last_error_code?: string | null
  last_error_message?: string | null
  [key: string]: unknown
}

export type ConnectionCheckState = 'ok' | 'warning' | 'failed' | 'skipped' | 'not_verified'
export type DiagnosticsState = 'failed' | 'identity_verified' | 'mock_only'

export interface DiagnosticCheck {
  id: string
  label: string
  state: ConnectionCheckState
  detail: string
  error_code?: string | null
  duration_ms?: number | null
  next_step?: string | null
  source?: string
}

/** 测试连接的完整结果；ok 仅代表必需检查通过，不代表真实 QQ 收发已验证。 */
export interface ConnectionDiagnostics {
  ok: boolean
  state: DiagnosticsState
  connection_mode: string
  is_mock: boolean
  tested_at: string
  latency_ms: number
  checks: DiagnosticCheck[]
  login: { user_id?: string; nickname?: string; source?: string } | null
  groups: Array<{ group_id: string; group_name: string | null }>
  group_count: number
  identity_verified: boolean
  action_path_verified: boolean
  group_list_verified: boolean
  real_inbound_verified: boolean
  real_outbound_verified: boolean
  message_send_attempted: boolean
  verified_scope: string[]
  unverified_scope: string[]
  error_code: string | null
  error_message: string | null
  next_step: string | null
  note: string
}

/** 接入向导：后端只返回计数、枚举、布尔值与时间，不包含 QQ 号、名称或端点。 */
export type OnboardingOverall = 'ready_real' | 'ready_mock_only' | 'action_required' | 'blocked'
export type OnboardingStepState =
  | 'done'
  | 'action_required'
  | 'optional'
  | 'blocked'
  | 'mock_only'
  | 'not_verified'
export type OnboardingFreshness = 'fresh' | 'aging' | 'stale' | 'missing' | 'not_applicable'

export interface OnboardingStep {
  key: string
  order: number
  title: string
  state: OnboardingStepState
  summary: string
  next_step: string | null
  route: string
  freshness: OnboardingFreshness | string
  evidence: Record<string, unknown>
}

export interface OnboardingPayload {
  schema_version: string
  checked_at: string
  overall: OnboardingOverall
  ready_for_replies: boolean
  mock_only: boolean
  global_paused: boolean
  steps: OnboardingStep[]
  warnings: string[]
  blockers: string[]
  next_action: { key: string; label: string; route: string } | null
  notes: string[]
}

/** 只读诊断摘要：allowlist 字段，完整日志只在本地。 */
export interface DiagnosticsPayload {
  schema_version: string
  generated_at: string
  excluded: string[]
  app: { version: string; env: string }
  readiness: {
    database: boolean
    credential_key_configured: boolean
    global_paused: boolean
    global_pause_updated_at: string | null
    event_stream_subscribers: number
  }
  counts: {
    accounts: number
    adapter_instances: number
    groups: number
    personas: number
    providers: number
    messages: number
    memories: number
    memory_candidates: number
    media_assets: number
    outbox_messages: number
  }
  accounts: {
    modes: { mock: number; onebot11: number; other: number }
    live_online_instances: number
    identity_confirmed_instances: number
    connected_unverified_instances: number
  }
  connectors: {
    installation_count: number
    states: Array<{ state: string; count: number }>
    identity_confirmed: number
    real_traffic_verified: number
    real_qq_verified: boolean
  }
  providers: {
    total: number
    mock: number
    real: number
    real_config_complete: number
    real_test_passed: number
    real_test_failed: number
    real_never_tested: number
  }
  groups: {
    total: number
    enabled: number
    observe_only: number
    auto_reply_modes: number
    paused: number
    provider_resolved: number
    provider_unresolved: number
  }
  messages: {
    received: number
    observed: number
    replied: number
    sent: number
    outbox_pending: number
    outbox_failed: number
  }
  connection_test: {
    last_outcome: string | null
    last_state: string | null
    last_source: string | null
    tested_at: string | null
    age_seconds: number | null
    freshness: string
    identity_verified: boolean
    action_path_verified: boolean
    group_list_verified: boolean
    real_inbound_verified: boolean
    real_outbound_verified: boolean
    message_send_attempted: boolean
  }
  recent_audit_actions: Array<{ action: string; count: number }>
  text: string
}

/** `/api/accounts/{id}/status` 快照；实时状态只来自进程内适配器。 */
export interface AccountStatusSnapshot {
  account: Account
  global_pause: GlobalPause
  note: string
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
  max_reply_chars: number | null
  max_reply_chars_effective?: number
  context_message_limit: number | null
  context_message_limit_effective?: number
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

export interface PersonaChange {
  field: string
  label: string
  before: unknown
  after: unknown
}

export interface PersonaTraitDiffItem {
  trait_key: string
  trait_value?: string
  category?: string | null
  confidence?: number
  evidence_count?: number
  source_scope?: string
  status?: string
}

export interface PersonaDiff {
  fields: PersonaChange[]
  traits: {
    added: PersonaTraitDiffItem[]
    changed: Array<{ trait_key: string; source_scope: string; before: PersonaTraitDiffItem; after: PersonaTraitDiffItem }>
    removed: PersonaTraitDiffItem[]
  }
  impact: {
    field_changes: number
    traits_added: number
    traits_changed: number
    traits_removed: number
    description_changed: boolean
    scopes: string[]
    locked_fields: string[]
    skipped_locked: string[]
  }
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
  old_state?: Record<string, unknown>
  new_state?: Record<string, unknown>
  diff?: PersonaDiff
  impact?: PersonaDiff['impact']
}

export interface PersonaPreview {
  saved: false
  before: Record<string, unknown>
  after: Record<string, unknown>
  changes: PersonaChange[]
  diff: PersonaDiff
  note: string
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

export interface PersonaVersionDetail extends PersonaVersion {
  snapshot: Record<string, unknown>
  current: Record<string, unknown>
  diff: PersonaDiff
  note: string
}

export interface PersonaEvidenceItem {
  id: string
  missing: boolean
  sender_name: string | null
  timestamp: string | null
  group_id: string | null
  group_name: string | null
  preview: string
}

export interface PersonaEvidencePayload {
  items: PersonaEvidenceItem[]
  missing_count?: number
  note: string
}

export interface PersonaTemplate {
  key: string
  name: string
  description: string
  self_description: string
}

export type ProviderTestKind = 'connectivity' | 'generation'
export type ProviderTestOutcome = 'success' | 'failure' | 'cancelled'
export type ProviderCostStatus = 'estimated' | 'mock_zero' | 'unavailable'

export interface ProviderTestUsage {
  input_tokens: number | null
  output_tokens: number | null
  total_tokens: number | null
  estimated_cost: number | null
  currency: string
  cost_status: ProviderCostStatus
  note: string
}

/** 后端持久化的测试证据白名单；不含提示词、Key 或完整响应体。 */
export interface ProviderTestRecord {
  kind: ProviderTestKind
  outcome: ProviderTestOutcome
  ok: boolean
  tested_at: string
  latency_ms: number | null
  attempts: number
  model: string | null
  is_mock: boolean
  error_code: string | null
  message: string | null
  reply_preview: string | null
  upstream_request_id: string | null
  usage: ProviderTestUsage | null
}

export interface ProviderTestResult extends ProviderTestRecord {
  provider_id: string
  provider_type: string
  provider_enabled: boolean
  billable: boolean
  operation_id: string | null
  retryable: boolean
  retry_after_seconds: number | null
  next_step: string | null
  text: string | null
}

export interface ProviderModel {
  id: string
  display_name: string | null
  created_at: string | null
  owned_by: string | null
}

export type ProviderModelListState =
  | 'available'
  | 'unsupported'
  | 'mock'
  | 'not_configured'
  | 'auth_failed'
  | 'rate_limited'
  | 'network_error'
  | 'timeout'
  | 'invalid_response'
  | 'error'

export interface ProviderModelList {
  supported: boolean
  state: ProviderModelListState | string
  models: ProviderModel[]
  current_model_listed: boolean | null
  truncated: boolean
  fetched_at: string | null
  message: string | null
  error_code: string | null
  note: string | null
}

export interface LLMProvider {
  id: string
  name: string
  provider_type: string
  base_url: string | null
  model: string | null
  api_key_configured: boolean
  api_key_masked: string
  timeout_seconds: number
  max_output_tokens: number
  temperature: number
  is_default: boolean
  enabled: boolean
  status: string
  is_mock: boolean
  config_complete: boolean
  config?: Record<string, number>
  last_tested_at?: string | null
  last_error?: string | null
  last_test?: ProviderTestRecord | null
  last_generation?: ProviderTestRecord | null
  cost_tracking?: 'configured' | 'mock_zero' | 'unconfigured'
  cost_pricing_configured?: boolean
  created_at?: string
}

export interface MediaProvider {
  provider_id: string
  provider_type: string
  name: string
  version: string
  capabilities: string[]
  config_schema?: Record<string, unknown>
  enabled: boolean
  status: string
  health_status: string
  is_mock: boolean
  planned: boolean
  last_error: string | null
  last_health_check_at: string | null
  limits?: Record<string, unknown>
}

export type MediaExecution = 'job' | 'contract_only'

export interface CapabilityEntry {
  capability: string
  provider_type: string
  state: string
  /** job = 任务队列真实执行；contract_only = 仅有接口与 Mock，队列不执行。 */
  execution: MediaExecution
  source: string
  checked_at: string
  available_provider_ids: string[]
  enabled_provider_ids: string[]
  providers: MediaProvider[]
  last_error: string | null
  note: string
  next_step: string
}

export interface MediaProviderToggleResult extends MediaProvider {
  cancelled_jobs: number
  cancelled_capabilities: string[]
  cancellation_error?: string | null
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
  origin_member_platform_user_id?: string | null
  reply_kind?: string
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
  request_id?: string | null
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

export interface MemorySourceItem {
  id: string
  missing: boolean
  sender_name: string | null
  timestamp: string | null
  group_id: string | null
  group_name: string | null
  preview: string
}

export interface MemorySourcesPayload {
  items: MemorySourceItem[]
  missing_count?: number
  note: string
}

export interface MemoryCleanupResult {
  mode: string
  dry_run: boolean
  matched: number
  deleted: number
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
  /** 内置工具在进程内执行；不存在外部代码加载。 */
  execution?: 'in_process'
  registration?: 'fixed_at_startup'
  authorization?: string
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
  /** builtin_in_process = 内置插件；not_executed = 只登记清单，不加载代码。 */
  execution?: 'builtin_in_process' | 'not_executed'
  runtime_requirements?: PluginRuntimeRequirement[]
}

export interface PluginRuntimeRequirement {
  key: string
  state: string
  note: string
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

export interface BackupVerifyResult {
  filename: string
  size_bytes: number
  sha256: string
  checksum_ok: boolean
  integrity_ok: boolean
  integrity_message: string
  schema_version: string
  tables: Record<string, number>
  verified_at: string
}

/** 备份 Schema 与当前程序 Alembic head 的兼容性判定。 */
export interface SchemaCompatibility {
  backup_revision: string | null
  current_revision: string | null
  head_revision: string | null
  status: 'compatible' | 'unknown' | 'incompatible'
  compatible: boolean
  restore_allowed: boolean
  message: string
}

export interface BackupRestorePreview {
  backup: BackupRecord & { manifest?: Record<string, unknown> }
  verification: BackupVerifyResult
  schema: SchemaCompatibility
  app_version: { backup: string; current: string }
  current_state: { accounts: number }
  requires_pause: boolean
  paused: boolean
  confirm_phrase: string
  warnings: string[]
}

/** 只读清理预览：某时刻的快照，不删除数据。 */
export interface RetentionPreview {
  generated_at: string
  running: boolean
  retention_days: Record<string, number>
  counts: {
    messages_expired: number
    messages_will_delete: number
    messages_remaining_after: number
    messages_with_media: number
    media_expired: number
    logs: number
    memories: number
  }
  memory_retention_enabled: boolean
  limits: { batch_size: number; max_batches: number; max_messages_per_run: number }
  truncated: boolean
  notes: string[]
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
    interface?: string
    capabilities?: Record<string, unknown>
  }>
  features: Array<{ key: string; state: string; note: string }>
}

export interface ExtensionContract {
  kind: 'chat_adapter' | 'llm_provider' | 'media_provider' | 'tool' | 'plugin'
  interface: string
  state: string
  execution: string
  implementations: string[]
  planned?: string[]
  pipeline_dependency: string
  guarantees: string[]
}

export interface ExtensionCapabilitiesPayload {
  contracts: ExtensionContract[]
  media: CapabilityEntry[]
  tools: ToolRecord[]
  plugins: PluginRecord[]
  checked_at: string
  notes: string[]
}

// ---------------------------------------------------------------------------
// 连接器管理（仅本机回环）
// ---------------------------------------------------------------------------

export type ConnectorStateName =
  | 'not_installed'
  | 'installing'
  | 'installer_ready'
  | 'installer_running'
  | 'installed_not_started'
  | 'starting'
  | 'waiting_login'
  | 'logged_in_not_connected'
  | 'connected_traffic_unverified'
  | 'traffic_verified'
  | 'interrupted'
  | 'running_unmanaged'
  | 'auth_failed'
  | 'incompatible'
  | 'external_readonly'
  | 'unknown_error'

export interface ConnectorEvidence {
  source: string
  detail: string
  kind: string
  observed_at: string
}

export interface ConnectorState {
  state: ConnectorStateName | string
  severity: string
  inferred: boolean
  evidence: ConnectorEvidence[]
  next_steps: string[]
}

export interface ConnectorProcessInfo {
  owned: boolean
  alive: boolean
  started_at: string | null
}

export interface ConnectorConfigFileSummary {
  relative_path: string
  name: string
  exists: boolean
  size: number
  account_id: string | null
  parseable: boolean
  error: string | null
}

export interface ConnectorInstanceSummary {
  id: string
  account_id: string
  name: string
  connection_mode: string
  endpoint: string | null
  api_endpoint: string | null
  status: string
  auto_connect: boolean
  token_masked: string
  identity_confirmed_user_id: string | null
  identity_confirmed_at: string | null
}

export interface ConnectorInstallation {
  id: string
  kind: string
  display_name: string
  version: string
  source: string
  managed: boolean
  active: boolean
  layout_confidence: string
  shell_installed: boolean
  installer_ready: boolean
  version_compatibility: string
  auto_configure_allowed: boolean
  documented_config_version: string
  root_path: string
  shell_path: string | null
  config_files: ConnectorConfigFileSummary[]
  license: Record<string, unknown>
  installer_launched_at: string | null
  last_seen_at: string | null
  last_state: string | null
  state: ConnectorState
  next_steps: string[]
  can_start: boolean
  can_stop: boolean
  can_configure: boolean
  can_run_installer: boolean
  can_activate: boolean
  can_diagnose: boolean
  real_traffic_verified: boolean
  process: ConnectorProcessInfo
  installer: ConnectorProcessInfo
  ports: number[]
  port_listening: boolean
  active_job: { id: string; state: string; stage: string; progress: number } | null
  instance: ConnectorInstanceSummary | null
}

export interface ConnectorJob {
  id: string
  kind: string
  version: string
  target_name: string
  state: string
  stage: string
  progress: number
  message: string
  error_code: string | null
  error_message: string | null
  cancel_requested: boolean
  log_tail: string
  can_cancel: boolean
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface ConnectorSummary {
  installations: ConnectorInstallation[]
  recent_jobs: ConnectorJob[]
  global_pause: GlobalPause
  counts: Record<string, number>
  active_installation_id: string | null
  staging_orphans: string[]
  note: string
}

export interface ConnectorCapabilities {
  local_only: boolean
  platform_supported: boolean
  process_control_supported: boolean
  installer_script_available: boolean
  connector_kind: string
  display_name: string
  release_asset_name: string
  documented_config_version: string
  supports: Record<string, boolean>
  root_exists: boolean
  staging_orphans: string[]
  real_qq_verified: boolean
  notes: string[]
}

export interface ConnectorRelease {
  version: string
  asset_name: string | null
  size: number | null
  digest: string | null
  published_at?: string | null
  license: Record<string, unknown>
  version_compatibility: string
  auto_configure_allowed: boolean
}

export interface ConnectorConfigPreview {
  installation_id: string
  version: string
  version_compatibility: string
  auto_configure_allowed: boolean
  target_file: string | null
  target_exists: boolean
  available_files: ConnectorConfigFileSummary[]
  existing_managed_entries: Array<Record<string, unknown>>
  preserved_root_keys: string[]
  preserved_network_keys: string[]
  planned_ports: { http: number | null; websocket: number | null }
  token_masked: string
  token_will_be_generated: boolean
  process_stopped: boolean
  can_apply: boolean
  reasons: string[]
  notes: string[]
}

export interface ConnectorSnapshot {
  id: string
  snapshot_group: string
  relative_path: string
  sha256: string
  reason: string
  created_at: string
  restored_at: string | null
}
