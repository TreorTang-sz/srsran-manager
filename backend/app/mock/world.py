"""MockWorld — the simulated srsRAN server used in Windows dev mode.

Holds all simulated state (services, S1, USRP, UEs, system load) and
advances it lazily whenever any provider reads it. Fault injection
mutates this world; the watchdog then observes the injected fault
exactly as it would observe a real fault on Linux.

日志剧本（核心）：
  world 产生与真实 srsRAN 相同格式的日志行（journal 行为的模拟），
  MockLogSource.poll() 取出到期行 -> 与 Linux journalctl 输出走同一条
  LogEventParser / LogStateAggregator 管线（相同接口原则）。

  eNB:  banner -> Reading configuration file -> (RF opened | No UHD
        Devices Found) -> ==== eNodeB started === -> Setting frequency
  EPC:  banner -> 7 条 Initialized
  S1:   eNB+EPC ready 后 EPC 侧发出 Received S1 Setup Request ->
        Sending S1 Setup Response（plmn_error 时发 S1 Setup Failure
        cause: misc - unknown-PLMN）
  注入 s1_fault: SCTP Association Shutdown（S1_LOST 路径）

Fault semantics:
  * enb/epc crash  - one-shot: the process dies; a restart fixes it.
  * s1 disconnect  - SCTP Shutdown 日志; sticky until the eNB restarts.
  * usrp disconnect- eNB 崩溃 (设备丢失), 重启后剧本输出 No UHD Devices
                     Found; sticky until explicitly cleared.
  * plmn error     - EPC 对每次 S1 Setup Request 回 Failure; sticky
                     until cleared (配置错误, 重启无效 -> FAULT).
  * high cpu/temp  - sticky until cleared (resource anomaly).
  * recover-fail N - the next N start/restart attempts end in FAILED.
"""
from __future__ import annotations

import random
import threading
import time
from typing import List, Optional, Tuple

from app.config import AppConfig
from app.models import ServiceName, ServiceState, UEInfo

# 真实日志原文（与 parser 规则一一对应，不虚构格式）
_L_ENB_BANNER = "---  Software Radio Systems LTE eNodeB  ---"
_L_ENB_CONFIG = "Reading configuration file /etc/srsran/enb.conf..."
_L_RF_OPENED = "RF device 'UHD' successfully opened"
_L_NO_UHD = "No UHD Devices Found"
_L_ENB_STARTED = "==== eNodeB started ==="
_L_FREQ = ("Setting frequency: DL=875.0 Mhz, UL=830.0 MHz "
           "for cc_idx=0 nof_prb=25")
_L_ABORTED = "Aborted."
_L_EPC_BANNER = "---  Software Radio Systems EPC  ---"
_L_EPC_INIT = (
    "HSS Initialized.",
    "MME S11 Initialized",
    "MME GTP-C Initialized",
    "MME Initialized.",
    "SPGW GTP-U Initialized.",
    "SPGW S11 Initialized.",
    "SP-GW Initialized.",
)
_L_S1_REQUEST = "Received S1 Setup Request."
_L_S1_REQUEST_DETAIL = ("S1 Setup Request - eNB Name: srsenb01, "
                        "eNB id: 0x19b")
_L_S1_RESPONSE = "Sending S1 Setup Response"
_L_S1_FAILURE = "S1 Setup Failure cause: misc - unknown-PLMN"
_L_SCTP_SHUTDOWN = "SCTP Association Shutdown. Association: 4"


class MockService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.state = ServiceState.STOPPED
        self.pid: int | None = None
        self.ready_at = 0.0
        self.stop_at = 0.0
        self.will_fail = False
        self.running_since = 0.0
        self._pid_seq = random.randint(800, 1600)


class MockUE:
    def __init__(self, rnti: int, rng: random.Random) -> None:
        self.rnti = rnti
        self.cqi = rng.randint(8, 15)
        self.mcs_dl = rng.randint(12, 27)
        self.mcs_ul = rng.randint(8, 20)
        self.dl = rng.uniform(6.0, 14.0)   # Mbps
        self.ul = rng.uniform(0.5, 1.6)    # Mbps
        self.last_seen = time.time()


