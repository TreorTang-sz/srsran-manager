<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { store, fmtMbps } from '../store'
import type { ThroughputPoint } from '../types'

const el = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const tp = computed<readonly ThroughputPoint[]>(() => store().throughput)

const latest = computed(() => {
  const last = tp.value[tp.value.length - 1]
  return last ?? null
})

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  return `${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

function buildOption(points: readonly ThroughputPoint[]): echarts.EChartsOption {
  return {
    backgroundColor: 'transparent',
    grid: { left: 46, right: 12, top: 28, bottom: 22 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#161b22',
      borderColor: '#30363d',
      textStyle: { color: '#c9d1d9', fontSize: 12 },
      valueFormatter: (v) => `${Number(v).toFixed(2)} Mbps`,
    },
    legend: {
      top: 0, right: 0,
      textStyle: { color: '#8b949e', fontSize: 11 },
      itemWidth: 14, itemHeight: 8,
    },
    xAxis: {
      type: 'category',
      data: points.map(p => formatTs(p.ts)),
      axisLine: { lineStyle: { color: '#30363d' } },
      axisLabel: { color: '#8b949e', fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Mbps',
      nameTextStyle: { color: '#8b949e', fontSize: 10 },
      axisLine: { show: false },
      axisLabel: { color: '#8b949e', fontSize: 10 },
      splitLine: { lineStyle: { color: '#21262d' } },
    },
    series: [
      { name: 'LTE DL', type: 'line', data: points.map(p => p.lte_dl), showSymbol: false,
        lineStyle: { width: 1.6, color: '#58a6ff' }, itemStyle: { color: '#58a6ff' },
        areaStyle: { color: 'rgba(88,166,255,0.10)' } },
      { name: 'LTE UL', type: 'line', data: points.map(p => p.lte_ul), showSymbol: false,
        lineStyle: { width: 1.6, color: '#3fb950' }, itemStyle: { color: '#3fb950' } },
      { name: 'Core DL', type: 'line', data: points.map(p => p.core_dl), showSymbol: false,
        lineStyle: { width: 1.2, color: '#bc8cff', type: 'dashed' }, itemStyle: { color: '#bc8cff' } },
      { name: 'Core UL', type: 'line', data: points.map(p => p.core_ul), showSymbol: false,
        lineStyle: { width: 1.2, color: '#d29922', type: 'dashed' }, itemStyle: { color: '#d29922' } },
    ],
  }
}

function refresh() {
  if (!chart) return
  chart.setOption(buildOption(tp.value))
}

function onResize() { chart?.resize() }

onMounted(() => {
  if (!el.value) return
  chart = echarts.init(el.value)
  refresh()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(tp, refresh, { deep: false })
</script>

<template>
  <div class="panel chart-panel">
    <h3>实时吞吐量</h3>
    <div class="stats">
      <div class="stat"><span>LTE DL</span><b class="mono dl">{{ fmtMbps(latest?.lte_dl) }}</b><i>Mbps</i></div>
      <div class="stat"><span>LTE UL</span><b class="mono ul">{{ fmtMbps(latest?.lte_ul) }}</b><i>Mbps</i></div>
      <div class="stat"><span>Core DL</span><b class="mono core">{{ fmtMbps(latest?.core_dl) }}</b><i>Mbps</i></div>
      <div class="stat"><span>Core UL</span><b class="mono coreul">{{ fmtMbps(latest?.core_ul) }}</b><i>Mbps</i></div>
      <div class="stat"><span>窗口</span><b>~{{ Math.max(tp.length, 0) }}s</b></div>
    </div>
    <div ref="el" class="chart"></div>
  </div>
</template>

<style scoped>
.chart-panel { width: 100%; }
.stats { display: flex; gap: 26px; flex-wrap: wrap; margin-bottom: 8px; }
.stat { display: flex; align-items: baseline; gap: 6px; }
.stat span { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.stat b { font-size: 17px; }
.stat i { font-size: 10px; color: var(--muted); font-style: normal; }
.dl { color: var(--blue); }
.ul { color: var(--green); }
.core { color: var(--purple); }
.coreul { color: var(--yellow); }
.chart { width: 100%; height: 240px; }
</style>
