<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiGet } from '../api'
import type { EventRecord } from '../types'

const events = ref<EventRecord[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

const PAGE = 50
const severity = ref('')
const typeFilter = ref('')

async function load(reset = true) {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ limit: String(PAGE) })
    if (severity.value) params.set('severity', severity.value)
    if (typeFilter.value) params.set('type', typeFilter.value)
    const resp = await apiGet(`/api/events?${params}`)
    events.value = reset ? resp.events : events.value.concat(resp.events)
    total.value = resp.total ?? 0
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function fmtTime(ts: string): string {
  if (!ts) return ''
  return ts.replace('T', ' ').replace(/\.\d+.*$/, '')
}

function sevClass(sev: string): string {
  switch (sev) {
    case 'ERROR': case 'CRITICAL': return 'err'
    case 'WARNING': return 'warn'
    default: return 'info'
  }
}

onMounted(() => load(true))
</script>

<template>
  <div class="panel">
    <div class="toolbar">
      <h3>事件历史 <span class="total">共 {{ total }} 条</span></h3>
      <div class="filters">
        <select v-model="severity" @change="load(true)">
          <option value="">全部级别</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <input v-model="typeFilter" placeholder="事件类型过滤，如 ENB_CRASH" @keyup.enter="load(true)" />
        <button :disabled="loading" @click="load(true)">{{ loading ? '加载中…' : '刷新' }}</button>
      </div>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="table-wrap">
      <table v-if="events.length">
        <thead>
          <tr><th>时间</th><th>级别</th><th>来源</th><th>类型</th><th>信息</th></tr>
        </thead>
        <tbody>
          <tr v-for="(ev, i) in events" :key="ev.id ?? i" :class="sevClass(ev.severity)">
            <td class="mono time">{{ fmtTime(ev.ts) }}</td>
            <td><span class="sev">{{ ev.severity }}</span></td>
            <td>{{ ev.source }}</td>
            <td class="mono type">{{ ev.type }}</td>
            <td class="msg" :title="ev.message">{{ ev.message }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!loading" class="empty">无匹配事件</div>
    </div>

    <div v-if="events.length < total" class="more">
      <button :disabled="loading" @click="load(false)">加载更多</button>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.toolbar h3 { margin: 0; }
.total { color: var(--muted); font-size: 11px; font-weight: 400; margin-left: 8px; }
.filters { display: flex; gap: 8px; }
.filters input { width: 220px; }
.error { color: var(--red); font-size: 12px; margin-bottom: 8px; }
.table-wrap { overflow-x: auto; max-height: calc(100vh - 220px); overflow-y: auto; }
.time { white-space: nowrap; font-size: 12px; color: var(--muted); }
.sev { font-size: 10px; font-weight: 700; }
tr.err .sev { color: var(--red); }
tr.warn .sev { color: var(--yellow); }
tr.info .sev { color: var(--blue); }
tr.err td { background: rgba(248, 81, 73, 0.04); }
tr.warn td { background: rgba(210, 153, 34, 0.04); }
.type { color: var(--blue); font-size: 12px; white-space: nowrap; }
.msg { max-width: 480px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.empty { color: var(--muted); text-align: center; padding: 40px 0; }
.more { margin-top: 10px; text-align: center; }
</style>