class MockWorld:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.lock = threading.RLock()
        self.services: dict[str, MockService] = {
            ServiceName.EPC.value: MockService(ServiceName.EPC.value),
            ServiceName.ENB.value: MockService(ServiceName.ENB.value),
        }

        # fault injection state
        self.usrp_fault = False
        self.s1_fault = False
        self.plmn_error = False
        self.high_cpu = False
        self.high_temp = False
        self.recover_fail_pending = 0

        # log script: (due_ts, service, message)
        self._pending_logs: List[Tuple[float, str, str]] = []
        self._s1_announced = False   # EPC 已发出 Request/Response 对

        # UE simulation
        self.ues: dict[int, MockUE] = {}
        self._next_rnti = 0x4601

        self._rng = random.Random()
        self._last_tick = 0.0
        self._process_start = time.time()

    # ------------------------------------------------------------------
    # simulation core
    # ------------------------------------------------------------------
    def tick(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()
        with self.lock:
            if now - self._last_tick < 0.05:
                return
            self._last_tick = now

            for svc in self.services.values():
                if svc.state == ServiceState.STARTING and now >= svc.ready_at:
                    if svc.will_fail:
                        svc.state = ServiceState.FAILED
                        svc.pid = None
                        svc.will_fail = False
                    else:
                        svc.state = ServiceState.RUNNING
                        svc._pid_seq += 1
                        svc.pid = svc._pid_seq
                        svc.running_since = now
                elif svc.state == ServiceState.STOPPING and now >= svc.stop_at:
                    svc.state = ServiceState.STOPPED
                    svc.pid = None

            self._script_s1(now)

            if self.s1_connected(now):
                self._simulate_ues(now)
            elif self.ues:
                self.ues.clear()

    def _simulate_ues(self, now: float) -> None:
        """UE attach/detach + traffic jitter (S1 READY 时才发生)."""
        cfg = self.config.mock
        if len(self.ues) < cfg.max_ues and \
                self._rng.random() < cfg.ue_attach_probability:
            rnti = self._next_rnti
            self._next_rnti += 1
            self.ues[rnti] = MockUE(rnti, self._rng)
        if self.ues and self._rng.random() < cfg.ue_detach_probability:
            rnti = self._rng.choice(list(self.ues))
            del self.ues[rnti]
        for ue in self.ues.values():
            ue.dl = max(0.0, min(ue.dl + self._rng.uniform(-1.5, 1.5), 20.0))
            ue.ul = max(0.0, min(ue.ul + self._rng.uniform(-0.3, 0.3), 5.0))
            ue.last_seen = now

    def _script_s1(self, now: float) -> None:
        """S1 日志剧本：eNB+EPC 就绪后 EPC 侧发出 S1 协商日志。"""
        cfg = self.config.mock
        epc = self.services[ServiceName.EPC.value]
        enb = self.services[ServiceName.ENB.value]
        both_ready = (epc.state == ServiceState.RUNNING
                      and enb.state == ServiceState.RUNNING
                      and now >= enb.running_since + cfg.s1_connect_delay)

        if self.s1_fault:
            if self._s1_announced:
                # 注入 S1 断开: SCTP Association Shutdown (EPC 侧)
                self._pending_logs.append((now, "epc", _L_SCTP_SHUTDOWN))
                self._s1_announced = False
            return

        if both_ready and not self._s1_announced:
            self._s1_announced = True
            self._pending_logs.append((now, "epc", _L_S1_REQUEST))
            self._pending_logs.append((now, "epc", _L_S1_REQUEST_DETAIL))
            if self.plmn_error:
                self._pending_logs.append((now, "epc", _L_S1_FAILURE))
            else:
                self._pending_logs.append((now, "epc", _L_S1_RESPONSE))

    # ------------------------------------------------------------------
    # log script (consumed by MockLogSource)
    # ------------------------------------------------------------------
    def _script_enb_start(self) -> None:
        cfg = self.config.mock
        now = time.time()
        svc = self.services[ServiceName.ENB.value]
        self._pending_logs.append((now, "enb", _L_ENB_BANNER))
        self._pending_logs.append((now, "enb", _L_ENB_CONFIG))
        if svc.will_fail:
            self._pending_logs.append((now + cfg.start_delay, "enb", _L_ABORTED))
            return
        if self.usrp_fault:
            self._pending_logs.append(
                (now + cfg.enb_rf_delay, "enb", _L_NO_UHD))
            return
        self._pending_logs.append(
            (now + cfg.enb_rf_delay, "enb", _L_RF_OPENED))
        t2 = now + cfg.enb_rf_delay + cfg.enb_started_delay
        self._pending_logs.append((t2, "enb", _L_ENB_STARTED))
        self._pending_logs.append((t2, "enb", _L_FREQ))

    def _script_epc_start(self) -> None:
        cfg = self.config.mock
        now = time.time()
        svc = self.services[ServiceName.EPC.value]
        self._pending_logs.append((now, "epc", _L_EPC_BANNER))
        if svc.will_fail:
            self._pending_logs.append((now + cfg.start_delay, "epc", _L_ABORTED))
            return
        for line in _L_EPC_INIT:
            self._pending_logs.append((now + cfg.epc_ready_delay, "epc", line))

    def collect_due_logs(self, now: Optional[float] = None) -> List[Tuple[str, str]]:
        """取出到期日志行 [(service, message)]，并用 wall-clock 时间戳标记。"""
        now = now if now is not None else time.time()
        self.tick(now)
        with self.lock:
            due: List[Tuple[str, str]] = []
            remaining: List[Tuple[float, str, str]] = []
            for item in self._pending_logs:
                if item[0] <= now:
                    due.append((item[1], item[2]))
                else:
                    remaining.append(item)
            self._pending_logs = remaining
            return due

    def _drop_service_logs(self, service: str) -> None:
        self._pending_logs = [l for l in self._pending_logs if l[1] != service]

    # ------------------------------------------------------------------
    # derived state
    # ------------------------------------------------------------------
    def service_state(self, name: ServiceName) -> ServiceState:
        self.tick()
        with self.lock:
            return self.services[name.value].state

    def s1_connected(self, now: float | None = None) -> bool:
        """S1 READY 与否（供 UE 模拟与 probe detail 使用）。"""
        now = now if now is not None else time.time()
        self.tick(now)
        with self.lock:
            if self.s1_fault or self.plmn_error:
                return False
            epc = self.services[ServiceName.EPC.value]
            enb = self.services[ServiceName.ENB.value]
            if epc.state != ServiceState.RUNNING or enb.state != ServiceState.RUNNING:
                return False
            return now >= enb.running_since + self.config.mock.s1_connect_delay

    def usrp_connected(self) -> bool:
        return not self.usrp_fault

    def ue_snapshot(self) -> list[UEInfo]:
        self.tick()
        with self.lock:
            return [
                UEInfo(
                    rnti=ue.rnti,
                    cqi=ue.cqi,
                    mcs_dl=ue.mcs_dl,
                    mcs_ul=ue.mcs_ul,
                    dl_bitrate_mbps=round(ue.dl, 2),
                    ul_bitrate_mbps=round(ue.ul, 2),
                    last_seen=ue.last_seen,
                    state="CONNECTED",
                )
                for ue in self.ues.values()
            ]

    # ------------------------------------------------------------------
    # process manager operations
    # ------------------------------------------------------------------
    def start_service(self, name: ServiceName) -> None:
        with self.lock:
            svc = self.services[name.value]
            now = time.time()
            if svc.state in (ServiceState.RUNNING, ServiceState.STARTING):
                return
            self._drop_service_logs(name.value)
            svc.will_fail = self._consume_recover_fail(name)
            svc.state = ServiceState.STARTING
            svc.ready_at = now + self.config.mock.start_delay
            if name == ServiceName.EPC:
                self._script_epc_start()
            elif name == ServiceName.ENB:
                # restarting the eNB re-establishes the S1 link
                self.s1_fault = False
                self._s1_announced = False
                self._script_enb_start()

    def stop_service(self, name: ServiceName) -> None:
        with self.lock:
            svc = self.services[name.value]
            now = time.time()
            svc.will_fail = False
            self._drop_service_logs(name.value)
            if svc.state == ServiceState.STOPPED:
                return
            svc.state = ServiceState.STOPPING
            svc.stop_at = now + self.config.mock.stop_delay
            # S1 随任一侧停止而消亡（真实: SCTP 关联断开）
            self._s1_announced = False

    def crash_service(self, name: ServiceName) -> None:
        """Unexpected process death (fault injection)."""
        with self.lock:
            svc = self.services[name.value]
            svc.state = ServiceState.STOPPED
            svc.pid = None
            svc.will_fail = False
            self._drop_service_logs(name.value)
            self._s1_announced = False

    def _consume_recover_fail(self, name: ServiceName) -> bool:
        if self.recover_fail_pending > 0:
            self.recover_fail_pending -= 1
            return True
        return False
