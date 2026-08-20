<script setup lang="ts">
import { computed } from 'vue'
import { store, fmtMbps } from '../store'

const snap = computed(() => store().snapshot)
const ues = computed(() => snap.value?.enb_metrics?.ues ?? [])
const ueCount = computed(() => snap.value?.enb_metrics?.ue_count ?? 0)

function fmtTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function stateClass(state: string): string {
  switch (state) {
    case 'CONNECTED': case 'ACTIVE': return 'ok'
    case 'IDLE': return 'idle'
    default: return 'dim'
  }
}
</script>

<template>
  <div class="panel">
    <h3>在线 UE <span class="count">{{ ueCount }}</span></h3>
    <div class="table-wrap">
      <table v-if="ues.length">
        <thead>
          <tr><th>RNTI</th><th>CQI</th><th>MCS DL</th><th>MCS UL</th><th>DL</th><th>UL</th><th>状态</th><th>最后更新</th></tr>
        </thead>
        <tbody>
          <tr v-for="ue in ues" :key="ue.rnti" class="mono">
            <td>{{ ue.rnti.toString(16).toUpperCase() }}</td>
            <td>{{ ue.cqi ?? '—' }}</td>
            <td>{{ ue.mcs_dl ?? '—' }}</td>
            <td>{{ ue.mcs_ul ?? '—' }}</td>
            <td>{{ fmtMbps(ue.dl_bitrate_mbps) }}</td>
            <td>{{ fmtMbps(ue.ul_bitrate_mbps) }}</td>
            <td><span class="state" :class="stateClass(ue.state)">{{ ue.state }}</span></td>
            <td class="dim">{{ fmtTime(ue.last_seen) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">当前无在线 UE</div>
    </div>
  </div>
</template>

<style scoped>
.count {
  background: #21262d; border: 1px solid var(--border); border-radius: 10px;
  color: var(--blue); padding: 1px 9px; margin-left: 8px; font-size: 12px;
}
.table-wrap { overflow-x: auto; max-height: 260px; overflow-y: auto; }
td { white-space: nowrap; }
.dim { color: var(--muted); }
.state { font-size: 11px; padding: 1px 7px; border-radius: 3px; border: 1px solid var(--border); }
.state.ok { color: var(--green); border-color: #274937; }
.state.idle { color: var(--yellow); border-color: #4d3a13; }
.state.dim { color: var(--muted); }
.empty { color: var(--muted); text-align: center; padding: 26px 0; font-size: 13px; }
</style>
