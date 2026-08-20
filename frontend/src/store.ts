// Reactive store: WebSocket live data + throughput history + reconnect
import { reactive, readonly } from 'vue'
import type { Snapshot, ThroughputPoint } from './types'

const MAX_POINTS = 120 // ~2 minutes at 1 Hz

interface StoreState {
  snapshot: Snapshot | null
  connected: boolean
  lastError: string
  throughput: ThroughputPoint[]
  wsRetryMs: number
}

const state = reactive<StoreState>({
  snapshot: null,
  connected: false,
  lastError: '',
  throughput: [],
  wsRetryMs: 1000,
})

let ws: WebSocket | null = null
let backfillDone = false

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws`
}

function pushPoint(snap: Snapshot) {
  const point: ThroughputPoint = {
    ts: snap.ts,
    lte_dl: snap.enb_metrics.dl_bitrate_mbps,
    lte_ul: snap.enb_metrics.ul_bitrate_mbps,
    core_dl: snap.core_traffic.rx_mbps,
    core_ul: snap.core_traffic.tx_mbps,
  }
  state.throughput.push(point)
  if (state.throughput.length > MAX_POINTS) {
    state.throughput.splice(0, state.throughput.length - MAX_POINTS)
  }
}

async function backfillHistory() {
  try {
    const resp = await fetch('/api/throughput?window=120')
    if (!resp.ok) return
    const data = await resp.json()
    if (Array.isArray(data.points) && data.points.length > 0 && state.throughput.length === 0) {
      state.throughput = data.points.slice(-MAX_POINTS)
    }
  } catch { /* backend not ready yet */ }
}

function connect() {
  try {
    ws = new WebSocket(wsUrl())
  } catch (err) {
    state.lastError = String(err)
    scheduleReconnect()
    return
  }
  ws.onopen = () => {
    state.connected = true
    state.lastError = ''
    state.wsRetryMs = 1000
    if (!backfillDone) {
      backfillDone = true
      backfillHistory()
    }
  }
  ws.onmessage = (ev) => {
    try {
      const snap: Snapshot = JSON.parse(ev.data)
      state.snapshot = snap
      pushPoint(snap)
    } catch { /* malformed frame */ }
  }
  ws.onclose = () => {
    state.connected = false
    scheduleReconnect()
  }
  ws.onerror = () => {
    state.lastError = 'WebSocket error'
  }
}

function scheduleReconnect() {
  setTimeout(() => {
    connect()
  }, state.wsRetryMs)
  state.wsRetryMs = Math.min(state.wsRetryMs * 2, 10000)
}

export function startStore() {
  connect()
}

export function store() {
  return readonly(state)
}

// helpers shared by components
export function fmtMbps(v: number | null | undefined): string {
  if (v == null) return '—'
  return v >= 100 ? v.toFixed(1) : v.toFixed(2)
}

export function fmtUptime(seconds: number): string {
  if (!seconds || seconds <= 0) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m ${Math.floor(seconds % 60)}s`
}
