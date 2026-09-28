<template>
  <section class="page" data-module="road_occupy">
    <header class="page-head">
      <div>
        <h2>占道施工管理</h2>
        <p class="page-desc">
          把占道申请、施工路段、占道面积、批准期限串成时间轴；跟踪延期审批与路面恢复，
          面积溢占、延期材料不全、恢复日期早于施工结束时一律拦截，不得放行。
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
        <strong class="stat-value" :class="{ 'stat-warn': item.warn }">{{ item.value }}</strong>
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
          <td v-for="column in columns" :key="column">
            <button v-if="column === '申请编号'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <span v-else-if="column === '占道状态'" :class="{ 'tag-warn': row.面积溢占 }">
              {{ row[column] ?? '—' }}
            </span>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actionsFor(row)"
              :key="action.name"
              class="link"
              :class="{ 'link-danger': action.danger }"
              type="button"
              @click="openAction(action.name, row)"
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
    </footer>

    <!-- 动作表单弹窗：审批 / 开工 / 延期 / 撤场 / 恢复 / 验收 / 登记 -->
    <div v-if="form.show" class="modal-mask" @click.self="closeForm">
      <div class="modal">
        <header class="modal-head">
          <h3>{{ form.title }}</h3>
          <button class="link" type="button" @click="closeForm">关闭</button>
        </header>
        <p v-if="form.target" class="modal-target">
          {{ form.target.申请编号 }}｜{{ form.target.施工路段 }}
        </p>

        <div v-if="form.action === '申请延期'" class="doc-check">
          <p class="doc-title">延期必备材料（三份缺一不可，否则审批不予放行）：</p>
          <label v-for="doc in extensionDocs" :key="doc" class="doc-item">
            <input v-model="form.values.延期材料" type="checkbox" :value="doc" />
            <span>{{ doc }}</span>
          </label>
        </div>

        <form class="modal-form" @submit.prevent="submitForm">
          <label v-for="field in form.fields" :key="field.name" class="modal-field"
                 :class="{ 'field-wide': field.type === 'textarea' }">
            <span>{{ field.label }}</span>
            <textarea v-if="field.type === 'textarea'" v-model="form.values[field.name]"
                      :placeholder="field.placeholder" rows="2"></textarea>
            <input v-else :type="field.type ?? 'text'" v-model="form.values[field.name]"
                   :placeholder="field.placeholder" :step="field.type === 'number' ? '0.01' : undefined" />
          </label>
          <p v-if="form.hint" class="form-hint">{{ form.hint }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="closeForm">取消</button>
            <button class="btn primary" type="submit">确认提交</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情抽屉：审批详情 / 时间轴 / 竣工验收，三处读同一份接口数据 -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <div>
            <h3>{{ detail.申请编号 }}</h3>
            <p>{{ detail.施工路段 }} · {{ detail.作业单位 || '作业单位未填' }}</p>
          </div>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>

        <div class="drawer-body">
          <section class="panel">
            <h4>审批详情（当前许可范围）</h4>
            <dl class="kv-grid">
              <div><dt>审批单位</dt><dd>{{ detail.审批详情.审批单位 || '—' }}</dd></div>
              <div><dt>当前状态</dt><dd>{{ detail.status }}</dd></div>
              <div><dt>申请占道面积</dt><dd>{{ fmtArea(detail.许可范围.申请占道面积) }}</dd></div>
              <div><dt>批准占道面积</dt><dd>{{ fmtArea(detail.许可范围.批准占道面积) }}</dd></div>
              <div><dt>实际占道面积</dt><dd>
                <span :class="{ 'tag-warn': detail.许可范围.面积溢占 }">
                  {{ fmtArea(detail.许可范围.实际占道面积) }}
                </span>
              </dd></div>
              <div><dt>许可范围结论</dt><dd>
                <span :class="detail.许可范围.面积溢占 ? 'tag-warn' : 'tag-ok'">
                  {{ detail.许可范围.许可范围说明 }}
                </span>
              </dd></div>
              <div><dt>申请期限</dt><dd>{{ detail.许可范围.申请开始日 || '—' }} ~ {{ detail.许可范围.申请结束日 || '—' }}</dd></div>
              <div><dt>当前批准期限</dt><dd>
                {{ detail.许可范围.批准开始日 || '—' }} ~ {{ detail.许可范围.批准结束日 || '—' }}
                <em v-if="detail.审批详情.已批准延期次数" class="muted">
                  （含 {{ detail.审批详情.已批准延期次数 }} 次已批准延期）
                </em>
              </dd></div>
            </dl>

            <table v-if="detail.审批详情.延期记录.length" class="sub-table">
              <thead>
                <tr><th>序</th><th>申请日</th><th>原结束日</th><th>申请延至</th><th>材料</th><th>状态</th><th>审批意见</th></tr>
              </thead>
              <tbody>
                <tr v-for="rec in detail.审批详情.延期记录" :key="rec.序号">
                  <td>{{ rec.序号 }}</td>
                  <td>{{ rec.申请日 }}</td>
                  <td>{{ rec.原结束日 }}</td>
                  <td>{{ rec.申请延至日 }}</td>
                  <td>
                    <span :class="rec.材料齐全 ? 'tag-ok' : 'tag-warn'">
                      {{ rec.材料齐全 ? '齐全' : '缺：' + rec.缺失材料.join('、') }}
                    </span>
                  </td>
                  <td>
                    <span :class="rec.状态 === '已批准' ? 'tag-ok' : rec.状态 === '已驳回' ? 'tag-warn' : ''">
                      {{ rec.状态 }}
                    </span>
                    <em v-if="rec.批准结束日" class="muted">（至 {{ rec.批准结束日 }}）</em>
                  </td>
                  <td>{{ rec.审批意见 || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="panel">
            <h4>时间轴</h4>
            <ol class="timeline">
              <li v-for="node in detail.时间轴" :key="node.节点" class="tl-item" :class="`tl-${node.状态}`">
                <span class="tl-dot"></span>
                <div class="tl-content">
                  <p class="tl-title">
                    {{ node.标题 }}
                    <span class="tl-date">{{ node.日期 }}</span>
                    <span v-if="node.异常" class="tag-warn">异常</span>
                  </p>
                  <p class="tl-desc">{{ node.描述 }}</p>
                  <p v-if="node.阻断原因" class="tl-block">⛔ {{ node.阻断原因 }}</p>
                </div>
              </li>
            </ol>
          </section>

          <section class="panel">
            <h4>路面恢复与竣工验收</h4>
            <dl class="kv-grid">
              <div><dt>实际施工结束</dt><dd>{{ detail.恢复信息.实际结束日 || '—' }}</dd></div>
              <div><dt>路面恢复日期</dt><dd>
                <span :class="detail.恢复信息.日期合规 === false ? 'tag-warn' : ''">
                  {{ detail.恢复信息.恢复日期 || '—' }}
                </span>
              </dd></div>
              <div><dt>恢复面积</dt><dd>{{ fmtArea(detail.恢复信息.恢复面积) }}</dd></div>
              <div><dt>恢复方式</dt><dd>{{ detail.恢复信息.恢复方式 || '—' }}</dd></div>
              <div><dt>恢复状态</dt><dd>{{ detail.恢复信息.恢复状态 }}</dd></div>
              <div><dt>竣工验收</dt><dd>
                {{ detail.恢复信息.验收日期 || '—' }}
                <em v-if="detail.恢复信息.验收人" class="muted">（{{ detail.恢复信息.验收人 }}：{{ detail.恢复信息.验收意见 || '合格' }}）</em>
              </dd></div>
            </dl>
            <p v-if="detail.恢复信息.异常提示" class="tl-block">⛔ {{ detail.恢复信息.异常提示 }}</p>
            <div class="drawer-actions">
              <button v-for="action in actionsFor(detail)" :key="action.name"
                      class="btn" :class="{ primary: !action.danger, ghost: action.danger }"
                      type="button" @click="openAction(action.name, detail)">
                {{ action.name }}
              </button>
            </div>
          </section>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/road_occupy'
const columns = ['申请编号', '施工路段', '占道面积', '占道起止日', '作业单位', '交通疏导', '审批单位', '占道状态']
const statuses = ['待审批', '已批准', '施工中', '已撤场', '已恢复', '已验收']
const extensionDocs = ['延期申请书', '施工进度说明', '交通疏导调整方案']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const detail = ref<Row | null>(null)
const stats = ref([
  { label: '待审批占道', value: 0, warn: false },
  { label: '施工中', value: 0, warn: false },
  { label: '面积溢占', value: 0, warn: true },
  { label: '待恢复/待验收', value: 0, warn: false },
])

interface FieldDef {
  name: string
  label: string
  type?: string
  placeholder?: string
}

interface ActionDef {
  name: string
  danger?: boolean
}

const form = reactive<{
  show: boolean
  action: string
  title: string
  target: Row | null
  fields: FieldDef[]
  values: Record<string, any>
  hint: string
}>({
  show: false,
  action: '',
  title: '',
  target: null,
  fields: [],
  values: {},
  hint: '',
})

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function fmtArea(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value} ㎡`
}

/** 按当前状态决定可执行动作，前端只做入口收敛，真正的红线判断在后端。 */
function actionsFor(row: Row): ActionDef[] {
  const pendingExt = Number(row.待延期审批 ?? 0) > 0 ||
    (row.审批详情?.待审批延期次数 ?? 0) > 0
  switch (row.status) {
    case '待审批':
      return [{ name: '审批通过' }]
    case '已批准':
      return [{ name: '开始施工' }, { name: '申请延期' }]
    case '施工中':
      return [
        { name: '确认撤场' },
        { name: '申请延期' },
        ...(pendingExt
          ? [{ name: '延期批准' }, { name: '延期驳回', danger: true } as ActionDef]
          : []),
      ]
    case '已撤场':
      return [{ name: '登记恢复' }]
    case '已恢复':
      return [{ name: '竣工验收' }]
    default:
      return []
  }
}

const CREATE_FIELDS: FieldDef[] = [
  { name: '申请编号', label: '申请编号', placeholder: 'ROAD-2026-009' },
  { name: '施工路段', label: '施工路段' },
  { name: '作业单位', label: '作业单位' },
  { name: '申请占道面积', label: '申请占道面积（㎡）', type: 'number' },
  { name: '申请开始日', label: '申请开始日', type: 'date' },
  { name: '申请结束日', label: '申请结束日', type: 'date' },
  { name: '交通疏导方案', label: '交通疏导方案', type: 'textarea', placeholder: '围挡范围、导改路线、人行通道安排' },
]

function openCreate() {
  openForm('登记占道申请', 'create', null, CREATE_FIELDS, {
    申请占道面积: '',
    申请开始日: '',
    申请结束日: '',
  })
}

function openAction(action: string, row: Row) {
  const presets: Record<string, { title: string; fields: FieldDef[]; values?: Record<string, any>; hint?: string }> = {
    审批通过: {
      title: '审批通过：核定许可范围与批准期限',
      fields: [
        { name: '批准占道面积', label: '批准占道面积（㎡）', type: 'number', placeholder: '不得随意超出申请面积' },
        { name: '批准开始日', label: '批准开始日', type: 'date' },
        { name: '批准结束日', label: '批准结束日', type: 'date' },
        { name: '审批单位', label: '审批单位', placeholder: row.审批单位 || '' },
      ],
    },
    开始施工: {
      title: '开始施工：上报实际占道情况',
      fields: [
        { name: '实际占道面积', label: '实际占道面积（㎡）', type: 'number' },
        { name: '实际开始日', label: '实际开始日', type: 'date' },
      ],
      hint: '实际占道面积超出批准占道面积（面积溢占）时，开工将被直接拦截。',
    },
    申请延期: {
      title: '延期申请：在当前批准期限内提出',
      fields: [
        { name: '申请延至日', label: '申请延至日', type: 'date' },
        { name: '延期原因', label: '延期原因', type: 'textarea' },
      ],
      hint: '三份必备材料须全部勾选；申请日晚于当前批准结束日同样不予批准。',
    },
    延期批准: {
      title: '延期批准：复核材料与期限后放行',
      fields: [
        { name: '批准结束日', label: '批准结束日（可调整）', type: 'date' },
        { name: '审批意见', label: '审批意见', placeholder: '同意延期' },
      ],
      hint: '材料不全或逾期申请时，提交会被后端拦截，批准期限不会顺延。',
    },
    延期驳回: {
      title: '延期驳回',
      fields: [{ name: '审批意见', label: '驳回意见', placeholder: '请说明不批准原因' }],
    },
    确认撤场: {
      title: '确认撤场：上报施工结束',
      fields: [
        { name: '实际结束日', label: '实际结束日', type: 'date' },
        { name: '实际占道面积', label: '复核实测面积（㎡，有变化时填写）', type: 'number' },
      ],
      hint: '面积溢占未处置时撤场会被拦截；实际结束日不得早于开工日。',
    },
    登记恢复: {
      title: '登记路面恢复',
      fields: [
        { name: '恢复日期', label: '路面恢复日期', type: 'date' },
        { name: '恢复面积', label: '恢复面积（㎡）', type: 'number' },
        { name: '恢复方式', label: '恢复方式', placeholder: '如：沥青混凝土罩面' },
      ],
      hint: '恢复日期早于实际施工结束日时不予登记。',
    },
    竣工验收: {
      title: '竣工验收：统一复核许可范围与恢复状态',
      fields: [
        { name: '验收日期', label: '验收日期', type: 'date' },
        { name: '验收人', label: '验收人' },
        { name: '验收意见', label: '验收意见', placeholder: '合格' },
      ],
      hint: '存在面积溢占、恢复日期早于施工结束或恢复面积不足时，验收不得放行结案。',
    },
  }
  const preset = presets[action]
  if (!preset) return
  openForm(preset.title, action, row, preset.fields, { ...(preset.values ?? {}) }, preset.hint ?? '')
}

function openForm(
  title: string,
  action: string,
  target: Row | null,
  fields: FieldDef[],
  values: Record<string, any>,
  hint = '',
) {
  form.show = true
  form.title = title
  form.action = action
  form.target = target
  form.fields = fields
  form.values = reactive({ ...values, 延期材料: [] })
  form.hint = hint
}

function closeForm() {
  form.show = false
  form.target = null
}

async function submitForm() {
  if (!form.target && form.action !== 'create') return
  errorMessage.value = ''
  const payload: Record<string, any> = { ...form.values }
  const action = form.action === 'create' ? undefined : form.action
  if (action) payload.action = action
  // 数字字段转 number
  for (const field of form.fields) {
    if (field.type === 'number' && typeof payload[field.name] === 'string' && payload[field.name] !== '') {
      payload[field.name] = Number(payload[field.name])
    }
  }
  try {
    const url = form.action === 'create' ? ENDPOINT : `${ENDPOINT}/${form.target!.id}/actions`
    const response = await request(url, {
      method: 'POST',
      body: JSON.stringify({ values: payload }),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      errorMessage.value = result.detail || result.message || '操作未生效'
      return
    }
    const openedId = form.target?.id
    closeForm()
    await reload()
    if (openedId && detail.value?.id === openedId) {
      await openDetailById(openedId)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道施工操作失败'
  }
}

async function openDetail(row: Row) {
  await openDetailById(row.id)
}

async function openDetailById(id: number | string) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) throw new Error('占道申请详情读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道申请详情读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('占道申请列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value[0].value = rows.value.filter((r: Row) => r.status === '待审批').length
    stats.value[1].value = rows.value.filter((r: Row) => r.status === '施工中').length
    stats.value[2].value = rows.value.filter((r: Row) => r.面积溢占).length
    stats.value[3].value = rows.value.filter((r: Row) => r.status === '已撤场' || r.status === '已恢复').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '占道施工列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.stat-warn { color: #b42318; }
.tag-warn { color: #b42318; font-weight: 600; }
.tag-ok { color: #067647; font-weight: 600; }
.muted { color: var(--muted); font-style: normal; font-size: 12px; }
.filter-item select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; }
.link-danger { color: #b42318; }

.modal-mask, .drawer-mask {
  position: fixed; inset: 0; background: rgba(16, 24, 40, 0.45);
  z-index: 50; display: flex; justify-content: center; align-items: flex-start;
  padding: 40px 16px; overflow-y: auto;
}
.modal {
  background: #fff; border-radius: 10px; width: min(640px, 100%);
  padding: 18px 20px; box-shadow: 0 12px 32px rgba(16, 24, 40, 0.2);
}
.modal-head, .drawer-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 10px;
}
.modal-head h3, .drawer-head h3 { margin: 0 0 4px; font-size: 16px; }
.modal-target { font-size: 13px; color: var(--muted); margin: 0 0 12px; }
.modal-form { display: flex; flex-direction: column; gap: 10px; }
.modal-field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.modal-field span { color: var(--muted); }
.modal-field input, .modal-field textarea {
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.form-hint { font-size: 12px; color: #b54708; background: #fffaeb; border: 1px solid #fedf89;
  border-radius: 6px; padding: 6px 8px; margin: 0; }
.doc-check { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 12px; }
.doc-title { font-size: 13px; margin: 0 0 6px; }
.doc-item { display: flex; gap: 6px; align-items: center; font-size: 13px; margin-bottom: 4px; }

.drawer {
  background: #fff; border-radius: 10px; width: min(880px, 100%);
  margin: auto 0; box-shadow: 0 12px 32px rgba(16, 24, 40, 0.2);
}
.drawer-head { padding: 16px 20px; border-bottom: 1px solid var(--border); }
.drawer-head p { margin: 0; font-size: 12px; color: var(--muted); }
.drawer-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 16px; }
.panel { border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.panel h4 { margin: 0 0 10px; font-size: 14px; }
.kv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin: 0; font-size: 13px; }
.kv-grid dt { color: var(--muted); font-size: 12px; }
.kv-grid dd { margin: 2px 0 0; }
.sub-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }
.sub-table th, .sub-table td { border: 1px solid var(--border); padding: 5px 7px; text-align: left; }

.timeline { list-style: none; margin: 0; padding: 0 0 0 6px; }
.tl-item { position: relative; padding: 0 0 16px 22px; border-left: 2px solid var(--border); }
.tl-item:last-child { border-left-color: transparent; padding-bottom: 0; }
.tl-dot { position: absolute; left: -7px; top: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: #cbd5e1; border: 2px solid #fff; }
.tl-done .tl-dot { background: #12b76a; }
.tl-current .tl-dot { background: var(--brand); box-shadow: 0 0 0 4px rgba(31, 111, 235, 0.18); }
.tl-blocked .tl-dot { background: #b42318; }
.tl-pending .tl-dot { background: #e2e8f0; }
.tl-title { margin: 0; font-size: 13px; font-weight: 600; display: flex; gap: 8px; align-items: center; }
.tl-date { color: var(--muted); font-weight: 400; font-size: 12px; }
.tl-desc { margin: 3px 0 0; font-size: 12px; color: #475467; }
.tl-block { margin: 4px 0 0; font-size: 12px; color: #b42318; }
.drawer-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
</style>
