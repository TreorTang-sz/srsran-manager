<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiGet, apiPost, ApiError } from '../api'

interface FaultInfo { key: string; label: string; desc: string }

const FAULTS: FaultInfo[] = [
  { key: 'enb-crash', label: 'eNB 崩溃', desc: 'srsENB 进程异常退出' },
  { key: 'epc-crash', label: 'EPC 崩溃', desc: 'srsEPC 进程异常退出' },
  { key: 's1-down', label: 'S1 断开', desc: '模拟 S1 连接中断' },
  { key: 'usrp-down', label: 'B210 断开', desc: '模拟 USRP 设备拔出' },
  { key: 'high-cpu', label: '高 CPU', desc: 'CPU 占用飙升至 95%' },
  { key: 'high-temp', label: '高温', desc: 'CPU 温度升至 88°C' },
  { key: 'recover-fail', label: '恢复失败', desc: '下一次自动恢复将失败' },
]

const active = ref<Record<string, unknown>>({})
const busy = ref('')
const result = ref('')
const resultOk = ref(false)

async function loadActive() {
  try {
    const resp = await apiGet('/api/dev/faults')
    active.value = resp?.active ?? {}
  } catch { /* ignore */ }
}

async function inject(f: FaultInfo) {
  busy.value = f.key
  result.value = ''
  try {
    const resp = await apiPost(`/api/dev/fault/${f.key}`)
    resultOk.value = true
    result.value = typeof resp?.message === 'string' ? resp.message : `已注入 ${f.label}`
  } catch (err) {
    resultOk.value = false
    if (err instanceof ApiError && err.status === 401) {
      result.value = '鉴权失败：请先设置 API Token'
    } else {
      result.value = err instanceof Error ? err.message : String(err)
    }
  } finally {
    busy.value = ''
    loadActive()
  }
}

async function clearAll() {
  busy.value = 'clear'
  try {
    await apiPost('/api/dev/fault/clear')
    resultOk.value = true
    result.value = '已清除全部故障'
  } catch (err) {
    resultOk.value = false
    result.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = ''
    loadActive()
  }
}

function isActive(key: string): boolean {
  return Boolean(active.value[key])
}

onMounted(loadActive)
</script>

<template>
  <div class="panel fault-panel">
    <h3>故障注入 <span class="mock-tag">DEV ONLY</span></h3>
    <div class="faults">
      <button
        v-for="f in FAULTS"
        :key="f.key"
        :class="{ armed: isActive(f.key) }"
        :disabled="busy !== ''"
        :title="f.desc"
        @click="inject(f)"
      >
        {{ busy === f.key ? '注入中…' : f.label }}
        <span v-if="isActive(f.key)" class="armed-dot">●</span>
      </button>
    </div>
    <div class="actions">
      <button class="ok" :disabled="busy !== ''" @click="clearAll">
        {{ busy === 'clear' ? '清除中…' : '清除全部故障' }}
      </button>
    </div>
    <div v-if="result" class="result" :class="resultOk ? 'ok' : 'err'">{{ result }}</div>
  </div>
</template>

<style scoped>
.mock-tag {
  background: rgba(188, 140, 255, 0.15); color: var(--purple);
  border: 1px solid var(--purple); border-radius: 3px;
  padding: 1px 6px; font-size: 9px; margin-left: 6px;
}
.faults { display: flex; gap: 6px; flex-wrap: wrap; }
.faults button.armed { border-color: var(--yellow); color: var(--yellow); }
.armed-dot { margin-left: 4px; }
.actions { margin-top: 8px; }
.result { margin-top: 8px; font-size: 12px; padding: 5px 10px; border-radius: 4px; }
.result.ok { color: var(--green); background: rgba(63, 185, 80, 0.08); }
.result.err { color: var(--red); background: rgba(248, 81, 73, 0.08); }
</style>
