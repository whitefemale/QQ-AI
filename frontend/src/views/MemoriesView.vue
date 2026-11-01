<template>
  <div class="page">
    <PageHeader
      title="长期记忆"
      description="管理 AI 群友的长期记忆。只有开启记忆的群才会注入本群或当前发送者的普通敏感度记忆，绝不跨群；AI 提取可手动触发或在群内显式开启后台增量提取，结果都必须人工审核；语义检索仍为规划能力。"
    >
      <template #actions>
        <el-tag type="success" effect="plain">AI 提取：需审核</el-tag>
        <el-tag type="info" effect="plain">后台自动提取：可选开启</el-tag>
        <el-badge :value="pendingCount" :hidden="!pendingCount" class="header-badge">
          <el-button @click="openCandidates">候选审核</el-button>
        </el-badge>
        <el-button @click="openExtract">AI 提取候选</el-button>
        <el-button @click="openExport">导出 CSV</el-button>
        <el-button @click="openCleanup">清理工具</el-button>
        <el-button :loading="loading" @click="reload">刷新</el-button>
        <el-button type="primary" @click="openCreate">添加记忆</el-button>
      </template>
    </PageHeader>

    <el-alert
      type="info"
      show-icon
      :closable="false"
      title="当前是本地关键词/二元词检索，不是向量语义搜索。"
      description="固定记忆优先，其次按与当前消息的相关度、置信度和记录时间排序。敏感度为 sensitive、已过期、账号级或成员的记忆不会自动注入；记忆内容始终是不可信历史资料。AI 提取结果只是待审核候选，不会直接进入记忆库。"
    />
    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />

    <div class="card">
      <div class="filter-bar">
        <el-select v-model="filters.account_id" clearable placeholder="全部账号" style="width: 180px" @change="onFilterAccountChange">
          <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
        </el-select>
        <el-select v-model="filters.group_id" clearable placeholder="全部群" style="width: 200px" @change="reloadFirstPage">
          <el-option v-for="group in filterGroups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
        </el-select>
        <el-select v-model="filters.memory_type" clearable placeholder="全部类型" style="width: 140px" @change="reloadFirstPage">
          <el-option v-for="item in MEMORY_TYPES" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input
          v-model="filters.search"
          clearable
          placeholder="搜索记忆内容"
          style="width: 240px"
          @keyup.enter="reloadFirstPage"
          @clear="reloadFirstPage"
        />
        <el-checkbox v-model="filters.include_expired" @change="reloadFirstPage">包含已过期</el-checkbox>
        <el-button @click="reloadFirstPage">查询</el-button>
        <el-button text @click="resetFilters">重置</el-button>
      </div>
    </div>

    <div class="card">
      <el-table v-loading="loading" :data="memories" row-key="id">
        <el-table-column label="记忆内容" min-width="300">
          <template #default="{ row }">
            <div class="memory-content">{{ row.content }}</div>
            <div class="memory-meta">
              <el-tag v-if="row.is_pinned" size="small" type="warning">已固定</el-tag>
              <el-tag v-if="row.sensitivity === 'sensitive'" size="small" type="danger">敏感</el-tag>
              <el-tooltip v-if="row.source_message_ids?.length" :content="row.source_message_ids.join('、')" placement="top">
                <span class="muted">来源 {{ row.source_message_ids.length }} 条消息</span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ memoryTypeLabel(row.memory_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="作用范围" min-width="200">
          <template #default="{ row }">
            <div>{{ row.group_id ? groupLabel(row.group_id) : '账号级' }}</div>
            <div class="muted">
              <template v-if="row.member_id">
                成员 {{ memberLabel(row.member_id) }}
                <el-tag v-if="excludedMembers.has(row.member_id)" size="small" type="warning">已排除记忆</el-tag>
              </template>
              <template v-else-if="row.group_id">全群可见</template>
              <template v-else>不属于任何群，不会自动注入</template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="注入状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="injectionState(row).type">{{ injectionState(row).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="90">
          <template #default="{ row }">
            <span class="mono">{{ Number(row.confidence).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="过期时间" width="150">
          <template #default="{ row }">
            <span :class="{ muted: !row.expires_at }">{{ formatTime(row.expires_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建 / 更新" width="150">
          <template #default="{ row }">
            <div>{{ formatTime(row.created_at) }}</div>
            <div class="muted">{{ formatTime(row.updated_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="285" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" @click="togglePinned(row)">{{ row.is_pinned ? '取消固定' : '固定' }}</el-button>
              <el-button size="small" text @click="openSources(row)">来源</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" text @click="removeMemory(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !memories.length" description="还没有符合条件的记忆。添加后，只有相关消息才会使用它。" />
      <div v-if="total > pageSize" class="pagination">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next, total"
          @current-change="loadMemories"
        />
      </div>
      <p v-if="note" class="muted note">{{ note }}</p>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑记忆' : '添加记忆'" width="720px" :close-on-click-modal="false">
      <el-alert
        v-if="dialogMember?.excluded_from_memory"
        type="warning"
        show-icon
        :closable="false"
        title="该成员已被排除记忆，其成员级记忆不会自动注入。"
        class="dialog-alert"
      />
      <el-form label-width="110px">
        <el-form-item label="账号" required>
          <el-select v-model="form.account_id" :disabled="Boolean(editing)" style="width: 100%" placeholder="选择账号" @change="onFormAccountChange">
            <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="作用群">
          <el-select v-model="form.group_id" :disabled="Boolean(editing)" clearable style="width: 100%" placeholder="不指定群（账号级，不会自动注入）">
            <el-option v-for="group in formGroups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
          </el-select>
          <div class="form-tip">只有指定群、且该群开启「允许长期记忆」时，记忆才可能自动注入。编辑时不能更换作用域。</div>
        </el-form-item>
        <el-form-item label="成员范围">
          <el-select
            v-model="form.member_id"
            :disabled="Boolean(editing) || !form.account_id"
            clearable
            filterable
            style="width: 100%"
            placeholder="留空表示全群可见"
          >
            <el-option
              v-for="member in formMembers"
              :key="member.id"
              :label="`${member.display_name || member.platform_user_id}（${member.platform_user_id}）${member.excluded_from_memory ? ' · 已排除记忆' : ''}`"
              :value="member.platform_user_id"
            />
          </el-select>
          <div class="form-tip">成员级记忆只对应当前发送者；选择成员时必须同时指定群。</div>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.memory_type" style="width: 180px">
            <el-option v-for="item in MEMORY_TYPES" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="5"
            maxlength="2000"
            show-word-limit
            placeholder="例如：小绿习惯在每周五同步项目进度。请写成描述性事实，不要保存密码、验证码、证件号或密钥。"
          />
        </el-form-item>
        <el-form-item label="敏感度">
          <el-radio-group v-model="form.sensitivity">
            <el-radio value="normal">普通（可自动注入）</el-radio>
            <el-radio value="sensitive">敏感（仅人工管理）</el-radio>
          </el-radio-group>
          <div class="form-tip">敏感记忆不会被自动注入提示词，适合只在控制台保留的记录。</div>
        </el-form-item>
        <el-form-item label="置信度">
          <el-slider v-model="form.confidence" :min="0" :max="1" :step="0.05" show-input style="max-width: 420px" />
        </el-form-item>
        <el-form-item label="固定记忆">
          <el-switch v-model="form.is_pinned" />
          <span class="form-tip" style="margin-left: 10px">固定记忆优先注入，即使当前消息没有明显关键词重叠。</span>
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="form.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="留空表示长期有效"
            clearable
            style="width: 260px"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMemory">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="extractDialog" title="AI 提取记忆候选" width="680px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="提取结果不会自动生效。"
        description="模型只会生成待审核候选；批准前不会保存为正式记忆，也不会注入提示词。聊天记录是不可信数据，不符合证据、敏感内容或去重规则的候选会被丢弃。"
        class="dialog-alert"
      />
      <el-form label-width="100px">
        <el-form-item label="目标群" required>
          <el-select v-model="extractGroupId" filterable style="width: 100%" placeholder="选择已开启长期记忆的群">
            <el-option
              v-for="group in extractGroups"
              :key="group.id"
              :label="`${group.name || group.platform_group_id} · ${accountLabel(group.account_id)}`"
              :value="group.id"
            />
          </el-select>
          <div class="form-tip">只读取该群最近的入站文本消息，至少需要 3 条；已标记“排除记忆”的成员会被忽略。</div>
        </el-form-item>
      </el-form>
      <el-empty
        v-if="!extractGroups.length"
        :image-size="70"
        description="没有已开启长期记忆的群。请先在群聊管理中显式开启，再回来提取。"
      />

      <div v-if="extractionResult" class="extract-result">
        <div class="extract-stats">
          <div class="stat"><span class="muted">扫描消息</span><strong>{{ extractionResult.scanned_messages }}</strong></div>
          <div class="stat"><span class="muted">新增候选</span><strong>{{ extractionResult.created_count }}</strong></div>
          <div class="stat"><span class="muted">跳过</span><strong>{{ extractionResult.skipped }}</strong></div>
          <div class="stat"><span class="muted">提取模型</span><strong>{{ extractionSource(extractionResult) }}</strong></div>
        </div>
        <el-alert
          v-if="extractionResult.is_mock"
          type="warning"
          show-icon
          :closable="false"
          title="本次由 Mock 模型模拟提取，仅用于演示流程。"
          description="Mock 候选不是真实 AI 的理解结果，不应作为真实记忆长期保留。"
          class="dialog-alert"
        />
        <p class="extract-message">{{ extractionResult.message }}</p>
        <div v-if="skippedReasons.length" class="skipped">
          <span class="muted">跳过原因：</span>
          <el-tag v-for="item in skippedReasons" :key="item.code" size="small" type="info" effect="plain">
            {{ skippedReasonLabel(item.code) }} × {{ item.count }}
          </el-tag>
        </div>
        <div v-if="extractionResult.created.length" class="extract-created">
          <div class="muted">本次候选（仍需审核）：</div>
          <div v-for="candidate in extractionResult.created" :key="candidate.id" class="created-item">
            {{ candidate.content }}
          </div>
        </div>
        <p class="muted extract-message">{{ extractionResult.note }}</p>
      </div>

      <template #footer>
        <el-button @click="extractDialog = false">关闭</el-button>
        <el-button v-if="extractionResult?.created_count" @click="openCandidates">审核候选</el-button>
        <el-button
          type="primary"
          :loading="extracting"
          :disabled="!extractGroupId || !extractGroups.length"
          @click="runExtraction"
        >
          开始提取
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="candidateDialog" title="记忆候选审核" width="1080px" :close-on-click-modal="false">
      <el-alert
        type="info"
        show-icon
        :closable="false"
        :title="candidateNote || '待审核候选不是正式记忆。'"
        class="dialog-alert"
      />
      <el-alert v-if="candidateError" type="error" show-icon :closable="false" :title="candidateError" class="dialog-alert" />
      <div class="candidate-toolbar">
        <el-radio-group v-model="candidateStatus" @change="onCandidateStatusChange">
          <el-radio-button value="pending">待审核</el-radio-button>
          <el-radio-button value="approved">已批准</el-radio-button>
          <el-radio-button value="rejected">已拒绝</el-radio-button>
        </el-radio-group>
        <span class="muted">共 {{ candidateTotal }} 条</span>
        <el-button size="small" :loading="candidateLoading" @click="loadCandidates">刷新</el-button>
      </div>
      <el-table v-loading="candidateLoading" :data="candidates" row-key="id">
        <el-table-column label="候选内容" min-width="300">
          <template #default="{ row }">
            <div class="memory-content">{{ row.content }}</div>
            <div class="candidate-tags">
              <el-tag v-if="row.is_mock" size="small" type="warning">Mock 模拟</el-tag>
              <el-tag size="small" :type="candidateStatusTag(row.status)">{{ candidateStatusLabel(row.status) }}</el-tag>
              <el-tooltip v-if="row.source_message_ids?.length" :content="row.source_message_ids.join('、')" placement="top">
                <span class="muted">证据 {{ row.source_message_ids.length }} 条消息</span>
              </el-tooltip>
              <span v-else class="muted">无证据</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="95">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ memoryTypeLabel(row.memory_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围" min-width="180">
          <template #default="{ row }">
            <div>{{ groupLabel(row.group_id) }}</div>
            <div class="muted">
              {{ row.member_id ? `成员 ${memberLabel(row.member_id)}` : '全群可见' }}
              <span> · {{ accountLabel(row.account_id) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="80">
          <template #default="{ row }">
            <span class="mono">{{ Number(row.confidence).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="提取来源" width="150">
          <template #default="{ row }">
            <div>{{ candidateSource(row) }}</div>
            <div class="muted">{{ formatTime(row.created_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="审核信息" width="160">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <span class="muted">等待人工审核</span>
            </template>
            <template v-else>
              <div>{{ formatTime(row.reviewed_at) }}</div>
              <div class="muted">{{ row.reviewed_by || '—' }}</div>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="145" fixed="right">
          <template #default="{ row }">
            <div v-if="row.status === 'pending'" class="row-actions">
              <el-button size="small" type="primary" :loading="candidateActionId === row.id" @click="approveCandidate(row)">
                批准
              </el-button>
              <el-button size="small" type="danger" text :disabled="candidateActionId === row.id" @click="rejectCandidate(row)">
                拒绝
              </el-button>
            </div>
            <span v-else class="muted">{{ row.memory_id ? '已生成正式记忆' : '未生成记忆' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!candidateLoading && !candidates.length" description="暂无待审核记忆候选；后台提取默认关闭。" />
      <div v-if="candidateTotal > candidatePageSize" class="pagination">
        <el-pagination
          v-model:current-page="candidatePage"
          :page-size="candidatePageSize"
          :total="candidateTotal"
          layout="prev, pager, next, total"
          @current-change="loadCandidates"
        />
      </div>
    </el-dialog>

    <el-dialog v-model="exportDialog" title="导出记忆 CSV" width="560px" :close-on-click-modal="false">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="导出使用当前筛选条件"
        description="默认排除敏感记忆。CSV 带 UTF-8 BOM 并做公式注入防护；导出动作会写审计，但不记录记忆正文。"
      />
      <el-checkbox v-model="exportIncludeSensitive">
        包含敏感记忆（仅在本机管理界面下载，导出文件不再受应用保护）
      </el-checkbox>
      <el-alert
        v-if="exportIncludeSensitive"
        type="warning"
        :closable="false"
        show-icon
        title="敏感记忆将写入导出文件"
        description="请只保存在受控位置，并避免上传到公开网盘、聊天群或代码仓库。"
      />
      <p class="muted">
        筛选：{{ filters.account_id ? accountLabel(filters.account_id) : '全部账号' }} ·
        {{ filters.group_id ? groupLabel(filters.group_id) : '全部群' }} ·
        {{ filters.memory_type ? memoryTypeLabel(filters.memory_type) : '全部类型' }} ·
        {{ filters.search.trim() ? `搜索「${filters.search.trim()}」` : '无搜索词' }}
      </p>
      <template #footer>
        <el-button @click="exportDialog = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="exportCsv">下载 CSV</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="cleanupDialog" title="记忆清理" width="560px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="清理只删除未固定的匹配记忆"
        description="固定记忆不会被删除。建议先使用「仅统计」确认范围，再执行真实清理。"
      />
      <el-form label-width="100px">
        <el-form-item label="模式">
          <el-radio-group v-model="cleanupMode">
            <el-radio value="expired">已过期</el-radio>
            <el-radio value="older_than">创建超过天数</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="cleanupMode === 'older_than'" label="天数">
          <el-input-number v-model="cleanupDays" :min="1" :max="3650" />
        </el-form-item>
        <el-form-item label="仅统计">
          <el-switch v-model="cleanupDryRun" />
          <span class="muted" style="margin-left: 10px">开启时不会删除任何记忆。</span>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="cleanupResult"
        :type="cleanupResult.dry_run ? 'info' : 'success'"
        :closable="false"
        show-icon
        :title="`匹配 ${cleanupResult.matched} 条，删除 ${cleanupResult.deleted} 条`"
        :description="cleanupResult.note"
      />
      <template #footer>
        <el-button @click="cleanupDialog = false">关闭</el-button>
        <el-button type="primary" :loading="cleaning" @click="runCleanup">
          {{ cleanupDryRun ? '仅统计' : '执行清理' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="sourcesDialog" title="记忆来源" width="760px">
      <el-alert type="info" :closable="false" show-icon :title="sourcesNote" />
      <el-table v-loading="sourcesLoading" :data="sources" size="small">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ row.timestamp ? formatTime(row.timestamp) : '—' }}</template>
        </el-table-column>
        <el-table-column label="群 / 发送者" width="180">
          <template #default="{ row }">
            <div>{{ row.group_name || row.group_id || '—' }}</div>
            <div class="muted">{{ row.sender_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="脱敏预览" min-width="260">
          <template #default="{ row }">
            <span v-if="row.missing" class="muted">消息已删除或不在该记忆所属账号/群范围内。</span>
            <span v-else>{{ row.preview || '（无文本）' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!sourcesLoading && !sources.length" description="该记忆没有关联的来源消息。" :image-size="50" />
      <template #footer>
        <el-button @click="sourcesDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="approvalDialog" title="批准记忆候选" width="540px" :close-on-click-modal="false">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="批准后生成正式记忆"
        description="普通敏感度可能按相关性自动注入；敏感记忆不会被自动注入，只能在控制台查看与管理。"
      />
      <p class="candidate-preview">{{ approvalCandidate?.content }}</p>
      <el-form label-width="100px">
        <el-form-item label="敏感度">
          <el-radio-group v-model="approvalSensitivity">
            <el-radio value="normal">普通（可自动注入）</el-radio>
            <el-radio value="sensitive">敏感（仅人工管理）</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="approvalCandidate?.is_mock"
        type="warning"
        :closable="false"
        show-icon
        title="这是 Mock 模拟内容"
        description="Mock 候选不是真实模型的理解结果，不应作为真实记忆长期保留。"
      />
      <template #footer>
        <el-button @click="approvalDialog = false">取消</el-button>
        <el-button type="primary" :loading="candidateActionId !== ''" @click="submitCandidateApproval">
          确认批准
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import { api, downloadApiFile, errorMessage } from '@/api/client'
import type {
  Account,
  Group,
  MemberRecord,
  MemoryCandidateApproval,
  MemoryCandidateListPayload,
  MemoryCandidateRecord,
  MemoryCleanupResult,
  MemoryExtractionResult,
  MemoryListPayload,
  MemoryRecord,
  MemorySourceItem,
  MemorySourcesPayload,
} from '@/api/types'
import { CLEANUP_PHRASE, typedConfirm } from '@/utils/confirmation'
import { formatTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

const MEMORY_TYPES = [
  { value: 'fact', label: '事实' },
  { value: 'preference', label: '偏好' },
  { value: 'relationship', label: '关系' },
  { value: 'event', label: '经历' },
  { value: 'project', label: '长期事项' },
  { value: 'boundary', label: '边界' },
] as const

interface MemoryForm {
  account_id: string
  group_id: string | null
  member_id: string | null
  memory_type: string
  content: string
  sensitivity: string
  confidence: number
  is_pinned: boolean
  expires_at: string | null
}

const accounts = ref<Account[]>([])
const groups = ref<Group[]>([])
const members = ref<MemberRecord[]>([])
const memories = ref<MemoryRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const note = ref('')
const dialog = ref(false)
const editing = ref<MemoryRecord | null>(null)

const pendingCount = ref(0)
const extractDialog = ref(false)
const extractGroupId = ref('')
const extracting = ref(false)
const extractionResult = ref<MemoryExtractionResult | null>(null)
const candidateDialog = ref(false)
const candidateStatus = ref('pending')
const candidates = ref<MemoryCandidateRecord[]>([])
const candidateTotal = ref(0)
const candidatePage = ref(1)
const candidatePageSize = 50
const candidateLoading = ref(false)
const candidateError = ref('')
const candidateNote = ref('')
const candidateActionId = ref('')

const exportDialog = ref(false)
const exportIncludeSensitive = ref(false)
const exporting = ref(false)
const cleanupDialog = ref(false)
const cleanupMode = ref<'expired' | 'older_than'>('expired')
const cleanupDays = ref(90)
const cleanupDryRun = ref(true)
const cleaning = ref(false)
const cleanupResult = ref<MemoryCleanupResult | null>(null)
const sourcesDialog = ref(false)
const sourcesLoading = ref(false)
const sources = ref<MemorySourceItem[]>([])
const sourcesNote = ref('')
const approvalDialog = ref(false)
const approvalCandidate = ref<MemoryCandidateRecord | null>(null)
const approvalSensitivity = ref<'normal' | 'sensitive'>('normal')

const filters = reactive({
  account_id: '',
  group_id: '',
  memory_type: '',
  search: '',
  include_expired: true,
})

const form = reactive<MemoryForm>(emptyForm())

const filterGroups = computed(() =>
  filters.account_id ? groups.value.filter((group) => group.account_id === filters.account_id) : groups.value,
)
const formGroups = computed(() =>
  form.account_id ? groups.value.filter((group) => group.account_id === form.account_id) : [],
)
const formMembers = computed(() =>
  form.account_id ? members.value.filter((member) => member.account_id === form.account_id) : [],
)
const excludedMembers = computed(
  () => new Set(members.value.filter((member) => member.excluded_from_memory).map((member) => member.platform_user_id)),
)
const groupMap = computed(() => new Map(groups.value.map((group) => [group.id, group])))
const memberMap = computed(() => new Map(members.value.map((member) => [member.platform_user_id, member])))
const dialogMember = computed(() => formMembers.value.find((member) => member.platform_user_id === form.member_id) ?? null)
const extractGroups = computed(() => groups.value.filter((group) => group.allow_memory))
const skippedReasons = computed(() =>
  Object.entries(extractionResult.value?.skipped_reasons ?? {}).map(([code, count]) => ({ code, count })),
)

function emptyForm(): MemoryForm {
  return {
    account_id: '',
    group_id: null,
    member_id: null,
    memory_type: 'fact',
    content: '',
    sensitivity: 'normal',
    confidence: 0.7,
    is_pinned: false,
    expires_at: null,
  }
}

function memoryTypeLabel(value: string): string {
  return MEMORY_TYPES.find((item) => item.value === value)?.label ?? value
}

function groupLabel(groupId: string | null): string {
  if (!groupId) return '账号级'
  const group = groupMap.value.get(groupId)
  return group ? group.name || group.platform_group_id : '未知群（可能已删除）'
}

function accountLabel(accountId: string): string {
  return accounts.value.find((account) => account.id === accountId)?.display_name ?? accountId
}

function extractionSource(result: MemoryExtractionResult): string {
  if (result.is_mock) return 'Mock 模拟'
  return result.model || result.provider_type || '未记录'
}

function candidateSource(candidate: MemoryCandidateRecord): string {
  if (candidate.is_mock) return 'Mock 模拟'
  return candidate.extraction_model || candidate.provider_type || '未记录'
}

function candidateStatusLabel(status: string): string {
  return status === 'approved' ? '已批准' : status === 'rejected' ? '已拒绝' : '待审核'
}

function candidateStatusTag(status: string): 'success' | 'danger' | 'warning' {
  return status === 'approved' ? 'success' : status === 'rejected' ? 'danger' : 'warning'
}

function skippedReasonLabel(code: string): string {
  const labels: Record<string, string> = {
    duplicate: '重复内容',
    sensitive: '疑似敏感内容',
    invalid_content: '内容无效',
    invalid_fields: '字段无效',
    low_confidence: '置信度不足',
    unknown_member: '未知成员',
    missing_evidence: '缺少有效证据',
    over_limit: '超过条数上限',
  }
  return labels[code] ?? code
}

function memberLabel(platformUserId: string): string {
  const member = memberMap.value.get(platformUserId)
  return member ? member.display_name || member.platform_user_id : platformUserId
}

function injectionState(row: MemoryRecord): { label: string; type: 'success' | 'warning' | 'danger' | 'info' } {
  if (row.expired) return { label: '已过期', type: 'warning' }
  if (row.sensitivity !== 'normal') return { label: '仅人工管理', type: 'warning' }
  if (!row.group_id) return { label: '不自动注入', type: 'info' }
  const group = groupMap.value.get(row.group_id)
  if (!group) return { label: '群不存在', type: 'danger' }
  if (!group.allow_memory) return { label: '群未开启记忆', type: 'info' }
  if (row.member_id && excludedMembers.value.has(row.member_id)) return { label: '成员已排除', type: 'warning' }
  return { label: '可自动注入', type: 'success' }
}

async function loadBase(): Promise<void> {
  const [accountData, groupData, memberData] = await Promise.all([
    api<{ items: Account[] }>('/accounts'),
    api<{ items: Group[] }>('/groups'),
    api<{ items: MemberRecord[] }>('/groups/members'),
  ])
  accounts.value = accountData.items
  groups.value = groupData.items
  members.value = memberData.items
  if (!filters.account_id && accounts.value.length === 1) {
    filters.account_id = accounts.value[0].id
  }
}

async function loadMemories(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const data = await api<MemoryListPayload>('/memories', {
      query: {
        account_id: filters.account_id || undefined,
        group_id: filters.group_id || undefined,
        memory_type: filters.memory_type || undefined,
        search: filters.search.trim() || undefined,
        include_expired: filters.include_expired,
        page: page.value,
        page_size: pageSize,
      },
    })
    memories.value = data.items
    total.value = data.total
    note.value = data.note
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    loading.value = false
  }
}

async function reload(): Promise<void> {
  try {
    await Promise.all([loadBase(), loadPendingCount()])
    await loadMemories()
  } catch (cause) {
    error.value = errorMessage(cause)
  }
}

async function loadPendingCount(): Promise<void> {
  try {
    const data = await api<MemoryCandidateListPayload>('/memories/candidates', {
      query: { status: 'pending', page: 1, page_size: 1 },
    })
    pendingCount.value = data.total
  } catch {
    // 候选计数只是辅助提示，失败时不覆盖页面主要错误。
    pendingCount.value = 0
  }
}

async function reloadFirstPage(): Promise<void> {
  page.value = 1
  await loadMemories()
}

function onFilterAccountChange(): void {
  filters.group_id = ''
  void reloadFirstPage()
}

function resetFilters(): void {
  filters.account_id = accounts.value.length === 1 ? accounts.value[0].id : ''
  filters.group_id = ''
  filters.memory_type = ''
  filters.search = ''
  filters.include_expired = true
  void reloadFirstPage()
}

function onFormAccountChange(): void {
  form.group_id = null
  form.member_id = null
}

function openCreate(): void {
  editing.value = null
  Object.assign(form, emptyForm(), {
    account_id: filters.account_id || accounts.value[0]?.id || '',
    group_id: filters.group_id || null,
  })
  dialog.value = true
}

function openEdit(row: MemoryRecord): void {
  editing.value = row
  Object.assign(form, {
    account_id: row.account_id,
    group_id: row.group_id,
    member_id: row.member_id,
    memory_type: row.memory_type,
    content: row.content,
    sensitivity: row.sensitivity,
    confidence: Number(row.confidence),
    is_pinned: row.is_pinned,
    expires_at: row.expires_at,
  })
  dialog.value = true
}

async function saveMemory(): Promise<void> {
  if (!form.account_id) {
    ElMessage.warning('请选择账号。')
    return
  }
  if (!form.content.trim()) {
    ElMessage.warning('请填写记忆内容。')
    return
  }
  if (form.member_id && !form.group_id) {
    ElMessage.warning('成员级记忆必须指定作用群，否则不会被检索。')
    return
  }
  const payload: Record<string, unknown> = {
    memory_type: form.memory_type,
    content: form.content.trim(),
    sensitivity: form.sensitivity,
    confidence: form.confidence,
    is_pinned: form.is_pinned,
    expires_at: form.expires_at || null,
  }
  saving.value = true
  try {
    if (editing.value) {
      await api<MemoryRecord>(`/memories/${editing.value.id}`, { method: 'PATCH', body: payload })
      ElMessage.success('记忆已更新。')
    } else {
      await api<MemoryRecord>('/memories', {
        method: 'POST',
        body: {
          ...payload,
          account_id: form.account_id,
          group_id: form.group_id || null,
          member_id: form.member_id || null,
        },
      })
      ElMessage.success('记忆已创建。只有相关消息才会使用它。')
    }
    dialog.value = false
    await loadMemories()
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    saving.value = false
  }
}

async function togglePinned(row: MemoryRecord): Promise<void> {
  try {
    await api<MemoryRecord>(`/memories/${row.id}`, { method: 'PATCH', body: { is_pinned: !row.is_pinned } })
    ElMessage.success(row.is_pinned ? '已取消固定。' : '已固定，将优先注入。')
    await loadMemories()
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

async function removeMemory(row: MemoryRecord): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除后无法恢复：\n「${row.content.slice(0, 120)}${row.content.length > 120 ? '…' : ''}」`,
      '删除长期记忆',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await api(`/memories/${row.id}`, { method: 'DELETE' })
    ElMessage.success('记忆已删除。')
    if (memories.value.length === 1 && page.value > 1) page.value -= 1
    await loadMemories()
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  }
}

function openExtract(): void {
  extractionResult.value = null
  const preferred = filters.group_id && extractGroups.value.some((group) => group.id === filters.group_id)
    ? filters.group_id
    : extractGroups.value[0]?.id ?? ''
  extractGroupId.value = preferred
  extractDialog.value = true
}

async function runExtraction(): Promise<void> {
  if (!extractGroupId.value) {
    ElMessage.warning('请选择已开启长期记忆的群。')
    return
  }
  extracting.value = true
  extractionResult.value = null
  try {
    extractionResult.value = await api<MemoryExtractionResult>('/memories/extract', {
      method: 'POST',
      body: { group_id: extractGroupId.value },
    })
    await loadPendingCount()
    ElMessage.success(extractionResult.value.message)
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    extracting.value = false
  }
}

function openCandidates(): void {
  if (extractDialog.value) extractDialog.value = false
  candidateDialog.value = true
  candidateStatus.value = 'pending'
  candidatePage.value = 1
  void loadCandidates()
}

function onCandidateStatusChange(): void {
  candidatePage.value = 1
  void loadCandidates()
}

async function loadCandidates(): Promise<void> {
  candidateLoading.value = true
  candidateError.value = ''
  try {
    const data = await api<MemoryCandidateListPayload>('/memories/candidates', {
      query: {
        status: candidateStatus.value,
        page: candidatePage.value,
        page_size: candidatePageSize,
      },
    })
    candidates.value = data.items
    candidateTotal.value = data.total
    candidateNote.value = data.note
  } catch (cause) {
    candidateError.value = errorMessage(cause)
  } finally {
    candidateLoading.value = false
  }
}

function approveCandidate(candidate: MemoryCandidateRecord): void {
  approvalCandidate.value = candidate
  approvalSensitivity.value = 'normal'
  approvalDialog.value = true
}

async function submitCandidateApproval(): Promise<void> {
  const candidate = approvalCandidate.value
  if (!candidate) return
  candidateActionId.value = candidate.id
  try {
    await api<MemoryCandidateApproval>(`/memories/candidates/${candidate.id}/approve`, {
      method: 'POST',
      body: { sensitivity: approvalSensitivity.value },
    })
    ElMessage.success(
      approvalSensitivity.value === 'sensitive'
        ? '候选已批准为敏感记忆，不会自动注入提示词。'
        : '候选已批准为正式记忆。是否注入仍取决于群设置与相关性。',
    )
    approvalDialog.value = false
    if (candidates.value.length === 1 && candidatePage.value > 1) candidatePage.value -= 1
    await Promise.all([loadCandidates(), loadPendingCount(), loadMemories()])
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    candidateActionId.value = ''
  }
}

async function rejectCandidate(candidate: MemoryCandidateRecord): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '拒绝后该候选不会生成记忆，之后仍可重新触发提取。',
      '拒绝记忆候选',
      { confirmButtonText: '拒绝', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  candidateActionId.value = candidate.id
  try {
    await api(`/memories/candidates/${candidate.id}/reject`, { method: 'POST' })
    ElMessage.success('候选已拒绝。')
    if (candidates.value.length === 1 && candidatePage.value > 1) candidatePage.value -= 1
    await Promise.all([loadCandidates(), loadPendingCount()])
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    candidateActionId.value = ''
  }
}

function openExport(): void {
  exportIncludeSensitive.value = false
  exportDialog.value = true
}

async function exportCsv(): Promise<void> {
  exporting.value = true
  try {
    const file = await downloadApiFile('/memories/export.csv', {
      query: {
        account_id: filters.account_id || undefined,
        group_id: filters.group_id || undefined,
        memory_type: filters.memory_type || undefined,
        search: filters.search.trim() || undefined,
        include_expired: filters.include_expired,
        include_sensitive: exportIncludeSensitive.value,
      },
    })
    const url = URL.createObjectURL(file.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.filename
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success(exportIncludeSensitive.value ? '已导出（含敏感记忆）。' : '已导出（不含敏感记忆）。')
    exportDialog.value = false
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    exporting.value = false
  }
}

function openCleanup(): void {
  cleanupMode.value = 'expired'
  cleanupDays.value = 90
  cleanupDryRun.value = true
  cleanupResult.value = null
  cleanupDialog.value = true
}

async function runCleanup(): Promise<void> {
  if (!cleanupDryRun.value) {
    const scope = cleanupMode.value === 'expired' ? '所有已过期' : `创建超过 ${cleanupDays.value} 天`
    const confirmed = await typedConfirm(
      `将永久删除${scope}的未固定记忆，无法恢复。固定记忆不受影响。建议先执行「仅统计」核对范围。`,
      CLEANUP_PHRASE,
      '执行记忆清理',
    )
    if (!confirmed) return
  }
  cleaning.value = true
  cleanupResult.value = null
  try {
    const result = await api<MemoryCleanupResult>('/memories/cleanup', {
      method: 'POST',
      body: {
        mode: cleanupMode.value,
        days: cleanupMode.value === 'older_than' ? cleanupDays.value : undefined,
        dry_run: cleanupDryRun.value,
        confirm: cleanupDryRun.value ? undefined : CLEANUP_PHRASE,
      },
    })
    cleanupResult.value = result
    ElMessage.success(result.note)
    if (!result.dry_run) await loadMemories()
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    cleaning.value = false
  }
}

async function openSources(row: MemoryRecord): Promise<void> {
  sourcesDialog.value = true
  sourcesLoading.value = true
  sources.value = []
  sourcesNote.value = '只展示该记忆所属账号与群范围内的来源消息。'
  try {
    const data = await api<MemorySourcesPayload>(`/memories/${row.id}/sources`)
    sources.value = data.items
    sourcesNote.value = data.note
  } catch (cause) {
    ElMessage.error(errorMessage(cause))
  } finally {
    sourcesLoading.value = false
  }
}

onMounted(async () => {
  await reload()
})
</script>

<style scoped>
.filter-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.memory-content {
  line-height: 1.6;
  white-space: pre-wrap;
}

.memory-meta {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 5px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.note {
  margin: 10px 0 0;
  line-height: 1.6;
}

.dialog-alert {
  margin-bottom: 14px;
}

.header-badge {
  display: inline-flex;
}

.form-tip {
  margin-top: 5px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.extract-result {
  margin-top: 6px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.extract-stats {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.extract-stats .stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.extract-stats strong {
  font-size: 16px;
}

.extract-message {
  margin: 8px 0;
  line-height: 1.6;
}

.skipped {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin: 8px 0;
}

.extract-created {
  margin-top: 10px;
  line-height: 1.6;
}

.created-item {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--el-bg-color);
  white-space: pre-wrap;
}

.candidate-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.candidate-tags {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 5px;
}

.candidate-preview {
  margin: 12px 0;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
