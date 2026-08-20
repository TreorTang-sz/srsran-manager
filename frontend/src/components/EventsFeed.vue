<script setup lang="ts">
import { computed } from 'vue'
import { store } from '../store'
import type { EventRecord } from '../types'

const snap = computed(() => store().snapshot)
const events = computed<readonly EventRecord[]>(() => snap.value?.recent_events ?? [])

function sevClass(sev: string): string {
  switch (sev) {
    case 'ERROR': case 'CRITICAL': return 'err'
    case 'WARNING': return 'warn'
    default: return 'info'
  }
}

function fmtTime(ts: string): string {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+.*$/, '')
}
</script>

<template>
  <div class="panel">
    <h3>最近事件</h3>
    <div class="feed">
      <div v-if="!events.length" class="empty">暂无事件</div>
      <div v-for="(ev, i) in events" :key="ev.id ?? i" class="event" :class="sevClass(ev.severity)">
        <span class="time mono">{{ fmtTime(ev.ts) }}</span>
        <span class="sev">{{ ev.severity }}</span>
        <span class="type mono">{{ ev.type }}</span>
        <span class="msg" :title="ev.message">{{ ev.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.feed { display: flex; flex-direction: column; gap: 2px; max-height: 220px; overflow-y: auto; }
.event {
  display: grid; grid-template-columns: 66px 54px 150px 1fr; gap: 8px;
  font-size: 12px; padding: 3px 6px; border-radius: 3px; align-items: baseline;
}
.event.err { background: rgba(248, 81, 73, 0.08); }
.event.warn { background: rgba(210, 153, 34, 0.08); }
.time { color: var(--muted); font-size: 11px; }
.sev { font-size: 10px; font-weight: 700; }
.event.err .sev { color: var(--red); }
.event.warn .sev { color: var(--yellow); }
.event.info .sev { color: var(--blue); }
.type { color: var(--blue); font-size: 11px; }
.event.err .type { color: #ff8b88; }
.msg { color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.empty { color: var(--muted); text-align: center; padding: 20px 0; font-size: 13px; }
</style>
