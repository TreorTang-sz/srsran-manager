// Types mirroring backend app/models.py (JSON wire format)

export interface ServiceStatus {
  name: string
  state: string
  pid: number | null
  detail: string
}

export interface SystemMetrics {
  ts: number
  cpu_percent: number
  cpu_per_core: number[]
  mem_total_mb: number
  mem_used_mb: number
  mem_percent: number
  swap_total_mb: number
  swap_used_mb: number
  disk_total_gb: number
  disk_used_gb: number
  disk_percent: number
  disk_read_mbps: number
  disk_write_mbps: number
  net_rx_mbps: number
  net_tx_mbps: number
  cpu_temp_c: number | null
  uptime_s: number
}

export interface UsrpStatus {
  ts: number
  connected: boolean
  device: string | null
  serial: string | null
  detail: string
}

export interface S1Status {
  ts: number
  // Log-event driven S1 state machine:
  // S1_DOWN | S1_CONNECTING | S1_READY | S1_LOST | S1_CONFIG_ERROR
  state: string
  connected: boolean
  detail: string
  last_s1_ready_time: number | null
  last_sctp_shutdown_time: number | null
}

export interface UEInfo {
  rnti: number
  cqi: number | null
  mcs_dl: number | null
  mcs_ul: number | null
  dl_bitrate_mbps: number
  ul_bitrate_mbps: number
  last_seen: number
  state: string
}

export interface EnbMetrics {
  ts: number
  ue_count: number
  ues: UEInfo[]
  dl_bitrate_mbps: number
  ul_bitrate_mbps: number
  source: string
}

export interface CoreTraffic {
  ts: number
  rx_mbps: number
  tx_mbps: number
  interfaces: string[]
}

export interface WatchdogStatus {
  state: string
  desired_running: boolean
  consecutive_failures: number
  max_recovery_attempts: number
  total_recoveries: number
  state_since: number
  last_health_level: string
  last_issues: string[]
  last_error: string
  // Why we are in FAULT ("" when not): CONFIG_ERROR / recovery exhausted
  fault_reason: string
}

export interface EventRecord {
  id: number | null
  ts: string
  type: string
  source: string
  severity: string
  message: string
  data: Record<string, unknown>
}

export interface LogRecord {
  id: number | null
  ts: string
  level: string
  module: string
  message: string
}

export interface Snapshot {
  ts: number
  mode: string
  // backend version (backend/app/__init__.py __version__, matches git tag)
  version?: string
  watchdog: WatchdogStatus
  services: { epc: ServiceStatus; enb: ServiceStatus }
  s1: S1Status
  usrp: UsrpStatus
  system: SystemMetrics
  enb_metrics: EnbMetrics
  core_traffic: CoreTraffic
  recent_events: EventRecord[]
  type?: string
}

export interface ThroughputPoint {
  ts: number
  lte_dl: number
  lte_ul: number
  core_dl: number
  core_ul: number
}
