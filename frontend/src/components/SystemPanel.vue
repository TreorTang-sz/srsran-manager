<script setup lang="ts">
import { computed } from 'vue'
import { store, fmtUptime } from '../store'

const snap = computed(() => store().snapshot)
const sys = computed(() => snap.value?.system)

const cpuColor = (v: number) => (v >= 90 ? 'var(--red)' : v >= 75 ? 'var(--yellow)' : 'var(--green)')
const tempColor = (v: number | null) =>
  v == null ? 'var(--muted)' : v >= 80 ? 'var(--red)' : v >= 70 ? 'var(--yellow)' : 'var(--green)'

const coreLoad = computed(() => {
  const cores = sys.value?.cpu_per_core ?? []
  const max = Math.max(100, ...cores)
  return cores.map((v, i) => ({ i, v, pct: Math.min(100, (v / max) * 100) }))
})
</script>

<template>
  <div class="panel sys-panel">
    <h3>系统资源</h3>
    <template v-if="sys">
      <div class="metrics">
        <div class="metric">
          <div class="metric-head"><span>CPU</span><b :style="{ color: cpuColor(sys.cpu_percent) }">{{ sys.cpu_percent.toFixed(1) }}%</b></div>
          <div class="bar"><div class="fill" :style="{ width: Math.min(100, sys.cpu_percent) + '%', background: cpuColor(sys.cpu_percent) }"></div></div>
        </div>
        <div class="metric">
          <div class="metric-head"><span>内存</span><b :style="{ color: cpuColor(sys.mem_percent) }">{{ sys.mem_percent.toFixed(1) }}%</b></div>
          <div class="bar"><div class="fill" :style="{ width: Math.min(100, sys.mem_percent) + '%', background: cpuColor(sys.mem_percent) }"></div></div>
          <div class="metric-sub">{{ sys.mem_used_mb.toFixed(0) }} / {{ sys.mem_total_mb.toFixed(0) }} MB</div>
        </div>
        <div class="metric">
          <div class="metric-head"><span>磁盘</span><b :style="{ color: cpuColor(sys.disk_percent) }">{{ sys.disk_percent.toFixed(1) }}%</b></div>
          <div class="bar"><div class="fill" :style="{ width: Math.min(100, sys.disk_percent) + '%', background: cpuColor(sys.disk_percent) }"></div></div>
          <div class="metric-sub">{{ sys.disk_used_gb.toFixed(1) }} / {{ sys.disk_total_gb.toFixed(1) }} GB</div>
        </div>
        <div class="metric">
          <div class="metric-head"><span>CPU 温度</span><b :style="{ color: tempColor(sys.cpu_temp_c) }">
            {{ sys.cpu_temp_c != null ? sys.cpu_temp_c.toFixed(1) + ' °C' : 'N/A' }}
          </b></div>
        </div>
      </div>

      <div v-if="coreLoad.length" class="cores">
        <div v-for="c in coreLoad" :key="c.i" class="core" :title="`Core ${c.i}: ${c.v.toFixed(0)}%`">
          <div class="core-fill" :style="{ height: c.pct + '%', background: cpuColor(c.v) }"></div>
        </div>
      </div>

      <div class="kv-grid">
        <div class="kv"><span class="k">Swap</span><span class="v mono">{{ sys.swap_used_mb.toFixed(0) }} / {{ sys.swap_total_mb.toFixed(0) }} MB</span></div>
        <div class="kv"><span class="k">磁盘 IO</span><span class="v mono">R {{ sys.disk_read_mbps.toFixed(1) }} · W {{ sys.disk_write_mbps.toFixed(1) }} MB/s</span></div>
        <div class="kv"><span class="k">网络</span><span class="v mono">RX {{ sys.net_rx_mbps.toFixed(2) }} · TX {{ sys.net_tx_mbps.toFixed(2) }} Mbps</span></div>
        <div class="kv"><span class="k">运行时间</span><span class="v mono">{{ fmtUptime(sys.uptime_s) }}</span></div>
      </div>
    </template>
    <div v-else class="empty">等待数据…</div>
  </div>
</template>

<style scoped>
.sys-panel { flex: 1; min-width: 420px; }
.metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 18px; }
.metric-head { display: flex; justify-content: space-between; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.metric-head b { font-size: 13px; }
.bar { height: 6px; background: #21262d; border-radius: 3px; overflow: hidden; }
.fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.metric-sub { font-size: 10px; color: var(--muted); margin-top: 3px; }
.cores { display: flex; gap: 3px; align-items: flex-end; height: 34px; margin: 12px 0 4px; }
.core { flex: 1; background: #21262d; border-radius: 2px; height: 100%; display: flex; align-items: flex-end; overflow: hidden; }
.core-fill { width: 100%; border-radius: 2px; transition: height 0.5s; }
.kv-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; margin-top: 10px; }
.kv { display: flex; justify-content: space-between; font-size: 12px; }
.k { color: var(--muted); }
.v { color: var(--text); }
.empty { color: var(--muted); font-size: 13px; padding: 20px 0; text-align: center; }
</style>
