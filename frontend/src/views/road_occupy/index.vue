<template>
  <section class="page" data-module="road_occupy">
    <header class="page-head">
      <div>
        <h2>占道施工管理</h2>
        <p class="page-desc">
          围绕占道申请、施工路段、占道面积、批准期限做登记与流转；延期与路面恢复全过程跟踪，
          面积溢占、延期材料不全、恢复日期早于施工结束时不直接放行。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记占道申请</button>
        <button class="btn" type="button" @click="exportRows">导出占道施工清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="{ warn: item.warn }">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>申请编号</span>
        <input v-model="keyword" placeholder="按申请编号检索" />
      </label>
      <label class="filter-item">
        <span>占道状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['申请编号'] ?? '—' }}</td>
          <td>{{ row['施工路段'] ?? '—' }}</td>
          <td>
            申请 {{ fmtArea(row['占道面积']) }}㎡
            <span v-if="row['批准面积'] != null" class="sub">/ 批准 {{ fmtArea(row['批准面积']) }}㎡</span>
            <span v-if="row['实际占道面积'] != null" class="sub">/ 实际 {{ fmtArea(row['实际占道面积']) }}㎡</span>
            <span v-if="row['是否溢占']" class="tag danger">面积溢占</span>
          </td>
          <td>
            <span v-if="row['当前批准截止日']">{{ row['当前批准截止日'] }}</span>
            <span v-else class="muted">待批准</span>
            <span v-if="row['延期次数']" class="tag">延期 {{ row['延期次数'] }} 次</span>
            <span v-if="row['待审批延期']" class="tag warn">延期待审</span>
          </td>
          <td>
            <span class="status" :class="statusClass(row.status)">{{ row.status }}</span>
          </td>
          <td>
            <span v-if="row['恢复日期']">{{ row['恢复日期'] }}</span>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <span v-if="row['验收日期']">{{ row['验收日期'] }}</span>
            <span v-else class="muted">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">时间轴</button>
            <button
              v-for="action in actionsFor(row)"
              :key="action.name"
              class="link"
              type="button"
              @click="openAction(action, row)"
            >
              {{ action.name }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无占道施工数据，可先登记占道申请</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条占道施工记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
    </footer>

    <!-- 登记占道申请 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记占道申请</h3>
        <div class="form-grid">
          <label v-for="f in createFields" :key="f.key" :class="{ full: f.full }">
            <span>{{ f.label }}<em v-if="f.required">*</em></span>
            <input v-model="createForm[f.key]" :placeholder="f.placeholder ?? ''" :type="f.type ?? 'text'" />
          </label>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </div>
      </div>
    </div>

    <!-- 动作表单 -->
    <div v-if="actionOpen" class="modal-mask" @click.self="actionOpen = false">
      <div class="modal">
        <h3>{{ currentAction?.name }}｜{{ currentRow?.['申请编号'] }}</h3>
        <div class="form-grid">
          <label v-for="f in currentAction?.fields ?? []" :key="f.key" :class="{ full: f.full }">
            <span>{{ f.label }}<em v-if="f.required">*</em></span>
            <select v-if="f.type === 'select'" v-model="actionForm[f.key]">
              <option v-for="opt in f.options ?? []" :key="opt" :value="opt">{{ opt }}</option>
            </select>
            <input
              v-else
              v-model="actionForm[f.key]"
              :type="f.type ?? 'text'"
              :placeholder="f.placeholder ?? ''"
            />
          </label>
          <p v-if="!(currentAction?.fields ?? []).length" class="muted">该动作无需补充信息，可直接提交。</p>
        </div>
        <p v-if="actionHint" class="form-hint">{{ actionHint }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="actionOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitAction">确认{{ currentAction?.name }}</button>
        </div>
      </div>
    </div>

    <!-- 时间轴 / 审批详情 / 竣工验收抽屉 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <div>
            <h3>{{ detail['申请编号'] }} · 占道时间轴</h3>
            <p class="muted">{{ detail['施工路段'] }}｜{{ detail['作业单位'] ?? '—' }}｜审批单位：{{ detail['审批单位'] ?? '—' }}</p>
          </div>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </header>

        <section class="drawer-section">
          <h4>一致性检查（当前许可范围 vs 恢复状态）</h4>
          <p v-if="!detail.checks.length" class="tag ok">时间轴、审批详情与竣工验收口径一致，未发现拦截项</p>
          <ul v-else class="check-list">
            <li v-for="(c, i) in detail.checks" :key="i" :class="c['级别'] === '拦截' ? 'danger' : 'warn'">
              <span class="tag" :class="c['级别'] === '拦截' ? 'danger' : 'warn'">{{ c['级别'] }}</span>
              {{ c['问题'] }}
            </li>
          </ul>
        </section>

        <section class="drawer-section">
          <h4>许可范围（审批详情）</h4>
          <div class="kv-grid">
            <div><span>申请占道面积</span><strong>{{ fmtArea(detail.permit_scope['申请占道面积']) }}㎡</strong></div>
            <div><span>批准面积</span><strong>{{ fmtArea(detail.permit_scope['批准面积']) }}㎡</strong></div>
            <div><span>实际占道面积</span>
              <strong :class="{ danger: detail.permit_scope['是否溢占'] }">{{ fmtArea(detail.permit_scope['实际占道面积']) }}㎡</strong>
            </div>
            <div><span>批准起始日</span><strong>{{ detail.permit_scope['批准起始日'] ?? '—' }}</strong></div>
            <div><span>原始批准截止日</span><strong>{{ detail.permit_scope['原始批准截止日'] ?? '—' }}</strong></div>
            <div><span>当前批准截止日</span><strong>{{ detail.permit_scope['当前批准截止日'] ?? '—' }}</strong></div>
          </div>
        </section>

        <section v-if="detail.extensions?.length" class="drawer-section">
          <h4>延期记录</h4>
          <table class="data-table inner">
            <thead>
              <tr><th>序号</th><th>申请日期</th><th>延期至</th><th>材料</th><th>状态</th><th>批准日期</th></tr>
            </thead>
            <tbody>
              <tr v-for="ext in detail.extensions" :key="ext['序号']">
                <td>延期{{ ext['序号'] }}</td>
                <td>{{ ext['申请日期'] ?? '—' }}</td>
                <td>{{ ext['延期至'] }}</td>
                <td>
                  {{ (ext['延期材料'] ?? []).join('、') || '未提交' }}
                  <span v-if="!ext['材料齐全'] && ext['状态'] === '待审批'" class="tag danger">材料不全</span>
                </td>
                <td><span class="status" :class="extStatusClass(ext['状态'])">{{ ext['状态'] }}</span></td>
                <td>{{ ext['批准日期'] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="drawer-section">
          <h4>路面恢复与竣工验收</h4>
          <div class="kv-grid">
            <div><span>施工结束日</span><strong>{{ detail.restoration['施工结束日'] ?? '—' }}</strong></div>
            <div><span>恢复日期</span><strong>{{ detail.restoration['恢复日期'] ?? '—' }}</strong></div>
            <div><span>恢复情况</span><strong>{{ detail.restoration['恢复情况'] ?? '尚未恢复' }}</strong></div>
            <div><span>验收日期</span><strong>{{ detail.restoration['验收日期'] ?? '—' }}</strong></div>
            <div><span>验收结论</span><strong>{{ detail.restoration['验收结论'] ?? '待验收' }}</strong></div>
          </div>
        </section>

        <section class="drawer-section">
          <h4>时间轴</h4>
          <ol class="timeline">
            <li v-for="(node, idx) in detail.timeline" :key="idx" :class="node['状态']">
              <span class="dot"></span>
              <div>
                <div class="tl-head">
                  <strong>{{ node['节点'] }}</strong>
                  <span class="muted">{{ node['日期'] ?? '日期待定' }}</span>
                  <span class="tag" :class="nodeStateClass(node['状态'])">{{ node['状态'] }}</span>
                </div>
                <p class="tl-content">{{ node['内容'] }}</p>
              </div>
            </li>
          </ol>
        </section>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Level = '拦截' | '提示'

interface CheckItem { 级别: Level; 问题: string }
interface TimelineNode { 节点: string; 日期: string | null; 状态: string; 内容: string }
interface Extension {
  序号: number
  延期至: string
  延期材料: string[]
  材料齐全: boolean
  状态: string
  申请日期: string | null
  批准日期: string | null
}
interface Detail {
  [key: string]: unknown
  permit_scope: Record<string, string | number | boolean | null>
  restoration: Record<string, string | boolean | null>
  checks: CheckItem[]
  timeline: TimelineNode[]
  extensions?: Extension[]
}
interface FormField {
  key: string
  label: string
  required?: boolean
  type?: string
  placeholder?: string
  options?: string[]
  full?: boolean
}
interface ActionDef {
  name: string
  hint?: string
  fields?: FormField[]
}

const ENDPOINT = '/api/road_occupy'
const columns = ["申请编号", "施工路段", "占道面积", "当前批准截止日", "占道状态", "恢复日期", "验收日期"]
const statuses = ["待审批", "已批准", "施工中", "已撤场", "已恢复", "已验收"]

// 状态 → 允许的动作；所有动作都走服务端校验，拦截项（溢占/材料不全/恢复倒置）会被退回。
const STATUS_ACTIONS: Record<string, ActionDef[]> = {
  待审批: [{
    name: '审批通过',
    hint: '批准面积不得超过申请占道面积，批准期限需有起止日。',
    fields: [
      { key: '批准面积', label: '批准面积(㎡)', type: 'number', placeholder: '不填则按申请面积批准' },
      { key: '批准起始日', label: '批准起始日', type: 'date' },
      { key: '批准截止日', label: '批准截止日', type: 'date' },
      { key: '审批单位', label: '审批单位' },
    ],
  }],
  已批准: [{
    name: '开始施工',
    hint: '实际占道面积超过批准面积即属面积溢占，不得直接开工。',
    fields: [
      { key: '实际占道面积', label: '实际占道面积(㎡)', type: 'number', required: true },
      { key: '施工开始日', label: '施工开始日', type: 'date', required: true },
    ],
  }, {
    name: '申请延期',
    hint: '延期材料至少包含：延期申请单、现场佐证材料；材料不全时审批不予放行。',
    fields: [
      { key: '延期至', label: '延期截止日', type: 'date', required: true },
      { key: '延期事由', label: '延期事由', full: true },
      { key: '延期材料', label: '延期材料（用、号分隔）', placeholder: '延期申请单、现场佐证材料', full: true },
    ],
  }],
  施工中: [{
    name: '申请延期',
    hint: '延期材料至少包含：延期申请单、现场佐证材料；材料不全时审批不予放行。',
    fields: [
      { key: '延期至', label: '延期截止日', type: 'date', required: true },
      { key: '延期事由', label: '延期事由', full: true },
      { key: '延期材料', label: '延期材料（用、号分隔）', placeholder: '延期申请单、现场佐证材料', full: true },
    ],
  }, {
    name: '审批延期',
    hint: '仅对待审批的延期生效：材料不全不得批准，可在审批结果中选择驳回。',
    fields: [
      { key: '审批结果', label: '审批结果', type: 'select', options: ['批准', '驳回'] },
      { key: '审批意见', label: '审批意见', full: true },
    ],
  }, {
    name: '确认撤场',
    fields: [
      { key: '施工结束日', label: '施工结束日', type: 'date', required: true },
      { key: '实际占道面积', label: '复测实际占道面积(㎡)', type: 'number' },
    ],
  }],
  已撤场: [{
    name: '路面恢复',
    hint: '恢复日期早于施工结束日时不允许登记。',
    fields: [
      { key: '恢复日期', label: '恢复日期', type: 'date', required: true },
      { key: '恢复情况', label: '恢复情况', full: true, placeholder: '如：沥青路面已按原结构恢复' },
    ],
  }],
  已恢复: [{
    name: '竣工验收',
    hint: '存在面积溢占、延期材料不全或恢复日期倒置等拦截项时不得验收通过。',
    fields: [
      { key: '验收日期', label: '验收日期', type: 'date', required: true },
      { key: '验收单位', label: '验收单位' },
      { key: '验收结论', label: '验收结论', placeholder: '合格 / 不合格', full: true },
    ],
  }],
  已验收: [],
}

const createFields: FormField[] = [
  { key: '申请编号', label: '申请编号', required: true, placeholder: '如 ROAD-0004' },
  { key: '作业单位', label: '作业单位' },
  { key: '施工路段', label: '施工路段', required: true, full: true },
  { key: '占道面积', label: '占道面积(㎡)', type: 'number', required: true },
  { key: '占道起止日', label: '占道起止日', placeholder: '如 2026-10-01 至 2026-10-15', full: true },
  { key: '交通疏导', label: '交通疏导方案', full: true },
  { key: '审批单位', label: '拟报审批单位', full: true },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')

const stats = computed(() => {
  const count = (s: string) => rows.value.filter(r => String(r.status) === s).length
  const overflow = rows.value.filter(r => Boolean(r['是否溢占'])).length
  const pendingExt = rows.value.filter(r => Boolean(r['待审批延期'])).length
  return [
    { label: '待审批占道', value: count('待审批') },
    { label: '施工中占道', value: count('施工中') },
    { label: '已恢复待验收', value: count('已恢复') },
    { label: '面积溢占', value: overflow, warn: overflow > 0 },
    { label: '延期待审批', value: pendingExt, warn: pendingExt > 0 },
  ]
})

const createOpen = ref(false)
const createForm = ref<Record<string, string>>({})

const actionOpen = ref(false)
const currentRow = ref<Row | null>(null)
const currentAction = ref<ActionDef | null>(null)
const actionForm = ref<Record<string, string>>({})
const actionHint = computed(() => currentAction.value?.hint ?? '')

const detail = ref<Detail | null>(null)

function fmtArea(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = typeof value === 'number' ? value : Number(String(value).replace(/[^\d.]/g, ''))
  if (Number.isNaN(n)) return String(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function statusClass(status: unknown): string {
  return { 已验收: 'ok', 已恢复: 'ok', 施工中: 'active' }[String(status)] ?? ''
}
function extStatusClass(status: unknown): string {
  return { 已批准: 'ok', 已驳回: 'danger', 待审批: 'warn' }[String(status)] ?? ''
}
function nodeStateClass(state: unknown): string {
  return { 已完成: 'ok', 进行中: 'active', 异常: 'danger', 待处理: 'muted' }[String(state)] ?? 'muted'
}

function actionsFor(row: Row): ActionDef[] {
  return STATUS_ACTIONS[String(row.status)] ?? []
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createOpen.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '占道申请登记失败')
    }
    createOpen.value = false
    infoMessage.value = payload.message ?? '占道申请已登记'
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道申请登记失败'
  }
}

function openAction(action: ActionDef, row: Row) {
  currentRow.value = row
  currentAction.value = action
  actionForm.value = {}
  actionOpen.value = true
}

async function submitAction() {
  if (!currentRow.value || !currentAction.value) return
  errorMessage.value = ''
  infoMessage.value = ''
  const payload: Record<string, string> = { action: currentAction.value.name, ...actionForm.value }
  try {
    const response = await request(`${ENDPOINT}/${currentRow.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: payload }),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.message ?? '动作未生效，请稍后重试')
    }
    actionOpen.value = false
    infoMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道施工操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('占道申请详情读取失败')
    detail.value = (await response.json()) as Detail
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道申请详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  infoMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  params.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('占道申请列表读取失败')
    const payload = await response.json()
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道施工列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.sub { color: var(--muted); font-size: 12px; }
.muted { color: var(--muted); }
.info-text { color: #067647; }
.warn-text, .danger { color: #b42318; }

.tag {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 18px;
  background: #eef2ff;
  color: #344054;
  white-space: nowrap;
}
.tag.danger { background: #fef3f2; color: #b42318; }
.tag.warn { background: #fffaeb; color: #b54708; }
.tag.ok { background: #ecfdf3; color: #067647; }
.tag.muted { background: #f2f4f7; color: #667085; }

.status { font-weight: 600; }
.status.ok { color: #067647; }
.status.active { color: #1f6feb; }
.status.danger { color: #b42318; }
.status.warn { color: #b54708; }

.modal-mask, .drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
}
.modal {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: 86vh;
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
}
.modal h3, .drawer h3 { margin: 0 0 12px; font-size: 16px; }
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}
.form-grid label { display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.form-grid label.full { grid-column: 1 / -1; }
.form-grid input, .form-grid select {
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.form-grid em { color: #b42318; font-style: normal; margin-left: 2px; }
.form-hint { margin: 10px 0 0; font-size: 12px; color: #b54708; background: #fffaeb; padding: 6px 8px; border-radius: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }

.drawer-mask { justify-content: flex-end; align-items: stretch; }
.drawer {
  width: 640px;
  max-width: calc(100vw - 24px);
  background: #f8fafc;
  height: 100%;
  overflow-y: auto;
  padding: 18px 20px;
}
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.drawer-section {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 12px;
}
.drawer-section h4 { margin: 0 0 10px; font-size: 13px; }
.check-list { margin: 0; padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.kv-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; font-size: 12px; }
.kv-grid span { display: block; color: var(--muted); margin-bottom: 2px; }
.kv-grid strong { font-size: 13px; font-weight: 600; }

.data-table.inner { font-size: 12px; }
.data-table.inner th, .data-table.inner td { padding: 5px 7px; }

.timeline { list-style: none; margin: 0; padding: 0 0 0 6px; }
.timeline li { position: relative; padding: 0 0 16px 22px; border-left: 2px solid var(--border); }
.timeline li:last-child { border-left-color: transparent; padding-bottom: 0; }
.timeline .dot {
  position: absolute;
  left: -7px;
  top: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #cbd5e1;
  border: 2px solid #fff;
}
.timeline li.已完成 .dot { background: #12b76a; }
.timeline li.进行中 .dot { background: #1f6feb; box-shadow: 0 0 0 4px rgba(31, 111, 235, 0.15); }
.timeline li.异常 .dot { background: #f04438; }
.tl-head { display: flex; align-items: center; gap: 8px; }
.tl-head strong { font-size: 13px; }
.tl-content { margin: 3px 0 0; font-size: 12px; color: #475467; }
</style>
