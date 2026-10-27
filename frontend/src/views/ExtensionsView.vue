<template>
  <div class="page">
    <PageHeader
      title="扩展与预算"
      description="查看内置工具、插件清单与预算策略。当前版本不加载或执行任何第三方插件代码；不存在任意 Shell 或文件读写工具。"
    >
      <template #actions>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" />
    <el-alert
      type="warning"
      show-icon
      :closable="false"
      title="第三方插件当前仅登记清单，不会执行代码。"
      description="插件启停与权限批准只修改本地登记状态；运行时插件沙箱属于后续版本规划。"
    />

    <el-tabs v-model="activeTab">
      <el-tab-pane label="工具" name="tools">
        <div class="card">
          <div class="card-title">
            <span>内置工具</span>
            <span class="muted">工具默认在群内关闭，高风险工具需要额外授权</span>
          </div>
          <el-table v-loading="loading" :data="tools" row-key="name">
            <el-table-column label="名称" min-width="170">
              <template #default="{ row }">
                <div class="mono">{{ row.name }}</div>
                <div class="muted">{{ row.description }}</div>
              </template>
            </el-table-column>
            <el-table-column label="风险" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="riskTag(row.risk_level)">{{ row.risk_level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="权限" min-width="160">
              <template #default="{ row }">
                <span v-if="!row.required_permissions.length" class="muted">无</span>
                <el-tag v-for="permission in row.required_permissions" :key="permission" size="small" class="gap-tag">{{ permission }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="超时" width="80">
              <template #default="{ row }">{{ row.timeout_seconds }}s</template>
            </el-table-column>
            <el-table-column label="启用" width="80">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(value: string | number | boolean) => toggleTool(row, Boolean(value))" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" @click="openTest(row)">安全测试</el-button>
              </template>
            </el-table-column>
          </el-table>
          <p class="muted note-line">
            安全测试以管理员身份执行一次，不经过群聊，不允许高风险权限。参数会在审计日志中记录（已脱敏）。
          </p>
        </div>
      </el-tab-pane>

      <el-tab-pane label="插件" name="plugins">
        <div class="card">
          <div class="card-title">
            <span>已登记插件</span>
            <el-button size="small" :loading="syncing" @click="syncPlugins">重新扫描清单</el-button>
          </div>
          <el-alert
            v-if="loadErrors.length"
            type="error"
            :closable="false"
            show-icon
            title="部分插件清单加载失败"
          >
            <div v-for="(item, index) in loadErrors" :key="index" class="mono">{{ JSON.stringify(item) }}</div>
          </el-alert>
          <el-table v-loading="loading" :data="plugins" size="small">
            <el-table-column label="插件" min-width="220">
              <template #default="{ row }">
                <div>
                  <strong>{{ row.name }}</strong>
                  <span class="muted mono"> v{{ row.version }}</span>
                  <el-tag v-if="row.is_builtin" size="small" type="success">内置</el-tag>
                </div>
                <div class="muted">{{ row.description }}</div>
              </template>
            </el-table-column>
            <el-table-column label="运行时" width="150">
              <template #default="{ row }">
                <StateTag :state="row.runtime_status" />
                <div class="muted small-text">{{ row.runtime_note }}</div>
              </template>
            </el-table-column>
            <el-table-column label="权限" min-width="180">
              <template #default="{ row }">
                <el-tag v-for="permission in row.permissions" :key="permission" size="small" class="gap-tag">{{ permission }}</el-tag>
                <span v-if="!row.permissions.length" class="muted">无</span>
              </template>
            </el-table-column>
            <el-table-column label="健康" width="110">
              <template #default="{ row }"><StateTag :state="row.health_status" /></template>
            </el-table-column>
            <el-table-column label="启用" width="80">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.enabled"
                  :disabled="!row.is_builtin"
                  @change="(value: string | number | boolean) => togglePlugin(row, Boolean(value))"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130">
              <template #default="{ row }">
                <el-button size="small" :loading="healthId === row.id" @click="checkPluginHealth(row)">健康检查</el-button>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="plugin-detail">
                  <div><span class="muted">ID：</span><span class="mono">{{ row.id }}</span></div>
                  <div v-if="row.entrypoint"><span class="muted">入口：</span><span class="mono">{{ row.entrypoint }}</span></div>
                  <div><span class="muted">高风险权限：</span>{{ row.high_risk_permissions.join('、') || '无' }}</div>
                  <div>
                    <span class="muted">健康检查声明：</span>
                    <span v-if="row.healthcheck" class="mono">
                      {{ row.healthcheck.type }} {{ row.healthcheck.path || '（无路径）' }} · 每
                      {{ row.healthcheck.interval_seconds }}s · 超时 {{ row.healthcheck.timeout_seconds }}s
                    </span>
                    <span v-else class="muted">未声明</span>
                  </div>
                  <div v-if="row.healthcheck" class="muted small-text">{{ row.healthcheck_note }}</div>
                  <div class="permission-review">
                    <span class="muted">高风险权限审批：</span>
                    <el-tag size="small" :type="row.permission_approved ? 'success' : 'warning'">
                      {{ row.permission_approved ? '已批准' : '未批准' }}
                    </el-tag>
                    <template v-if="!row.is_builtin && row.high_risk_permissions.length">
                      <el-button
                        v-if="!row.permission_approved"
                        size="small"
                        type="warning"
                        plain
                        @click="approvePlugin(row, true)"
                      >
                        批准高风险权限
                      </el-button>
                      <el-button v-else size="small" type="danger" plain @click="approvePlugin(row, false)">
                        撤销批准
                      </el-button>
                    </template>
                    <span v-if="!row.is_builtin" class="muted small-text">
                      批准只修改本地登记状态，第三方运行时仍未启用。
                    </span>
                  </div>
                  <div v-if="row.last_error" class="error-text">{{ row.last_error }}</div>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !plugins.length" description="暂无已登记插件。" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="预算" name="budgets">
        <div class="grid grid-4">
          <div class="card metric">
            <span class="metric-label">近 24 小时请求</span>
            <span class="metric-value">{{ formatNumber(usageSummary?.requests ?? 0) }}</span>
            <span class="muted">成功 {{ formatNumber(usageSummary?.successful_requests ?? 0) }} · 失败 {{ formatNumber(usageSummary?.failed_requests ?? 0) }}</span>
          </div>
          <div class="card metric">
            <span class="metric-label">近 24 小时 Token</span>
            <span class="metric-value">{{ formatNumber(usageSummary?.tokens ?? 0) }}</span>
          </div>
          <div class="card metric">
            <span class="metric-label">近 24 小时估算成本</span>
            <span class="metric-value">{{ formatCost(usageSummary?.cost, usageSummary?.currency) }}</span>
            <span class="muted">
              <el-tag size="small" :type="costStatusTag(usageSummary?.cost_status)">
                {{ costStatusLabel(usageSummary?.cost_status) }}
              </el-tag>
            </span>
          </div>
          <div class="card metric">
            <span class="metric-label">费用数据覆盖</span>
            <span class="metric-value">{{ formatNumber(usageSummary?.priced_success_requests ?? 0) }}</span>
            <span class="muted">已计价成功调用；未计价 {{ usageSummary?.unpriced_success_requests ?? 0 }} 次</span>
          </div>
        </div>

        <el-alert
          v-if="usageSummary && (usageSummary.cost_status === 'partial' || usageSummary.cost_status === 'unconfigured')"
          type="warning"
          :closable="false"
          show-icon
          title="部分成功调用没有可估算的成本"
          :description="usageSummary.cost_note"
        />

        <div class="card">
          <div class="card-title">
            <span>用量趋势</span>
            <span class="muted">
              按 {{ trends?.timezone || '配置时区' }} 聚合真实 llm_usage；未知成本保持为空
            </span>
          </div>
          <div class="filter-bar">
            <el-radio-group v-model="trendBucket" size="small" @change="onTrendBucketChange">
              <el-radio-button value="hour">按小时</el-radio-button>
              <el-radio-button value="day">按天</el-radio-button>
            </el-radio-group>
            <el-select v-model="trendPeriods" size="small" style="width: 138px" @change="loadTrends">
              <el-option v-for="option in trendPeriodOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <el-select v-model="trendGroupId" size="small" clearable placeholder="全部群" style="width: 170px" @change="loadTrends">
              <el-option v-for="group in groups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
            </el-select>
            <el-select v-model="trendProviderId" size="small" clearable placeholder="全部 Provider" style="width: 170px" @change="loadTrends">
              <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
            </el-select>
            <el-button size="small" :loading="trendLoading" @click="loadTrends">刷新趋势</el-button>
          </div>
          <div class="trend-actions">
            <span class="muted">CSV 只包含模型调用元数据，不含消息正文、提示词、API Key 或任何凭证。</span>
            <div class="action-row compact">
              <el-select v-model="exportRange" size="small" style="width: 130px">
                <el-option label="近 24 小时" value="24h" />
                <el-option label="近 7 天" value="7d" />
                <el-option label="近 30 天" value="30d" />
                <el-option label="全部记录" value="all" />
              </el-select>
              <el-button size="small" type="primary" plain :loading="exporting" @click="exportCsv">导出 CSV</el-button>
            </div>
          </div>
          <el-alert v-if="trendError" type="error" :title="trendError" show-icon :closable="false" class="check-alert" />
          <div class="trend-summary">
            <div>
              <span class="muted">窗口请求</span>
              <strong>{{ formatNumber(trends?.requests ?? 0) }}</strong>
            </div>
            <div>
              <span class="muted">成功 / 失败</span>
              <strong>{{ formatNumber(trends?.successful_requests ?? 0) }} / {{ formatNumber(trends?.failed_requests ?? 0) }}</strong>
            </div>
            <div>
              <span class="muted">Token</span>
              <strong>{{ formatNumber(trends?.tokens ?? 0) }}</strong>
            </div>
            <div>
              <span class="muted">估算费用</span>
              <strong>{{ formatCost(trends?.cost, trends?.currency) }}</strong>
              <el-tag size="small" :type="costStatusTag(trends?.cost_status)">{{ costStatusLabel(trends?.cost_status) }}</el-tag>
            </div>
          </div>
          <el-alert
            v-if="trends && (trends.cost_status === 'partial' || trends.cost_status === 'unconfigured')"
            type="warning"
            :closable="false"
            show-icon
            title="窗口内存在无法计价的成功调用"
            :description="trends.cost_note"
          />
          <el-table v-loading="trendLoading" :data="trendRows" size="small" max-height="360" class="trend-table">
            <el-table-column label="时间" width="148">
              <template #default="{ row }"><span class="mono">{{ row.bucket_label }}</span></template>
            </el-table-column>
            <el-table-column label="请求趋势" min-width="170">
              <template #default="{ row }">
                <div class="trend-bar-track">
                  <div class="trend-bar" :style="{ width: trendBarWidth(row.requests) }" />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="请求" width="105">
              <template #default="{ row }">
                {{ formatNumber(row.requests) }}
                <div class="muted small-text">成功 {{ row.successful_requests }} · 失败 {{ row.failed_requests }}</div>
              </template>
            </el-table-column>
            <el-table-column label="Token" width="95">
              <template #default="{ row }">{{ formatNumber(row.tokens) }}</template>
            </el-table-column>
            <el-table-column label="估算费用" min-width="160">
              <template #default="{ row }">
                <span>{{ formatCost(row.cost, row.currency) }}</span>
                <el-tag v-if="row.requests" size="small" :type="costStatusTag(row.cost_status)" class="gap-tag">
                  {{ costStatusLabel(row.cost_status) }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!trendLoading && trends && !trends.requests" description="该窗口内没有真实模型调用。" :image-size="60" />
          <p class="muted note-line">
            趋势按真实本地记录分桶，空桶保留为 0；未配置单价的调用费用显示为 “—”，不会补成 0。
            CSV 导出使用当前群 / Provider 筛选，导出动作会写入审计日志。
          </p>
        </div>

        <div class="grid grid-2">
          <div class="card">
            <div class="card-title">
              <span>按 Provider 用量（24 小时）</span>
              <span class="muted">真实本地记录，仅含已有调用的 Provider</span>
            </div>
            <el-table v-loading="loading" :data="providerUsageRows" size="small" max-height="300">
              <el-table-column label="Provider" min-width="170">
                <template #default="{ row }">
                  <div>
                    {{ row.provider_name || '未记录 Provider' }}
                    <el-tag v-if="row.is_mock" size="small" type="warning">Mock</el-tag>
                  </div>
                  <div class="muted mono">{{ row.model || row.provider_type }}</div>
                </template>
              </el-table-column>
              <el-table-column label="请求" width="105">
                <template #default="{ row }">
                  {{ formatNumber(row.requests) }}
                  <div class="muted small-text">成功 {{ row.successful_requests }} · 失败 {{ row.failed_requests }}</div>
                </template>
              </el-table-column>
              <el-table-column label="Token" width="90">
                <template #default="{ row }">{{ formatNumber(row.tokens) }}</template>
              </el-table-column>
              <el-table-column label="估算费用" min-width="150">
                <template #default="{ row }">
                  <div>{{ formatCost(row.cost, row.currency) }}</div>
                  <el-tag size="small" :type="costStatusTag(row.cost_status)">{{ costStatusLabel(row.cost_status) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!loading && !providerUsageRows.length" description="近 24 小时没有模型调用。" :image-size="60" />
          </div>

          <div class="card">
            <div class="card-title">
              <span>按群用量（24 小时）</span>
              <span class="muted">用于配置群级请求/Token/费用上限</span>
            </div>
            <el-table v-loading="loading" :data="groupUsageRows" size="small" max-height="300">
              <el-table-column label="群" min-width="170">
                <template #default="{ row }">{{ row.group_name || row.group_id || '未关联群' }}</template>
              </el-table-column>
              <el-table-column label="请求" width="105">
                <template #default="{ row }">
                  {{ formatNumber(row.requests) }}
                  <div class="muted small-text">成功 {{ row.successful_requests }} · 失败 {{ row.failed_requests }}</div>
                </template>
              </el-table-column>
              <el-table-column label="Token" width="90">
                <template #default="{ row }">{{ formatNumber(row.tokens) }}</template>
              </el-table-column>
              <el-table-column label="估算费用" min-width="150">
                <template #default="{ row }">
                  <div>{{ formatCost(row.cost, row.currency) }}</div>
                  <el-tag size="small" :type="costStatusTag(row.cost_status)">{{ costStatusLabel(row.cost_status) }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!loading && !groupUsageRows.length" description="近 24 小时没有群内模型调用。" :image-size="60" />
          </div>
        </div>

        <div class="card">
          <div class="card-title">
            <span>预算 vs 实际用量</span>
            <span class="muted">按策略自身窗口统计；达到上限即阻断下一次模型调用</span>
          </div>
          <el-table v-loading="loading" :data="budgets" size="small">
            <el-table-column label="作用域" width="170">
              <template #default="{ row }">{{ scopeLabel(row) }}</template>
            </el-table-column>
            <el-table-column label="窗口" width="80">
              <template #default="{ row }">{{ windowLabel(row.window) }}</template>
            </el-table-column>
            <el-table-column label="指标" width="95">
              <template #default="{ row }">{{ metricLabel(row.metric) }}</template>
            </el-table-column>
            <el-table-column label="上限" width="120">
              <template #default="{ row }">{{ usageValue(row, row.limit_value) }}</template>
            </el-table-column>
            <el-table-column label="已用" width="130">
              <template #default="{ row }">{{ usageValue(row, row.used ?? 0) }}</template>
            </el-table-column>
            <el-table-column label="剩余" width="130">
              <template #default="{ row }">{{ usageValue(row, row.remaining ?? 0) }}</template>
            </el-table-column>
            <el-table-column label="告警阈值" width="95">
              <template #default="{ row }">{{ Math.round((row.warn_threshold ?? 0) * 100) }}%</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="budgetStateTag(row.state)">{{ budgetStateLabel(row.state) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="费用数据" min-width="150">
              <template #default="{ row }">
                <template v-if="row.metric === 'cost'">
                  <el-tag size="small" :type="costStatusTag(row.cost_status)">{{ costStatusLabel(row.cost_status) }}</el-tag>
                  <div v-if="row.unpriced_success_requests" class="muted small-text">
                    未计价成功调用 {{ row.unpriced_success_requests }} 次
                  </div>
                </template>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="75">
              <template #default="{ row }">
                <el-switch :model-value="row.enabled" @change="(value: string | number | boolean) => toggleBudget(row, Boolean(value))" />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="85">
              <template #default="{ row }">
                <el-button size="small" @click="openBudget(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!loading && !budgets.length" description="尚未配置预算。没有预算策略时不会因额度阻断调用，请自行控制成本。" />
          <p class="muted note-line">
            费用上限依赖 Provider 的输入/输出单价：费用预算覆盖到未配置单价的 Provider 时，调用会被阻断，避免无法计费的调用绕过上限；Mock 视为零外部费用。
            预算按已记录用量执行，单次调用可能使累计略超上限。
          </p>
          <div class="action-row">
            <el-button type="primary" @click="openBudget(null)">新增预算策略</el-button>
            <el-select v-model="checkAccountId" clearable placeholder="选择账号" style="width: 170px">
              <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
            </el-select>
            <el-select v-model="checkGroupId" clearable placeholder="选择群" style="width: 180px">
              <el-option v-for="group in groups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
            </el-select>
            <el-select v-model="checkProviderId" clearable placeholder="选择 Provider" style="width: 170px">
              <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
            </el-select>
            <el-select v-model="checkFeature" clearable placeholder="选择功能" style="width: 160px">
              <el-option v-for="feature in FEATURE_OPTIONS" :key="feature.value" :label="feature.label" :value="feature.value" />
            </el-select>
            <el-button @click="checkBudget">检查当前预算</el-button>
          </div>
          <p class="muted note-line">检查费用预算时请同时选择 Provider，否则无法判断该 Provider 是否具备可估算的单价。</p>
          <el-alert
            v-if="checkResult"
            class="check-alert"
            :type="checkResult.allowed ? 'success' : 'error'"
            :closable="false"
            show-icon
            :title="checkResult.allowed ? '当前未触发额度阻断' : '当前会被预算阻断'"
          >
            <div v-for="block in checkResult.blocks" :key="block.policy_id" class="muted">
              {{ blockScopeLabel(block) }} · {{ block.window }} · {{ block.metric }}：
              已用 {{ block.used }} / 上限 {{ block.limit }}
              <template v-if="block.reason === 'cost_unavailable'"> · Provider 未配置单价</template>
            </div>
            <div v-if="checkResult.note" class="muted">{{ checkResult.note }}</div>
          </el-alert>
        </div>

        <div class="card">
          <div class="card-title">
            <span>预算告警历史</span>
            <el-button size="small" :loading="alertsLoading" @click="loadAlerts(alertPage)">刷新告警</el-button>
          </div>
          <div class="filter-bar">
            <el-select v-model="alertLevel" size="small" clearable placeholder="全部级别" style="width: 140px" @change="onAlertFilterChange">
              <el-option label="接近上限" value="warning" />
              <el-option label="已超限" value="exceeded" />
            </el-select>
            <el-select v-model="alertScopeType" size="small" clearable placeholder="全部作用域" style="width: 150px" @change="onAlertFilterChange">
              <el-option label="全局" value="global" />
              <el-option label="按账号" value="account" />
              <el-option label="按群" value="group" />
              <el-option label="按 Provider" value="provider" />
              <el-option label="按功能" value="feature" />
            </el-select>
          </div>
          <el-alert v-if="alertsError" type="error" :title="alertsError" show-icon :closable="false" class="check-alert" />
          <el-table v-loading="alertsLoading" :data="alerts" size="small">
            <el-table-column label="时间" width="152">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="级别" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.level === 'exceeded' ? 'danger' : 'warning'">
                  {{ row.level === 'exceeded' ? '已超限' : '接近上限' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="作用域" width="170">
              <template #default="{ row }">
                <div>{{ row.scope_name }}</div>
                <div class="muted small-text">{{ windowLabel(row.window) }} · {{ metricLabel(row.metric) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="已用 / 上限" width="155">
              <template #default="{ row }">
                <span class="mono">{{ metricText(row.metric, row.used) }} / {{ metricText(row.metric, row.limit) }}</span>
                <div class="muted small-text">{{ Math.round((row.usage_ratio ?? 0) * 1000) / 10 }}% · {{ row.period_key }}</div>
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="280">
              <template #default="{ row }">{{ row.message }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!alertsLoading && !alerts.length" description="还没有预算告警。达到策略告警阈值或上限后才会生成事件。" :image-size="60" />
          <div v-if="alertTotal > alertPageSize" class="pagination">
            <el-pagination
              v-model:current-page="alertPage"
              :page-size="alertPageSize"
              :total="alertTotal"
              layout="prev, pager, next, total"
              @current-change="loadAlerts"
            />
          </div>
          <p class="muted note-line">
            {{ alertsNote || '告警事件按策略、统计周期与级别去重；每个新事件写入审计并通过 SSE 推送，不调用外部服务。' }}
          </p>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="testDialog" :title="`安全测试：${testTool?.name ?? ''}`" width="600px" :close-on-click-modal="false">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="仅测试工具本身，不经过群聊；高风险权限被拒绝。"
      />
      <el-form label-width="90px">
        <el-form-item label="参数 JSON">
          <el-input v-model="testArguments" type="textarea" :rows="6" class="mono-input" placeholder='{"expression": "1+2*3"}' />
        </el-form-item>
        <el-form-item label="Schema">
          <pre class="schema-pre">{{ JSON.stringify(testTool?.input_schema ?? {}, null, 2) }}</pre>
        </el-form-item>
      </el-form>
      <div v-if="testResult" class="test-output">
        <StateTag :state="testResult.ok ? 'success' : 'failed'" :label="testResult.ok ? '执行成功' : '执行失败'" />
        <div v-if="testResult.content" class="reply-text">{{ testResult.content }}</div>
        <div v-if="testResult.error_code" class="muted">{{ testResult.error_code }}：{{ testResult.error_message }}</div>
        <pre class="schema-pre">{{ JSON.stringify(testResult.data, null, 2) }}</pre>
      </div>
      <template #footer>
        <el-button @click="testDialog = false">关闭</el-button>
        <el-button type="primary" :loading="testing" @click="runToolTest">执行测试</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="budgetDialog" :title="budgetEditing ? '编辑预算策略' : '新增预算策略'" width="520px" :close-on-click-modal="false">
      <el-form label-width="120px">
        <el-form-item label="作用域">
          <el-select v-model="budgetForm.scope_type" style="width: 100%" @change="onScopeChange">
            <el-option label="全局" value="global" />
            <el-option label="按账号" value="account" />
            <el-option label="按群" value="group" />
            <el-option label="按 Provider" value="provider" />
            <el-option label="按功能" value="feature" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="budgetForm.scope_type === 'account'" label="账号" required>
          <el-select v-model="budgetForm.scope_id" style="width: 100%" placeholder="选择账号">
            <el-option v-for="account in accounts" :key="account.id" :label="account.display_name" :value="account.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="budgetForm.scope_type === 'group'" label="群" required>
          <el-select v-model="budgetForm.scope_id" style="width: 100%" placeholder="选择群">
            <el-option v-for="group in groups" :key="group.id" :label="group.name || group.platform_group_id" :value="group.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="budgetForm.scope_type === 'provider'" label="Provider" required>
          <el-select v-model="budgetForm.scope_id" style="width: 100%" placeholder="选择 Provider">
            <el-option v-for="provider in providers" :key="provider.id" :label="provider.name" :value="provider.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="budgetForm.scope_type === 'feature'" label="功能" required>
          <el-select v-model="budgetForm.scope_id" style="width: 100%" placeholder="选择功能">
            <el-option v-for="feature in FEATURE_OPTIONS" :key="feature.value" :label="feature.label" :value="feature.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="窗口">
          <el-select v-model="budgetForm.window" style="width: 100%">
            <el-option v-for="window in windows" :key="window" :label="windowLabel(window)" :value="window" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标">
          <el-select v-model="budgetForm.metric" style="width: 100%">
            <el-option label="请求次数" value="requests" />
            <el-option label="Token" value="tokens" />
            <el-option label="估算成本" value="cost" />
          </el-select>
        </el-form-item>
        <el-form-item label="上限">
          <el-input-number
            v-model="budgetForm.limit_value"
            :min="0.000001"
            :step="budgetForm.metric === 'cost' ? 0.001 : 1"
            :precision="budgetForm.metric === 'cost' ? 6 : 0"
          />
        </el-form-item>
        <el-form-item label="告警阈值">
          <el-input-number
            v-model="budgetForm.warn_threshold"
            :min="0"
            :max="1"
            :step="0.05"
            :precision="2"
          />
          <span class="muted threshold-hint">用量达到上限的该比例时生成一次 warning 告警；0 表示关闭接近上限告警。</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="budgetForm.enabled" />
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="接近上限会生成告警事件，达到上限仍会直接阻断模型调用。"
          description="告警只反映本地真实用量，每个策略每周期最多记录一次同级别事件，并写入审计；预算按已记录用量执行，单次调用可能使累计略超上限。"
        />
        <el-alert
          v-if="budgetForm.metric === 'cost'"
          class="check-alert"
          type="warning"
          :closable="false"
          show-icon
          title="费用上限要求 Provider 配置 Token 单价"
          description="未配置输入/输出单价的 Provider 在被费用预算覆盖时会被阻断，Mock 视为零外部费用。请先在「模型 API」中填写单价。"
        />
      </el-form>
      <template #footer>
        <el-button @click="budgetDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveBudget">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, downloadApiFile, errorMessage } from '@/api/client'
import type {
  Account,
  BudgetAlert,
  BudgetAlertList,
  BudgetCheck,
  BudgetPolicy,
  Group,
  LLMProvider,
  PluginRecord,
  ToolRecord,
  UsageBucket,
  UsageSummary,
  UsageTrendPoint,
  UsageTrends,
} from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import StateTag from '@/components/StateTag.vue'
import { FEATURE_OPTIONS, featureLabel } from '@/constants/budgets'
import { costStatusLabel, costStatusTag, formatCost, formatNumber, formatTime, riskTag } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface ToolResultView {
  ok: boolean
  content: string
  error_code: string | null
  error_message: string | null
  data: Record<string, unknown>
}

const activeTab = ref('tools')
const loading = ref(false)
const syncing = ref(false)
const testing = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)

const tools = ref<ToolRecord[]>([])
const plugins = ref<PluginRecord[]>([])
const loadErrors = ref<unknown[]>([])
const healthId = ref<string | null>(null)
const budgets = ref<BudgetPolicy[]>([])
const usageSummary = ref<UsageSummary | null>(null)
const groups = ref<Group[]>([])
const providers = ref<LLMProvider[]>([])
const accounts = ref<Account[]>([])

const trendBucket = ref<'hour' | 'day'>('hour')
const trendPeriods = ref(24)
const trendGroupId = ref('')
const trendProviderId = ref('')
const trends = ref<UsageTrends | null>(null)
const trendLoading = ref(false)
const trendError = ref<string | null>(null)
const exportRange = ref('7d')
const exporting = ref(false)

const alerts = ref<BudgetAlert[]>([])
const alertTotal = ref(0)
const alertsLoading = ref(false)
const alertsError = ref<string | null>(null)
const alertsNote = ref('')
const alertLevel = ref('')
const alertScopeType = ref('')
const alertPage = ref(1)
const alertPageSize = ref(20)

const testDialog = ref(false)
const testTool = ref<ToolRecord | null>(null)
const testArguments = ref('{}')
const testResult = ref<ToolResultView | null>(null)

const budgetDialog = ref(false)
const budgetEditing = ref<BudgetPolicy | null>(null)
const budgetForm = reactive({
  scope_type: 'global',
  scope_id: '',
  window: 'day',
  metric: 'requests',
  limit_value: 100,
  warn_threshold: 0.8,
  enabled: true,
})
const windows = ['hour', 'day', 'week', 'month', 'all']
const checkAccountId = ref('')
const checkGroupId = ref('')
const checkProviderId = ref('')
const checkFeature = ref('')
const checkResult = ref<BudgetCheck | null>(null)

function windowLabel(value: string): string {
  return { hour: '每小时', day: '每日', week: '每周', month: '每月', all: '累计' }[value] ?? value
}

function metricLabel(value: string): string {
  return { requests: '请求次数', tokens: 'Token', cost: '估算成本' }[value] ?? value
}

function scopeLabel(policy: BudgetPolicy): string {
  if (policy.scope_type === 'global') return '全局'
  if (policy.scope_type === 'account') {
    const account = accounts.value.find((item) => item.id === policy.scope_id)
    return `账号：${account?.display_name || policy.scope_id}`
  }
  if (policy.scope_type === 'group') {
    const group = groups.value.find((item) => item.id === policy.scope_id)
    return `群：${group?.name || group?.platform_group_id || policy.scope_id}`
  }
  if (policy.scope_type === 'feature') {
    return `功能：${featureLabel(policy.scope_id)}`
  }
  const provider = providers.value.find((item) => item.id === policy.scope_id)
  return `Provider：${provider?.name || policy.scope_id}`
}

function blockScopeLabel(block: BudgetCheck['blocks'][number]): string {
  if (block.scope_type === 'global') return '全局'
  if (block.scope_type === 'account') {
    const account = accounts.value.find((item) => item.id === block.scope_id)
    return `账号：${account?.display_name || block.scope_id}`
  }
  if (block.scope_type === 'group') {
    const group = groups.value.find((item) => item.id === block.scope_id)
    return `群：${group?.name || group?.platform_group_id || block.scope_id}`
  }
  if (block.scope_type === 'feature') return `功能：${featureLabel(block.scope_id)}`
  return `Provider：${block.scope_id}`
}

const providerUsageRows = computed<UsageBucket[]>(
  () => (usageSummary.value?.by_provider ?? []).filter((row) => row.requests > 0),
)
const groupUsageRows = computed<UsageBucket[]>(
  () => (usageSummary.value?.by_group ?? []).filter((row) => row.requests > 0),
)

const trendPeriodOptions = computed(() =>
  trendBucket.value === 'hour'
    ? [
        { value: 24, label: '近 24 小时' },
        { value: 72, label: '近 72 小时' },
        { value: 168, label: '近 7 天' },
        { value: 720, label: '近 30 天' },
      ]
    : [
        { value: 7, label: '近 7 天' },
        { value: 30, label: '近 30 天' },
        { value: 90, label: '近 90 天' },
        { value: 365, label: '近 365 天' },
      ],
)

const trendRows = computed<UsageTrendPoint[]>(() => trends.value?.items ?? [])

const maxTrendRequests = computed(() =>
  Math.max(1, ...trendRows.value.map((row) => row.requests)),
)

function trendBarWidth(requests: number): string {
  if (requests <= 0) return '0%'
  return `${Math.max(4, (requests / maxTrendRequests.value) * 100)}%`
}

function metricText(metric: string, value: number): string {
  if (metric === 'cost') return formatCost(value, 'USD')
  return formatNumber(value)
}

function usageValue(policy: BudgetPolicy, value: number): string {
  return metricText(policy.metric, value)
}

function budgetStateLabel(state?: string): string {
  return { ok: '正常', warning: '接近上限', exceeded: '已超限', disabled: '已停用' }[state ?? ''] ?? '—'
}

function budgetStateTag(state?: string): 'success' | 'warning' | 'danger' | 'info' {
  if (state === 'exceeded') return 'danger'
  if (state === 'warning') return 'warning'
  if (state === 'disabled') return 'info'
  return 'success'
}

function onTrendBucketChange(): void {
  trendPeriods.value = trendBucket.value === 'hour' ? 24 : 7
  void loadTrends()
}

async function loadTrends(): Promise<void> {
  trendLoading.value = true
  trendError.value = null
  try {
    const query: Record<string, string | number> = {
      bucket: trendBucket.value,
      periods: trendPeriods.value,
    }
    if (trendGroupId.value) query.group_id = trendGroupId.value
    if (trendProviderId.value) query.provider_id = trendProviderId.value
    trends.value = await api<UsageTrends>('/usage/trends', { query })
  } catch (err) {
    trendError.value = errorMessage(err)
  } finally {
    trendLoading.value = false
  }
}

function onAlertFilterChange(): void {
  void loadAlerts(1)
}

async function loadAlerts(page = alertPage.value): Promise<void> {
  alertsLoading.value = true
  alertsError.value = null
  try {
    const query: Record<string, string | number> = {
      page,
      page_size: alertPageSize.value,
    }
    if (alertLevel.value) query.level = alertLevel.value
    if (alertScopeType.value) query.scope_type = alertScopeType.value
    const data = await api<BudgetAlertList>('/budgets/alerts', { query })
    alerts.value = data.items
    alertTotal.value = data.total
    alertPage.value = data.page
    alertsNote.value = data.note
  } catch (err) {
    alertsError.value = errorMessage(err)
  } finally {
    alertsLoading.value = false
  }
}

async function exportCsv(): Promise<void> {
  const hoursByRange: Record<string, number | null> = {
    '24h': 24,
    '7d': 24 * 7,
    '30d': 24 * 30,
    all: null,
  }
  const hours = hoursByRange[exportRange.value] ?? null
  const query: Record<string, string> = {}
  if (hours !== null) {
    const now = new Date()
    query.since = new Date(now.getTime() - hours * 3600_000).toISOString()
    query.until = now.toISOString()
  }
  if (trendGroupId.value) query.group_id = trendGroupId.value
  if (trendProviderId.value) query.provider_id = trendProviderId.value
  exporting.value = true
  try {
    const file = await downloadApiFile('/usage/export.csv', { query })
    const url = URL.createObjectURL(file.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = file.filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    ElMessage.success(`已导出 ${file.filename}；导出动作已写入审计日志。`)
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    exporting.value = false
  }
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [toolData, pluginData, budgetData, summary, groupData, providerData, accountData] = await Promise.all([
      api<{ items: ToolRecord[] }>('/tools'),
      api<{ items: PluginRecord[]; load_errors: unknown[] }>('/plugins'),
      api<{ items: BudgetPolicy[] }>('/budgets'),
      api<UsageSummary>('/usage/summary', { query: { hours: 24 } }),
      api<{ items: Group[] }>('/groups'),
      api<{ items: LLMProvider[] }>('/providers'),
      api<{ items: Account[] }>('/accounts'),
    ])
    tools.value = toolData.items
    plugins.value = pluginData.items
    loadErrors.value = pluginData.load_errors ?? []
    budgets.value = budgetData.items
    usageSummary.value = summary
    groups.value = groupData.items
    providers.value = providerData.items
    accounts.value = accountData.items
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
  await Promise.all([loadTrends(), loadAlerts(1)])
}

async function toggleTool(tool: ToolRecord, enabled: boolean): Promise<void> {
  try {
    await api(`/tools/${encodeURIComponent(tool.name)}`, { method: 'PATCH', body: { enabled } })
    ElMessage.success(enabled ? '工具已启用。' : '工具已停用。')
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function openTest(tool: ToolRecord): void {
  testTool.value = tool
  testResult.value = null
  testArguments.value = tool.name === 'calculator' ? '{"expression": "1+2*3"}' : '{}'
  testDialog.value = true
}

async function runToolTest(): Promise<void> {
  if (!testTool.value) return
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(testArguments.value || '{}') as Record<string, unknown>
  } catch {
    ElMessage.warning('参数必须是合法 JSON 对象。')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api<ToolResultView>(`/tools/${encodeURIComponent(testTool.value.name)}/test`, {
      method: 'POST',
      body: { arguments: parsed },
    })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    testing.value = false
  }
}

async function syncPlugins(): Promise<void> {
  syncing.value = true
  try {
    const data = await api<{ loaded: number; errors: unknown[] }>('/plugins/sync', { method: 'POST' })
    ElMessage.success(`已扫描 ${data.loaded} 个插件清单${data.errors.length ? `，${data.errors.length} 个失败` : ''}。`)
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    syncing.value = false
  }
}

async function togglePlugin(plugin: PluginRecord, enabled: boolean): Promise<void> {
  try {
    await api(`/plugins/${plugin.id}/enable`, { method: 'POST', body: { enabled } })
    ElMessage.success(enabled ? '插件已启用。' : '插件已停用。')
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function approvePlugin(plugin: PluginRecord, approved: boolean): Promise<void> {
  if (!approved) {
    try {
      await ElMessageBox.confirm(
        `撤销「${plugin.name}」的高风险权限批准？已启用的第三方运行时会被停用；本版本本就不执行第三方代码。`,
        '撤销权限批准',
        { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  try {
    await api(`/plugins/${plugin.id}/approve`, { method: 'POST', body: { approved } })
    ElMessage.success(
      approved ? '高风险权限已批准；第三方插件运行时仍未启用。' : '已撤销高风险权限批准。',
    )
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function checkPluginHealth(plugin: PluginRecord): Promise<void> {
  healthId.value = plugin.id
  try {
    const data = await api<PluginRecord>(`/plugins/${plugin.id}/health`)
    if (data.health_status === 'healthy') {
      ElMessage.success('插件健康。')
    } else {
      ElMessage.warning(`健康状态：${data.health_status}${data.last_error ? ` · ${data.last_error}` : ''}`)
    }
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    healthId.value = null
  }
}

function openBudget(policy: BudgetPolicy | null): void {
  budgetEditing.value = policy
  Object.assign(budgetForm, {
    scope_type: policy?.scope_type ?? 'global',
    scope_id: policy?.scope_id ?? '',
    window: policy?.window ?? 'day',
    metric: policy?.metric ?? 'requests',
    limit_value: policy?.limit_value ?? 100,
    warn_threshold: policy?.warn_threshold ?? 0.8,
    enabled: policy?.enabled ?? true,
  })
  budgetDialog.value = true
}

function onScopeChange(): void {
  budgetForm.scope_id = ''
}

async function saveBudget(): Promise<void> {
  if (budgetForm.scope_type !== 'global' && !budgetForm.scope_id) {
    ElMessage.warning('请选择作用域对象。')
    return
  }
  if (budgetForm.limit_value <= 0) {
    ElMessage.warning('预算上限必须大于 0；如需暂停预算，请关闭“启用”开关。')
    return
  }
  saving.value = true
  try {
    if (budgetEditing.value) {
      await api(`/budgets/${budgetEditing.value.id}`, { method: 'PUT', body: budgetForm })
    } else {
      await api('/budgets', { method: 'POST', body: budgetForm })
    }
    ElMessage.success('预算策略已保存。')
    budgetDialog.value = false
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}

async function toggleBudget(policy: BudgetPolicy, enabled: boolean): Promise<void> {
  try {
    await api(`/budgets/${policy.id}`, {
      method: 'PUT',
      body: {
        scope_type: policy.scope_type,
        scope_id: policy.scope_id,
        window: policy.window,
        metric: policy.metric,
        limit_value: policy.limit_value,
        warn_threshold: policy.warn_threshold,
        enabled,
      },
    })
    ElMessage.success(enabled ? '预算策略已启用。' : '预算策略已停用。')
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function checkBudget(): Promise<void> {
  try {
    const query: Record<string, string> = {}
    if (checkAccountId.value) query.account_id = checkAccountId.value
    if (checkGroupId.value) query.group_id = checkGroupId.value
    if (checkProviderId.value) query.provider_id = checkProviderId.value
    if (checkFeature.value) query.feature = checkFeature.value
    checkResult.value = await api<BudgetCheck>('/budgets/check', { query })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

onMounted(loadAll)
</script>

<style scoped>
.gap-tag {
  margin-right: 4px;
  margin-bottom: 4px;
}

.note-line {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.small-text {
  font-size: 11px;
  margin-top: 2px;
}

.plugin-detail {
  padding: 8px 16px 12px 48px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.permission-review {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.error-text {
  color: var(--el-color-danger);
}

.action-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
  align-items: center;
}

.check-alert {
  margin-top: 12px;
}

.schema-pre {
  background: var(--app-surface-soft);
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  margin: 0;
  width: 100%;
  white-space: pre-wrap;
  word-break: break-word;
}

.test-output {
  border-top: 1px dashed var(--app-border);
  margin-top: 8px;
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.reply-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.mono-input :deep(textarea) {
  font-family: var(--app-mono);
}

.grid + .card,
.card + .card {
  margin-top: 16px;
}

.trend-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  font-size: 12px;
}

.action-row.compact {
  margin-top: 0;
}

.trend-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 28px;
  margin-bottom: 12px;
}

.trend-summary > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.trend-summary strong {
  font-size: 16px;
}

.trend-table {
  margin-top: 4px;
}

.trend-bar-track {
  width: 100%;
  height: 10px;
  border-radius: 5px;
  background: var(--app-border-soft);
  overflow: hidden;
}

.trend-bar {
  height: 100%;
  border-radius: 5px;
  background: var(--el-color-primary);
}

.threshold-hint {
  margin-left: 10px;
  font-size: 12px;
  line-height: 1.5;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
