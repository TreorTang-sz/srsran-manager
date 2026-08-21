<script setup lang="ts">
import { computed, ref } from 'vue'
import { store } from '../store'
import { getToken, setToken } from '../api'

defineProps<{ tab: string }>()
const emit = defineEmits<{ (e: 'set-tab', t: 'dashboard' | 'events' | 'logs'): void }>()

const snap = computed(() => store().snapshot)
const connected = computed(() => store().connected)
const wd = computed(() => snap.value?.watchdog)

// 启动链（日志事件驱动）: EPC_READY -> ENB_RF_INITIALIZING -> ENB_RUNNING
// -> S1_CONNECTING -> RUNNING；DEGRADED = S1_LOST 等待重连
const wdColor = computed(() => {
  switch (wd.value?.state) {
    case 'RUNNING': return 'var(--green)'
    case 'WARNING':
    case 'DEGRADED': return 'var(--yellow)'
    case 'RECOVERING':
    case 'STARTING':
    case 'EPC_READY':
    case 'ENB_RF_INITIALIZING':
    case 'ENB_RUNNING':
    case 'S1_CONNECTING': return 'var(--blue)'
    case 'FAULT': return 'var(--red)'
    default: return 'var(--muted)'
  }
})

const showToken = ref(false)
const tokenInput = ref(getToken())
function saveToken() {
  setToken(tokenInput.value.trim())
  showToken.value = false
}
</script>

<template>
  <header class="header">
    <div class="brand">
      <span class="logo">▣</span>
      <div>
        <div class="title">srsRAN MANAGER</div>
        <div class="subtitle">基站监控与看门狗系统</div>
      </div>
    </div>

    <nav class="tabs">
      <button :class="{ active: tab === 'dashboard' }" @click="emit('set-tab', 'dashboard')">概览</button>
      <button :class="{ active: tab === 'events' }" @click="emit('set-tab', 'events')">事件</button>
      <button :class="{ active: tab === 'logs' }" @click="emit('set-tab', 'logs')">日志</button>
    </nav>

    <div class="right">
      <div v-if="snap" class="badges">
        <span class="badge" :style="{ color: wdColor, borderColor: wdColor }">
          ● {{ wd?.state }}
        </span>
        <span v-if="wd && wd.consecutive_failures > 0" class="badge" style="color: var(--yellow); border-color: var(--yellow)">
          恢复失败 {{ wd.consecutive_failures }}/{{ wd.max_recovery_attempts }}
        </span>
        <span v-if="wd && wd.state === 'FAULT' && wd.fault_reason" class="badge"
              style="color: var(--red); border-color: var(--red)"
              :title="wd.fault_reason">
          {{ wd.fault_reason.length > 40 ? wd.fault_reason.slice(0, 40) + '…' : wd.fault_reason }}
        </span>
        <span v-if="snap.mode === 'mock'" class="badge" style="color: var(--purple); border-color: var(--purple)">
          MOCK
        </span>
        <span v-if="snap.version" class="badge" style="color: var(--muted); border-color: var(--muted)">
          v{{ snap.version }}
        </span>
        <span class="badge" :style="connected
          ? 'color: var(--green); border-color: var(--green)'
          : 'color: var(--red); border-color: var(--red)'">
          {{ connected ? 'WS 已连接' : 'WS 断开' }}
        </span>
      </div>
      <button class="token-btn" @click="showToken = !showToken" title="API Token">🔑</button>
    </div>

    <div v-if="showToken" class="token-panel panel">
      <label>API Token（用于控制操作）</label>
      <div class="token-row">
        <input v-model="tokenInput" type="password" placeholder="粘贴 API Token" />
        <button class="ok" @click="saveToken">保存</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 10px 20px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
  flex-wrap: wrap;
}
.brand { display: flex; align-items: center; gap: 10px; }
.logo { color: var(--blue); font-size: 22px; }
.title { font-weight: 700; letter-spacing: 0.06em; font-size: 15px; }
.subtitle { font-size: 11px; color: var(--muted); }
.tabs { display: flex; gap: 6px; }
.tabs button.active { background: #2d333b; border-color: var(--blue); color: var(--blue); }
.right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.badges { display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  border: 1px solid; border-radius: 4px; padding: 2px 8px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em;
}
.token-panel {
  position: absolute; right: 20px; top: 54px; width: 320px; z-index: 20;
}
.token-panel label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
.token-row { display: flex; gap: 8px; }
.token-row input { flex: 1; }
</style>
