<script setup lang="ts">
import { ref } from 'vue'
import { apiPost, getToken, ApiError } from '../api'

interface Action { label: string; target: 'epc' | 'enb' | 'network'; op: 'start' | 'stop' | 'restart'; danger: boolean }

const ACTIONS: Action[] = [
  { label: '启动', target: 'epc', op: 'start', danger: false },
  { label: '停止', target: 'epc', op: 'stop', danger: true },
  { label: '重启', target: 'epc', op: 'restart', danger: true },
  { label: '启动', target: 'enb', op: 'start', danger: false },
  { label: '停止', target: 'enb', op: 'stop', danger: true },
  { label: '重启', target: 'enb', op: 'restart', danger: true },
  { label: '启动网络', target: 'network', op: 'start', danger: false },
  { label: '停止网络', target: 'network', op: 'stop', danger: true },
  { label: '重启网络', target: 'network', op: 'restart', danger: true },
]

const TARGET_LABELS: Record<Action['target'], string> = {
  epc: 'srsEPC',
  enb: 'srsENB',
  network: 'LTE 网络',
}

const busy = ref('')
const result = ref('')
const resultOk = ref(false)
const confirmAction = ref<Action | null>(null)

function needConfirm(a: Action): boolean {
  return a.danger
}

async function exec(a: Action) {
  confirmAction.value = null
  busy.value = `${a.target}:${a.op}`
  result.value = ''
  try {
    const resp = await apiPost(`/api/${a.target}/${a.op}`)
    resultOk.value = true
    result.value = typeof resp?.message === 'string' ? resp.message : JSON.stringify(resp)
  } catch (err) {
    resultOk.value = false
    if (err instanceof ApiError && err.status === 401) {
      result.value = '鉴权失败：请先在右上角 🔑 设置 API Token'
    } else {
      result.value = err instanceof Error ? err.message : String(err)
    }
  } finally {
    busy.value = ''
  }
}

function onClick(a: Action) {
  if (needConfirm(a)) {
    confirmAction.value = a
  } else {
    exec(a)
  }
}
</script>

<template>
  <div class="panel">
    <h3>系统控制</h3>
    <div class="groups">
      <div v-for="target in ['epc', 'enb', 'network'] as const" :key="target" class="group">
        <div class="group-title">{{ TARGET_LABELS[target] }}</div>
        <div class="btns">
          <button
            v-for="a in ACTIONS.filter(x => x.target === target)"
            :key="`${a.target}:${a.op}`"
            :class="{ danger: a.danger }"
            :disabled="busy !== ''"
            @click="onClick(a)"
          >
            {{ busy === `${a.target}:${a.op}` ? '执行中…' : a.label }}
          </button>
        </div>
      </div>
    </div>
    <div v-if="result" class="result" :class="resultOk ? 'ok' : 'err'">{{ result }}</div>
    <div v-if="!getToken()" class="hint">未设置 API Token，控制操作将被拒绝</div>

    <div v-if="confirmAction" class="confirm-overlay" @click.self="confirmAction = null">
      <div class="confirm panel">
        <div class="confirm-title">操作确认</div>
        <p>确定要{{ confirmAction.label }} {{ TARGET_LABELS[confirmAction.target] }} 吗？</p>
        <div class="confirm-btns">
          <button class="danger" @click="exec(confirmAction)">确认执行</button>
          <button @click="confirmAction = null">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.groups { display: flex; gap: 18px; flex-wrap: wrap; }
.group { flex: 1; min-width: 140px; }
.group-title { font-size: 11px; color: var(--muted); margin-bottom: 6px; letter-spacing: 0.05em; }
.btns { display: flex; gap: 6px; flex-wrap: wrap; }
.result { margin-top: 10px; font-size: 12px; padding: 6px 10px; border-radius: 4px; }
.result.ok { color: var(--green); background: rgba(63, 185, 80, 0.08); }
.result.err { color: var(--red); background: rgba(248, 81, 73, 0.08); }
.hint { margin-top: 10px; font-size: 11px; color: var(--yellow); }
.confirm-overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.55);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.confirm { width: 340px; padding: 20px; }
.confirm-title { font-size: 14px; font-weight: 700; margin-bottom: 10px; }
.confirm p { margin: 0 0 16px; font-size: 13px; }
.confirm-btns { display: flex; gap: 10px; justify-content: flex-end; }
</style>
