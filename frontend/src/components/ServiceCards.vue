<script setup lang="ts">
import { computed } from 'vue'
import { store } from '../store'

const snap = computed(() => store().snapshot)

interface Card {
  key: string
  title: string
  level: 'ok' | 'warn' | 'err' | 'dim'
  main: string
  sub: string
}

function serviceLevel(state?: string): Card['level'] {
  switch (state) {
    case 'RUNNING': return 'ok'
    case 'STARTING':
    case 'STOPPING': return 'warn'
    case 'FAILED': return 'err'
    default: return 'dim'
  }
}

// 日志事件驱动的 S1 状态机: DOWN -> CONNECTING -> READY；LOST = 断开后等待重连
function s1View(s1: { state?: string; connected?: boolean } | undefined) {
  switch (s1?.state) {
    case 'S1_READY': return { level: 'ok' as const, main: 'S1 READY' }
    case 'S1_CONNECTING': return { level: 'warn' as const, main: 'S1 CONNECTING' }
    case 'S1_LOST': return { level: 'err' as const, main: 'S1 LOST' }
    case 'S1_CONFIG_ERROR': return { level: 'err' as const, main: 'S1 CONFIG ERROR' }
    case 'S1_DOWN': return { level: 'dim' as const, main: 'S1 DOWN' }
    default:
      // 兼容无 state 字段的旧后端
      return s1?.connected
        ? { level: 'ok' as const, main: 'CONNECTED' }
        : { level: 'dim' as const, main: 'DISCONNECTED' }
  }
}

const cards = computed<Card[]>(() => {
  const s = snap.value
  if (!s) return []
  const epc = s.services?.epc
  const enb = s.services?.enb
  const s1 = s1View(s.s1)
  return [
    {
      key: 'epc',
      title: 'srsEPC 核心网',
      level: serviceLevel(epc?.state),
      main: epc?.state ?? '—',
      sub: epc?.detail || (epc?.pid != null ? `PID ${epc.pid}` : '—'),
    },
    {
      key: 'enb',
      title: 'srsENB 基站',
      level: serviceLevel(enb?.state),
      main: enb?.state ?? '—',
      sub: enb?.detail || (enb?.pid != null ? `PID ${enb.pid}` : '—'),
    },
    {
      key: 's1',
      title: 'S1 连接',
      level: s1.level,
      main: s1.main,
      sub: s.s1.detail || 'eNB ↔ EPC',
    },
    {
      key: 'usrp',
      title: 'USRP B210',
      level: s.usrp.connected ? 'ok' : 'err',
      main: s.usrp.connected ? 'CONNECTED' : 'DISCONNECTED',
      sub: s.usrp.connected ? (s.usrp.device || 'B210') : (s.usrp.detail || '—'),
    },
  ]
})
</script>

<template>
  <div class="panel cards-panel">
    <h3>服务状态</h3>
    <div class="cards">
      <div v-for="c in cards" :key="c.key" class="card" :data-level="c.level">
        <div class="card-title">
          <span class="led" :class="c.level === 'ok' ? 'on' : c.level === 'err' ? 'off' : c.level === 'warn' ? 'warn' : 'dim'"></span>
          {{ c.title }}
        </div>
        <div class="card-main">{{ c.main }}</div>
        <div class="card-sub" :title="c.sub">{{ c.sub }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cards-panel { flex: 1; min-width: 420px; }
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
@media (max-width: 900px) { .cards { grid-template-columns: repeat(2, 1fr); } }
.card {
  background: var(--panel2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  min-width: 0;
}
.card[data-level='ok'] { border-color: #274937; }
.card[data-level='err'] { border-color: #6e2a28; }
.card[data-level='warn'] { border-color: #4d3a13; }
.card-title { font-size: 11px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-main {
  font-size: 15px; font-weight: 700; margin: 6px 0 2px; letter-spacing: 0.03em;
}
.card[data-level='ok'] .card-main { color: var(--green); }
.card[data-level='err'] .card-main { color: var(--red); }
.card[data-level='warn'] .card-main { color: var(--yellow); }
.card[data-level='dim'] .card-main { color: var(--muted); }
.card-sub {
  font-size: 11px; color: var(--muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
</style>
