<script setup lang="ts">
import { ref, computed } from 'vue'
import { store } from './store'
import StatusHeader from './components/StatusHeader.vue'
import ServiceCards from './components/ServiceCards.vue'
import SystemPanel from './components/SystemPanel.vue'
import ThroughputChart from './components/ThroughputChart.vue'
import UeTable from './components/UeTable.vue'
import EventsFeed from './components/EventsFeed.vue'
import ControlPanel from './components/ControlPanel.vue'
import FaultPanel from './components/FaultPanel.vue'
import EventsView from './components/EventsView.vue'
import LogsView from './components/LogsView.vue'

const tab = ref<'dashboard' | 'events' | 'logs'>('dashboard')
const snap = computed(() => store().snapshot)
const isMock = computed(() => snap.value?.mode === 'mock')
</script>

<template>
  <div class="app">
    <StatusHeader :tab="tab" @set-tab="t => (tab = t)" />

    <main v-if="tab === 'dashboard'" class="dashboard">
      <section class="row">
        <ServiceCards />
        <SystemPanel />
      </section>
      <section class="row">
        <ThroughputChart />
      </section>
      <section class="row two-col">
        <div class="col">
          <UeTable />
        </div>
        <div class="col">
          <EventsFeed />
          <ControlPanel />
          <FaultPanel v-if="isMock" />
        </div>
      </section>
    </main>

    <main v-else-if="tab === 'events'">
      <EventsView />
    </main>

    <main v-else>
      <LogsView />
    </main>
  </div>
</template>

<style>
:root {
  --bg: #0d1117;
  --panel: #161b22;
  --panel2: #1c2129;
  --border: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --green: #3fb950;
  --yellow: #d29922;
  --red: #f85149;
  --blue: #58a6ff;
  --purple: #bc8cff;
}
* { box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif;
  font-size: 14px;
}
.mono { font-family: 'Cascadia Code', Consolas, 'Courier New', monospace; }
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 14px 16px;
}
.panel h3 {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
}
.row { display: flex; gap: 14px; margin-bottom: 14px; flex-wrap: wrap; }
.two-col { display: grid; grid-template-columns: 3fr 2fr; gap: 14px; }
.col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
@media (max-width: 1100px) { .two-col { grid-template-columns: 1fr; } }
button {
  background: #21262d;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 13px;
}
button:hover { background: #2d333b; border-color: #484f58; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.danger { color: var(--red); border-color: #6e2a28; }
button.danger:hover { background: #3d1a19; }
button.ok { color: var(--green); border-color: #274937; }
button.ok:hover { background: #122b1d; }
input, select {
  background: #0d1117;
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 5px;
  padding: 5px 8px;
  font-size: 13px;
}
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left; font-size: 11px; text-transform: uppercase;
  color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--border);
  letter-spacing: 0.05em;
}
td { padding: 6px 8px; border-bottom: 1px solid #21262d; font-size: 13px; }
.led { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.led.on { background: var(--green); box-shadow: 0 0 6px var(--green); }
.led.off { background: var(--red); box-shadow: 0 0 6px var(--red); }
.led.warn { background: var(--yellow); box-shadow: 0 0 6px var(--yellow); }
.led.dim { background: #484f58; }
</style>
