<template>
  <div class="page">
    <PageHeader
      title="人格工作台"
      description="管理 AI 群友的身份、语气与成长治理。空白自成长从零开始，候选特征必须满足证据门槛才会进入稳定特征；系统安全规则、群规与工具权限不会被成长覆盖。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建人格</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="治理边界"
      description="成长提案不能修改系统安全规则、群规则或工具权限。单条消息不能引发人格突变；跨群学习默认关闭。所有变更生成版本快照并可回滚。"
    />

    <div class="persona-layout">
      <div class="card persona-list">
        <div class="card-title">
          <span>人格档案</span>
          <span class="muted">{{ personas.length }} 个</span>
        </div>
        <el-empty v-if="!loading && !personas.length" description="还没有人格，先创建一个。" :image-size="60" />
        <div
          v-for="item in personas"
          :key="item.id"
          class="persona-item"
          :class="{ active: item.id === selectedId }"
          @click="selectPersona(item)"
        >
          <div class="persona-item-head">
            <strong>{{ item.name }}</strong>
            <StateTag :state="item.enabled ? 'enabled' : 'disabled'" :label="item.enabled ? '启用' : '停用'" />
          </div>
          <div class="persona-item-meta">
            <el-tag size="small" effect="plain">{{ item.mode_label ?? item.mode }}</el-tag>
            <span class="muted">v{{ item.latest_version }}</span>
            <span class="muted">稳定 {{ item.stable_trait_count }} · 候选 {{ item.candidate_trait_count }}</span>
          </div>
        </div>
      </div>

      <div class="persona-main">
        <el-empty v-if="!selected" description="从左侧选择一个人格，或新建人格。" />
        <div v-else>
          <div class="card persona-head">
            <div>
              <div class="persona-title">
                {{ selected.name }}
                <el-tag v-if="selected.mode === 'emergent'" size="small" type="warning">空白自成长</el-tag>
              </div>
              <div class="muted">
                {{ selected.mode_label ?? selected.mode }} · 最新版本 v{{ selected.latest_version }} ·
                成长策略 {{ selected.growth_policy }} · 学习范围 {{ selected.learning_scope }}
              </div>
            </div>
            <div class="row-actions">
              <el-button size="small" type="danger" text @click="deletePersona(selected)">删除人格</el-button>
            </div>
          </div>

          <el-tabs v-model="activeTab" class="persona-tabs">
            <el-tab-pane label="基本配置" name="config">
              <div class="card">
                <el-form label-width="150px" class="persona-form">
                  <el-form-item label="名称" required>
                    <el-input v-model="editForm.name" maxlength="64" />
                  </el-form-item>
                  <el-form-item label="模式">
                    <el-select v-model="editForm.mode" style="width: 100%">
                      <el-option v-for="mode in modes" :key="mode.value" :label="mode.label" :value="mode.value" />
                    </el-select>
                  </el-form-item>
                  <el-form-item v-if="editForm.mode === 'template'" label="模板">
                    <el-select v-model="editForm.template_key" style="width: 100%" placeholder="选择模板">
                      <el-option v-for="template in templates" :key="template.key" :label="template.name" :value="template.key" />
                    </el-select>
                    <div class="form-tip">模板只提供初始自我描述；保存后仍可编辑。</div>
                  </el-form-item>

                  <template v-if="editForm.mode !== 'emergent'">
                    <el-form-item label="自我描述">
                      <el-input
                        v-model="editForm.self_description"
                        type="textarea"
                        :rows="4"
                        maxlength="4000"
                        show-word-limit
                        placeholder="用第一人称描述这个群友是谁、如何说话。"
                      />
                    </el-form-item>
                    <el-form-item label="设定字段">
                      <div class="authored-list">
                        <div v-for="(field, index) in authoredFields" :key="index" class="authored-row">
                          <el-input v-model="field.key" placeholder="字段（如 tone）" class="authored-key" maxlength="64" />
                          <el-input v-model="field.value" placeholder="内容" maxlength="1000" />
                          <el-button text type="danger" @click="authoredFields.splice(index, 1)">删除</el-button>
                        </div>
                        <el-button size="small" @click="authoredFields.push({ key: '', value: '' })">添加字段</el-button>
                      </div>
                    </el-form-item>
                  </template>
                  <el-alert
                    v-else
                    type="info"
                    :closable="false"
                    show-icon
                    title="空白自成长人格不预置性格或背景。"
                    description="初始时没有任何稳定特征；后续全部来自聊天证据经治理校验后的成长提案。"
                  />

                  <el-form-item label="补充系统提示">
                    <el-input
                      v-model="editForm.system_prompt_overlay"
                      type="textarea"
                      :rows="3"
                      maxlength="2000"
                      placeholder="可选的补充说明。安全规则、群规与工具权限无法通过此字段覆盖。"
                    />
                  </el-form-item>
                  <el-form-item label="启用成长">
                    <el-switch v-model="editForm.growth_enabled" />
                  </el-form-item>
                  <el-form-item label="成长策略">
                    <el-select v-model="editForm.growth_policy" style="width: 240px">
                      <el-option v-for="policy in growthPolicies" :key="policy.value" :label="policy.label" :value="policy.value" />
                    </el-select>
                    <span class="form-tip" style="margin-left: 10px">
                      {{ growthPolicies.find((item) => item.value === editForm.growth_policy)?.note }}
                    </span>
                  </el-form-item>
                  <el-form-item label="学习范围">
                    <el-select v-model="editForm.learning_scope" style="width: 240px">
                      <el-option v-for="scope in learningScopes" :key="scope.value" :label="scope.label" :value="scope.value" />
                    </el-select>
                    <div v-if="editForm.learning_scope === 'cross_group'" class="form-tip">跨群学习可能造成信息串群，默认不建议开启。</div>
                  </el-form-item>

                  <el-divider content-position="left">成长证据门槛</el-divider>
                  <div class="threshold-grid">
                    <el-form-item label="最少证据条数">
                      <el-input-number v-model="editForm.thresholds.min_evidence_count" :min="1" :max="100" />
                    </el-form-item>
                    <el-form-item label="最少不同会话">
                      <el-input-number v-model="editForm.thresholds.min_conversations" :min="1" :max="100" />
                    </el-form-item>
                    <el-form-item label="最低置信度">
                      <el-input-number v-model="editForm.thresholds.min_confidence" :min="0" :max="1" :step="0.05" />
                    </el-form-item>
                    <el-form-item label="成长间隔消息数">
                      <el-input-number v-model="editForm.thresholds.min_messages_between_growth" :min="1" :max="100" />
                    </el-form-item>
                    <el-form-item label="单次最多特征">
                      <el-input-number v-model="editForm.thresholds.max_traits_per_proposal" :min="1" :max="100" />
                    </el-form-item>
                  </div>

                  <el-form-item label="锁定字段">
                    <el-select
                      v-model="editForm.locked_fields"
                      multiple
                      filterable
                      allow-create
                      default-first-option
                      style="width: 100%"
                      placeholder="例如 self_description、tone；锁定后成长不会覆盖"
                    />
                  </el-form-item>
                  <el-form-item label="启用人格">
                    <el-switch v-model="editForm.enabled" />
                  </el-form-item>
                  <el-form-item label="备注">
                    <el-input v-model="editForm.notes" type="textarea" :rows="2" maxlength="2000" />
                  </el-form-item>
                  <el-form-item label="变更说明">
                    <el-input v-model="editForm.change_summary" maxlength="200" placeholder="将写入版本快照" />
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" :loading="saving" @click="savePersona">保存配置</el-button>
                  </el-form-item>
                </el-form>

                <div v-if="selected.bound_groups?.length" class="bound-groups">
                  <span class="muted">已绑定群：</span>
                  <el-tag v-for="group in selected.bound_groups" :key="group.id" size="small">
                    {{ group.name || group.platform_group_id }}
                  </el-tag>
                </div>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="`特征（${selected.traits?.length ?? 0}）`" name="traits">
              <div class="card">
                <div class="card-title">
                  <span>人格特征</span>
                  <el-select v-model="traitFilter" size="small" clearable placeholder="全部状态" style="width: 140px" @change="loadDetail(selected.id)">
                    <el-option label="候选" value="candidate" />
                    <el-option label="稳定" value="stable" />
                    <el-option label="已拒绝" value="rejected" />
                  </el-select>
                </div>
                <el-empty v-if="!filteredTraits.length" description="暂无特征。空白人格在积累足够证据前不会生成任何特征。" :image-size="60" />
                <el-table v-else :data="filteredTraits" size="small">
                  <el-table-column label="特征" min-width="200">
                    <template #default="{ row }">
                      <div><strong>{{ row.trait_key }}</strong>：{{ row.trait_value }}</div>
                      <div class="muted">{{ row.category }} · 来源 {{ row.source_scope }}</div>
                    </template>
                  </el-table-column>
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }"><StateTag :state="row.status" /></template>
                  </el-table-column>
                  <el-table-column label="置信度 / 证据" width="130">
                    <template #default="{ row }">
                      {{ row.confidence }} · {{ row.evidence_count }} 条
                    </template>
                  </el-table-column>
                  <el-table-column label="锁定" width="90">
                    <template #default="{ row }">
                      <el-switch :model-value="row.locked_by_user" @change="(value: string | number | boolean) => toggleTraitLock(row, Boolean(value))" />
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="220">
                    <template #default="{ row }">
                      <div class="row-actions">
                        <el-button v-if="row.status !== 'stable'" size="small" @click="setTraitStatus(row, 'stable')">稳定化</el-button>
                        <el-button v-if="row.status !== 'rejected'" size="small" @click="setTraitStatus(row, 'rejected')">拒绝</el-button>
                        <el-button v-if="row.status === 'rejected'" size="small" @click="setTraitStatus(row, 'candidate')">恢复候选</el-button>
                        <el-button size="small" type="danger" text @click="deleteTrait(row)">删除</el-button>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column type="expand">
                    <template #default="{ row }">
                      <div class="trait-evidence">
                        <div class="muted">证据消息 ID（{{ row.evidence_message_ids.length }}）</div>
                        <div class="mono evidence-ids">{{ row.evidence_message_ids.join('、') || '无' }}</div>
                        <div class="muted">首次观测：{{ formatTime(row.first_observed_at) }} · 最近观测：{{ formatTime(row.last_observed_at) }}</div>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-tab-pane>

            <el-tab-pane label="成长与版本" name="growth">
              <div class="card">
                <div class="card-title">
                  <span>成长分析</span>
                  <el-select v-model="analysisGroupId" size="small" clearable placeholder="不限定群（按人格范围）" style="width: 220px">
                    <el-option v-for="group in groups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
                  </el-select>
                  <el-button size="small" type="primary" :loading="analyzing" @click="analyze">立即分析</el-button>
                </div>
                <el-alert
                  type="info"
                  :closable="false"
                  show-icon
                  title="分析会读取已有聊天证据并调用当前模型生成提案；提案本身不是事实，仍需治理校验。"
                />
                <div v-if="lastOutcome" class="outcome-box">
                  <StateTag :state="lastOutcome.applied ? 'available' : 'paused'" :label="lastOutcome.result" />
                  <span>{{ lastOutcome.message }}</span>
                  <span v-if="lastOutcome.version_no" class="muted">· 已生成 v{{ lastOutcome.version_no }}</span>
                  <span class="muted">· 证据 {{ lastOutcome.evidence_count }} 条 / 会话 {{ lastOutcome.conversation_count }} 个</span>
                  <p v-if="lastOutcome.diff_summary" class="diff-summary">{{ lastOutcome.diff_summary }}</p>
                </div>
              </div>

              <div class="card">
                <div class="card-title">
                  <span>待审核提案</span>
                  <span class="muted">{{ pending.length }} 条</span>
                </div>
                <el-empty v-if="!pending.length" description="没有待审核提案。" :image-size="55" />
                <div v-for="event in pending" :key="event.id" class="pending-item">
                  <div class="pending-head">
                    <strong>{{ event.summary || '人格成长提案' }}</strong>
                    <span class="muted">置信度 {{ event.confidence }} · {{ formatTime(event.created_at) }}</span>
                  </div>
                  <div class="muted">{{ event.evidence_summary }}</div>
                  <p v-if="event.diff_summary" class="diff-summary">变化摘要：{{ event.diff_summary }}</p>
                  <pre class="proposal-pre">{{ JSON.stringify(event.proposal, null, 2) }}</pre>
                  <div class="row-actions">
                    <el-button size="small" type="success" @click="review(event, true)">批准并应用</el-button>
                    <el-button size="small" type="danger" plain @click="review(event, false)">拒绝</el-button>
                  </div>
                </div>
              </div>

              <div class="grid grid-2">
                <div class="card">
                  <div class="card-title">版本历史</div>
                  <el-empty v-if="!selected.versions?.length" description="暂无版本" :image-size="50" />
                  <el-table v-else :data="selected.versions" size="small" max-height="360">
                    <el-table-column label="版本" width="70">
                      <template #default="{ row }">v{{ row.version_no }}</template>
                    </el-table-column>
                    <el-table-column prop="change_summary" label="说明" show-overflow-tooltip />
                    <el-table-column label="时间" width="140">
                      <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
                    </el-table-column>
                    <el-table-column label="操作" width="90">
                      <template #default="{ row }">
                        <el-button size="small" text type="primary" :disabled="!row.restorable" @click="restoreVersion(row)">回滚</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </div>
                <div class="card">
                  <div class="card-title">成长事件</div>
                  <el-empty v-if="!selected.events?.length" description="暂无成长事件" :image-size="50" />
                  <el-timeline v-else>
                    <el-timeline-item
                      v-for="event in selected.events.slice(0, 20)"
                      :key="event.id"
                      :timestamp="formatTime(event.created_at)"
                      placement="top"
                    >
                      <div class="event-head">
                        <StateTag :state="event.result === 'applied' ? 'available' : event.result" :label="event.result" />
                        <span>{{ event.summary }}</span>
                      </div>
                      <div class="muted">{{ triggerLabel(event.trigger_type) }} · 证据 {{ event.evidence_summary }}</div>
                      <p v-if="event.diff_summary" class="diff-summary">{{ event.diff_summary }}</p>
                    </el-timeline-item>
                  </el-timeline>
                </div>
              </div>

              <div class="card danger-zone">
                <div class="card-title">重置人格</div>
                <p class="muted">
                  重置会删除该人格的全部特征、成长事件与版本历史，并回到初始空白状态。此操作不可撤销，需要二次确认。
                </p>
                <el-button type="danger" @click="resetPersona">重置为空白状态</el-button>
              </div>
            </el-tab-pane>

            <el-tab-pane label="测试对话" name="test">
              <div class="card">
                <p class="muted">
                  使用 dry-run 模拟一条群消息：不会发送到 QQ，也不会写入消息日志。需要选择一个账号与该账号下已登记的群。
                </p>
                <el-form label-width="110px">
                  <el-form-item label="账号">
                    <el-select v-model="testForm.account_id" style="width: 100%" placeholder="选择账号" @change="onTestAccountChange">
                      <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="群">
                    <el-select v-model="testForm.group_id" style="width: 100%" placeholder="选择群">
                      <el-option
                        v-for="group in testGroups"
                        :key="group.id"
                        :label="`${group.name || group.platform_group_id}${group.paused ? '（已暂停）' : ''}`"
                        :value="group.id"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="模拟消息">
                    <el-input v-model="testForm.text" type="textarea" :rows="3" maxlength="4000" placeholder="例如：你怎么看这个问题？" />
                  </el-form-item>
                  <el-form-item label="模拟 @ 机器人">
                    <el-switch v-model="testForm.mention" />
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" :loading="testing" @click="runTest">模拟运行</el-button>
                  </el-form-item>
                </el-form>

                <div v-if="testResult" class="test-result">
                  <div class="test-result-head">
                    <StateTag :state="String(testResult.result.action)" />
                    <span class="muted">原因：{{ testResult.result.reason }}</span>
                    <span v-if="testResult.result.detail" class="muted">· {{ testResult.result.detail }}</span>
                  </div>
                  <div v-if="testResult.result.reply" class="reply-box">
                    <div class="muted">回复</div>
                    <div>{{ testResult.result.reply }}</div>
                    <div class="muted">
                      模型 {{ testResult.result.model ?? '—' }}
                      <el-tag v-if="testResult.result.is_mock" size="small" type="warning">Mock</el-tag>
                      · {{ testResult.result.latency_ms ?? '—' }} ms
                      · tokens {{ testResult.result.input_tokens ?? 0 }}/{{ testResult.result.output_tokens ?? 0 }}
                    </div>
                  </div>
                  <el-collapse v-if="testResult.result.prompt_preview">
                    <el-collapse-item title="查看脱敏后的提示词预览" name="prompt">
                      <pre class="prompt-pre">{{ testResult.result.prompt_preview }}</pre>
                    </el-collapse-item>
                  </el-collapse>
                  <p class="muted">dry-run：不会发送，也不会持久化。</p>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>

    <el-dialog v-model="createDialog" title="新建人格" width="560px" :close-on-click-modal="false">
      <el-form label-width="120px">
        <el-form-item label="名称" required>
          <el-input v-model="createForm.name" maxlength="64" placeholder="例如：群友小助手" />
        </el-form-item>
        <el-form-item label="模式" required>
          <el-radio-group v-model="createForm.mode">
            <el-radio value="emergent">空白自成长</el-radio>
            <el-radio value="authored">用户编写</el-radio>
            <el-radio value="template">模板</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-alert
          v-if="createForm.mode === 'emergent'"
          type="info"
          :closable="false"
          show-icon
          title="从零开始：不能预置自我描述或设定字段。"
          description="初始没有任何性格；后续由 AI 在聊天中提出结构化提案，经证据门槛与治理规则校验后逐步形成。"
          class="create-alert"
        />
        <el-form-item v-if="createForm.mode === 'template'" label="模板" required>
          <el-select v-model="createForm.template_key" style="width: 100%" placeholder="选择模板">
            <el-option v-for="template in templates" :key="template.key" :label="template.name" :value="template.key" />
          </el-select>
          <div v-if="selectedTemplate" class="form-tip">{{ selectedTemplate.description }}</div>
        </el-form-item>
        <el-form-item v-if="createForm.mode === 'authored'" label="自我描述">
          <el-input v-model="createForm.self_description" type="textarea" :rows="4" maxlength="4000" />
        </el-form-item>
        <el-form-item label="成长策略">
          <el-select v-model="createForm.growth_policy" style="width: 100%">
            <el-option v-for="policy in growthPolicies" :key="policy.value" :label="policy.label" :value="policy.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="学习范围">
          <el-select v-model="createForm.learning_scope" style="width: 100%">
            <el-option v-for="scope in learningScopes" :key="scope.value" :label="scope.label" :value="scope.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.notes" type="textarea" :rows="2" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createPersona">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, errorMessage } from '@/api/client'
