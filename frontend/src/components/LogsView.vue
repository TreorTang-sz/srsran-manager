<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { apiGet } from '../api'
import type { LogRecord } from '../types'

const logs = ref<LogRecord[]>([])
const loading = ref(false)
const error = ref('')
const level = ref('')
const autoRefresh = ref(true)
const PAGE = 200

let timer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ limit: String(PAGE) })
    if (level.value) params.set('level', level.value)
    const resp = await apiGet(`/api/logs?${params}`)
    logs.value = resp.logs ?? []
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

function levelClass(lv: string): string {
  switch (lv) {
    case 'ERROR': case 'CRITICAL': return 'err'
    case 'WARNING': return 'warn'
    case 'DEBUG': return 'dim'
    default: return 'info'
  }
}

function startTimer() {
  stopTimer()
  if (autoRefresh.value) timer = setInterval(load, 5000)
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

function toggleAuto() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) startTimer(); else stopTimer()
}

onMounted(() => { load(); startTimer() })
onBeforeUnmount(stopTimer)
</script>

<template>
  <div class="panel">
    <div class="toolbar">
      <h3>系统日志 <span class="total">{{ logs.length }} 条（最近 5s 自动刷新）</span></h3>
      <div class="filters">
        <select v-model="level" @change="load">
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <button :class="{ ok: autoRefresh }" @click="toggleAuto">
          {{ autoRefresh ? '自动刷新中' : '已暂停' }}
        </button>
        <button :disabled="loading" @click="load">{{ loading ? '加载中…' : '刷新' }}</button>
      </div>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <div class="table-wrap">
      <table v-if="logs.length">
        <thead>
          <tr><th>时间</th><th>级别</th><th>模块</th><th>信息</th></tr>
        </thead>
        <tbody>
          <tr v-for="(lg, i) in logs" :key="lg.id ?? i" :class="levelClass(lg.level)">
            <td class="mono time">{{ fmtTime(lg.ts) }}</td>
            <td><span class="lv">{{ lg.level }}</span></td>
            <td>{{ lg.module }}</td>
            <td class="msg">{{ lg.message }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!loading" class="empty">无匹配日志</div>
    </div>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.toolbar h3 { margin: 0; }
.total { color: var(--muted); font-size: 11px; font-weight: 400; margin-left: 8px; }
.filters { display: flex; gap: 8px; }
.error { color: var(--red); font-size: 12px; margin-bottom: 8px; }
.table-wrap { overflow-x: auto; max-height: calc(100vh - 220px); overflow-y: auto; }
.time { white-space: nowrap; font-size: 12px; color: var(--muted); }
.lv { font-size: 10px; font-weight: 700; }
tr.err .lv { color: var(--red); }
tr.warn .lv { color: var(--yellow); }
tr.info .lv { color: var(--blue); }
tr.dim .lv { color: var(--muted); }
tr.dim td { color: var(--muted); }
.msg { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 720px; }
.empty { color: var(--muted); text-align: center; padding: 40px 0; }
</style>