import type { Account, EvolutionEvent, Group, Persona, PersonaTemplate, PersonaTrait, PersonaVersion } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { formatTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface PersonaDetail extends Persona {
  traits: PersonaTrait[]
  versions: PersonaVersion[]
  events: EvolutionEvent[]
  bound_groups: Array<{ id: string; name: string | null; platform_group_id: string }>
}

interface OptionItem {
  value: string
  label: string
  note?: string
}

interface GrowthOutcome {
  applied: boolean
  result: string
  message: string
  event_id?: string | null
  version_no?: number | null
  trait_count?: number
  evidence_count?: number
  conversation_count?: number
  summary?: string
  diff_summary?: string
}

interface DryRunPayload {
  dry_run: boolean
  sent: boolean
  persisted: boolean
  note: string
  result: {
    accepted: boolean
    action: string
    reason: string
    detail?: string | null
    reply?: string | null
    provider_id?: string | null
    model?: string | null
    is_mock?: boolean
    latency_ms?: number | null
    input_tokens?: number | null
    output_tokens?: number | null
    error_code?: string | null
    prompt_preview?: string | null
  }
}

const personas = ref<Persona[]>([])
const templates = ref<PersonaTemplate[]>([])
const modes = ref<OptionItem[]>([])
const growthPolicies = ref<OptionItem[]>([])
const learningScopes = ref<OptionItem[]>([])
const accounts = ref<Account[]>([])
const groups = ref<Group[]>([])

const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const analyzing = ref(false)
const testing = ref(false)
const error = ref<string | null>(null)

const selectedId = ref<string | null>(null)
const selected = ref<PersonaDetail | null>(null)
const activeTab = ref('config')
const traitFilter = ref<string | undefined>(undefined)
const analysisGroupId = ref<string | undefined>(undefined)
const pending = ref<EvolutionEvent[]>([])
const lastOutcome = ref<GrowthOutcome | null>(null)

const seeded = ref(false)
const createDialog = ref(false)
const createForm = reactive({
  name: '',
  mode: 'emergent',
  template_key: '',
  self_description: '',
  growth_policy: 'review',
  learning_scope: 'admin_only',
  notes: '',
})

const authoredFields = ref<Array<{ key: string; value: string }>>([])
const editForm = reactive({
  name: '',
  mode: 'emergent',
  template_key: '',
  self_description: '',
  system_prompt_overlay: '',
  growth_enabled: true,
  growth_policy: 'review',
  learning_scope: 'admin_only',
  thresholds: {
    min_evidence_count: 3,
    min_conversations: 2,
    min_confidence: 0.6,
    min_messages_between_growth: 5,
    max_traits_per_proposal: 5,
  },
  locked_fields: [] as string[],
  enabled: true,
  notes: '',
  change_summary: '控制台更新人格配置',
})

const testForm = reactive({
  account_id: '',
  group_id: '',
  text: '',
  mention: true,
})
const testResult = ref<DryRunPayload | null>(null)

const selectedTemplate = computed(() => templates.value.find((item) => item.key === createForm.template_key) ?? null)
const filteredTraits = computed(() => {
  const traits = selected.value?.traits ?? []
  return traitFilter.value ? traits.filter((trait) => trait.status === traitFilter.value) : traits
})
const testGroups = computed(() => groups.value.filter((group) => group.account_id === testForm.account_id))

const TRIGGER_LABELS: Record<string, string> = {
  auto: '自动成长',
  self_inquiry: '用户询问自我认知',
  manual: '管理员手动分析',
  review: '审核后应用',
}

function triggerLabel(value: string): string {
  return TRIGGER_LABELS[value] ?? value
}

function fillForm(persona: PersonaDetail): void {
  editForm.name = persona.name
  editForm.mode = persona.mode
  editForm.template_key = persona.template_key ?? ''
  editForm.self_description = persona.self_description
  editForm.system_prompt_overlay = persona.system_prompt_overlay
  editForm.growth_enabled = persona.growth_enabled
  editForm.growth_policy = persona.growth_policy
  editForm.learning_scope = persona.learning_scope
  editForm.thresholds = {
    min_evidence_count: Number(persona.thresholds?.min_evidence_count ?? 3),
    min_conversations: Number(persona.thresholds?.min_conversations ?? 2),
    min_confidence: Number(persona.thresholds?.min_confidence ?? 0.6),
    min_messages_between_growth: Number(persona.thresholds?.min_messages_between_growth ?? 5),
    max_traits_per_proposal: Number(persona.thresholds?.max_traits_per_proposal ?? 5),
  }
  editForm.locked_fields = [...persona.locked_fields]
  editForm.enabled = persona.enabled
  editForm.notes = persona.notes ?? ''
  editForm.change_summary = '控制台更新人格配置'
  authoredFields.value = Object.entries(persona.authored_fields ?? {}).map(([key, value]) => ({ key, value }))
}

async function loadBasics(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [personaData, templateData, optionsData] = await Promise.all([
      api<{
        items: Persona[]
        modes: OptionItem[]
        growth_policies: OptionItem[]
        learning_scopes: OptionItem[]
      }>('/personas'),
      api<{ items: PersonaTemplate[] }>('/personas/templates'),
      api<{
        accounts: Array<{ id: string; name: string }>
        groups: Group[]
      }>('/playground/options'),
    ])
    personas.value = personaData.items
    modes.value = personaData.modes
    growthPolicies.value = personaData.growth_policies
    learningScopes.value = personaData.learning_scopes
    templates.value = templateData.items
    const accountData = await api<{ items: Account[] }>('/accounts')
    accounts.value = accountData.items
    groups.value = (optionsData.groups as unknown as Group[]) ?? []
    if (!selectedId.value && personas.value.length) {
      selectPersona(personas.value[0])
    } else if (selectedId.value) {
      await loadDetail(selectedId.value)
    }
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function load(): Promise<void> {
  await loadBasics()
}

async function selectPersona(persona: Persona): Promise<void> {
  selectedId.value = persona.id
  activeTab.value = 'config'
  traitFilter.value = undefined
  lastOutcome.value = null
  await loadDetail(persona.id)
}

async function loadDetail(personaId: string): Promise<void> {
  try {
    const data = await api<PersonaDetail>(`/personas/${personaId}`)
    selected.value = data
    fillForm(data)
    const pendingData = await api<{ items: EvolutionEvent[] }>(`/personas/${personaId}/growth/pending`)
    pending.value = pendingData.items
    seeded.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function createPersona(): Promise<void> {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写人格名称。')
    return
  }
  if (createForm.mode === 'template' && !createForm.template_key) {
    ElMessage.warning('请选择人格模板。')
    return
  }
  const body: Record<string, unknown> = {
    name: createForm.name.trim(),
    mode: createForm.mode,
    growth_policy: createForm.growth_policy,
    learning_scope: createForm.learning_scope,
    notes: createForm.notes,
    growth_enabled: createForm.mode === 'emergent',
  }
  if (createForm.mode === 'template') body.template_key = createForm.template_key
  if (createForm.mode === 'authored') body.self_description = createForm.self_description
  creating.value = true
  try {
    const persona = await api<Persona>('/personas', { method: 'POST', body })
    ElMessage.success('人格已创建。')
    createDialog.value = false
    createForm.name = ''
    createForm.template_key = ''
    createForm.self_description = ''
    await loadBasics()
    selectedId.value = persona.id
    await loadDetail(persona.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    creating.value = false
  }
}

function openCreate(): void {
  createForm.name = ''
  createForm.mode = 'emergent'
  createForm.template_key = ''
  createForm.self_description = ''
  createForm.growth_policy = 'review'
  createForm.learning_scope = 'admin_only'
  createForm.notes = ''
  createDialog.value = true
}

async function savePersona(): Promise<void> {
  if (!selected.value) return
  if (!editForm.name.trim()) {
    ElMessage.warning('人格名称不能为空。')
    return
  }
  if (editForm.mode === 'template' && !editForm.template_key) {
    ElMessage.warning('模板模式必须选择模板。')
    return
  }
  const authored: Record<string, string> = {}
  for (const field of authoredFields.value) {
    if (field.key.trim() && field.value.trim()) authored[field.key.trim()] = field.value.trim()
  }
  const body: Record<string, unknown> = {
    name: editForm.name.trim(),
    mode: editForm.mode,
    template_key: editForm.template_key || null,
    system_prompt_overlay: editForm.system_prompt_overlay,
    growth_enabled: editForm.growth_enabled,
    growth_policy: editForm.growth_policy,
    learning_scope: editForm.learning_scope,
    thresholds: editForm.thresholds,
    locked_fields: editForm.locked_fields,
    enabled: editForm.enabled,
    notes: editForm.notes,
    change_summary: editForm.change_summary,
  }
  if (editForm.mode !== 'emergent') {
    body.self_description = editForm.self_description
    body.authored_fields = authored
  }
  saving.value = true
  try {
    await api(`/personas/${selected.value.id}`, { method: 'PATCH', body })
    ElMessage.success('人格配置已保存并生成新版本。')
    await loadBasics()
    await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function toggleTraitLock(trait: PersonaTrait, locked: boolean): Promise<void> {
  try {
    await api(`/personas/traits/${trait.id}`, { method: 'PATCH', body: { locked } })
    ElMessage.success(locked ? '特征已锁定，成长不会覆盖。' : '特征已解锁。')
    if (selected.value) await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function setTraitStatus(trait: PersonaTrait, status: string): Promise<void> {
  try {
    await api(`/personas/traits/${trait.id}`, { method: 'PATCH', body: { status } })
    ElMessage.success('特征状态已更新。')
    if (selected.value) await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function deleteTrait(trait: PersonaTrait): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除特征「${trait.trait_key}」？`, '删除特征', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await api(`/personas/traits/${trait.id}`, { method: 'DELETE' })
    ElMessage.success('特征已删除。')
    if (selected.value) await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function analyze(): Promise<void> {
  if (!selected.value) return
  analyzing.value = true
  lastOutcome.value = null
  try {
    const outcome = await api<GrowthOutcome>(`/personas/${selected.value.id}/growth/analyze`, {
      method: 'POST',
      body: { group_id: analysisGroupId.value || null },
    })
    lastOutcome.value = outcome
    if (outcome.applied) {
      ElMessage.success(outcome.message)
    } else {
      ElMessage.info(outcome.message)
    }
    await loadBasics()
    await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    analyzing.value = false
  }
}

async function review(event: EvolutionEvent, approve: boolean): Promise<void> {
  try {
    await ElMessageBox.confirm(
      approve ? '批准后提案将通过治理校验并可能生成新版本。确认批准？' : '拒绝后该提案不会应用。确认拒绝？',
      approve ? '批准成长提案' : '拒绝成长提案',
      { type: approve ? 'warning' : 'info', confirmButtonText: approve ? '批准' : '拒绝', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const outcome = await api<GrowthOutcome>(`/personas/growth/${event.id}/review`, {
      method: 'POST',
      body: { approve },
    })
    ElMessage.success(outcome.message)
    if (selected.value) {
      await loadDetail(selected.value.id)
      await loadBasics()
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function restoreVersion(version: PersonaVersion): Promise<void> {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm(
      `确定回滚到 v${version.version_no}「${version.change_summary}」？当前配置会被覆盖，并生成新的版本记录。`,
      '回滚人格版本',
      { type: 'warning', confirmButtonText: '回滚', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/personas/${selected.value.id}/versions/${version.id}/restore`, { method: 'POST' })
    ElMessage.success(`已回滚到 v${version.version_no}。`)
    await loadBasics()
    await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function resetPersona(): Promise<void> {
  if (!selected.value) return
  const name = selected.value.name
  try {
    await ElMessageBox.confirm(
      `重置「${name}」会删除全部特征、成长事件与版本历史，且不可恢复。`,
      '重置人格',
      { type: 'error', confirmButtonText: '继续', cancelButtonText: '取消' },
    )
    await ElMessageBox.prompt(
      `请输入人格名称「${name}」以确认重置：`,
      '二次确认',
      { type: 'error', confirmButtonText: '确认重置', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/personas/${selected.value.id}/reset`, { method: 'POST' })
    ElMessage.success('人格已重置为空白状态。')
    await loadBasics()
    await loadDetail(selected.value.id)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function deletePersona(persona: Persona): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除人格「${persona.name}」？绑定该人格的群需要重新选择人格。`,
      '删除人格',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await api(`/personas/${persona.id}`, { method: 'DELETE' })
    ElMessage.success('人格已删除。')
    if (selectedId.value === persona.id) {
      selectedId.value = null
      selected.value = null
    }
    await loadBasics()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function onTestAccountChange(): void {
  if (!testGroups.value.some((group) => group.id === testForm.group_id)) {
    testForm.group_id = ''
  }
}

async function runTest(): Promise<void> {
  if (!selected.value) return
  if (!testForm.account_id || !testForm.group_id) {
    ElMessage.warning('请选择账号与群。')
    return
  }
  if (!testForm.text.trim()) {
    ElMessage.warning('请输入模拟消息。')
    return
  }
  const account = accounts.value.find((item) => item.id === testForm.account_id)
  const mentions = testForm.mention && account?.self_platform_user_id ? [account.self_platform_user_id] : []
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api<DryRunPayload>(`/personas/${selected.value.id}/test`, {
      method: 'POST',
      body: {
        account_id: testForm.account_id,
        group_id: testForm.group_id,
        text: testForm.text,
        mentions,
        sender_name: '模拟群友',
      },
    })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    testing.value = false
  }
}

onMounted(loadBasics)
</script>

<style scoped>
.persona-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

@media (max-width: 1100px) {
  .persona-layout {
    grid-template-columns: 1fr;
  }
}

.persona-list {
  position: sticky;
  top: 14px;
  max-height: calc(100vh - 120px);
  overflow: auto;
}

.persona-item {
  border: 1px solid var(--app-border);
  border-radius: 9px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.persona-item:hover {
  border-color: var(--app-accent);
}

.persona-item.active {
  border-color: var(--app-accent);
  background: var(--app-accent-soft);
}

.persona-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.persona-item-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 12px;
}

.persona-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.persona-title {
  font-size: 17px;
  font-weight: 650;
  display: flex;
  gap: 8px;
  align-items: center;
}

.persona-tabs {
  margin-top: 4px;
}

.authored-list {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.authored-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.authored-key {
  max-width: 210px;
}

.threshold-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.bound-groups {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  padding-top: 8px;
  border-top: 1px dashed var(--app-border);
}

.outcome-box {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 10px;
  background: var(--app-accent-soft);
  border-radius: 8px;
  padding: 10px 12px;
}

.diff-summary {
  flex-basis: 100%;
  margin: 4px 0 0;
  color: var(--app-text-muted, #6b7280);
  font-size: 13px;
  line-height: 1.6;
}

.pending-item {
  border: 1px solid var(--app-border);
  border-radius: 9px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.pending-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.proposal-pre {
  background: var(--app-surface-soft);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
}

.event-head {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.trait-evidence {
  padding: 8px 16px 10px 48px;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.evidence-ids {
  word-break: break-all;
}

.danger-zone {
  border-color: #fecaca;
}

.reply-box {
  background: var(--app-success-soft);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 10px 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.test-result {
  border-top: 1px dashed var(--app-border);
  padding-top: 10px;
}

.test-result-head {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.prompt-pre {
  background: var(--app-surface-soft);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.create-alert {
  margin-bottom: 14px;
}
</style>
