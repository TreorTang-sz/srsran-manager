"""Application configuration.

Loading order (later overrides earlier):
  1. dataclass defaults
  2. YAML config file (config/config.yaml by default, override with
     SRSRAN_CONFIG env var)
  3. environment variables:
       SRSRAN_MODE          - auto | mock | linux
       SRSRAN_API_TOKEN     - API token for control endpoints
       SRSRAN_DB_PATH       - sqlite database path
       SRSRAN_HOST/PORT     - web bind address
       SRSRAN_WATCHDOG_ONLY - "1" -> run watchdog engine without web
       SRSRAN_MANAGER_ONLY  - "1" -> run web without in-process watchdog
                              (for split systemd deployment)

Secrets are NEVER hardcoded; token comes from config file / env only.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_CONFIG_PATHS = [
    "config/config.yaml",
    "../config/config.yaml",
    "/etc/srsran-manager/config.yaml",
]


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    run_web: bool = True


@dataclass
class MockConfig:
    start_delay: float = 1.5          # simulated service start time (s)
    stop_delay: float = 0.3
    s1_connect_delay: float = 1.0     # S1 comes up after both services run
    ue_attach_probability: float = 0.10
    ue_detach_probability: float = 0.03
    max_ues: int = 5
    # --- 日志剧本时序（模拟真实 srsRAN 日志节奏） ---
    epc_ready_delay: float = 0.5      # EPC banner -> 7 条 Initialized 日志
    enb_rf_delay: float = 1.0         # eNB config -> "RF device 'UHD' successfully opened"
    enb_started_delay: float = 0.5    # RF opened -> "==== eNodeB started ==="


@dataclass
class WatchdogConfig:
    run_watchdog: bool = True
    run_monitor: bool = True
    auto_start: bool = True             # 无人值守: 开机后自动拉起 LTE 网络
    check_interval: float = 1.0
    monitor_interval: float = 1.0
    recovery_cooldown: float = 5.0
    max_recovery_attempts: int = 3    # 禁止无限重启
    verify_delay: float = 4.0
    # 分阶段启动超时（见 StageTimeoutsConfig，覆盖旧的统一 start_timeout）
    stages: "StageTimeoutsConfig" = field(default_factory=lambda: StageTimeoutsConfig())


@dataclass
class StageTimeoutsConfig:
    """分阶段启动超时 —— 每个阶段等待对应的真实日志证据。

    epc_ready_timeout      等 EPC 的 7 条 Initialized 日志
    enb_rf_timeout         等 "RF device 'UHD' successfully opened"
                           （UHD/B210 初始化，RK3588 上可能较慢）
    enb_running_timeout    等 "==== eNodeB started ==="
    s1_ready_timeout       等 "Sending S1 Setup Response"
    s1_reconnect_grace     S1_LOST 后先等 eNB 自动重连（SCTP Shutdown
                           不等于启动失败，不应立即重启）
    """
    epc_ready_timeout: float = 45.0
    enb_rf_timeout: float = 180.0    # RK3588 + B210 大 PRB 初始化实测较慢
    enb_running_timeout: float = 60.0
    s1_ready_timeout: float = 30.0
    s1_reconnect_grace: float = 10.0


@dataclass
class ThresholdsConfig:
    cpu_warning: float = 85.0
    memory_warning: float = 85.0
    disk_warning: float = 90.0
    temperature_warning: float = 75.0


@dataclass
class DatabaseConfig:
    path: str = "data/srsran_manager.db"
    event_retention_days: int = 30


@dataclass
class SecurityConfig:
    # Token for control endpoints. Empty -> control endpoints disabled.
    api_token: Optional[str] = None
    # Fault-injection dev API (enabled automatically in mock mode)
    dev_fault_api: bool = True


@dataclass
class LinuxServicesConfig:
    epc: str = "srsran-epc"
    enb: str = "srsran-enb"


@dataclass
class LinuxUsrpConfig:
    # cache TTL for uhd_find_devices (the call is expensive)
    check_interval: float = 10.0
    find_cmd: str = "uhd_find_devices"


@dataclass
class LinuxMetricsConfig:
    # file: tail the enb metrics CSV; journal: journalctl -u <unit>
    source: str = "file"
    enb_metrics_file: str = "/var/log/srsran/enb_metrics.csv"
    journal_unit: str = "srsran-enb"
    # bitrate unit scale of the source metrics (bps -> Mbps conversion uses
    # this; adjust at deployment if the srsRAN version reports bytes/s)
    bitrate_scale: float = 1.0


@dataclass
class LinuxS1Config:
    # sctp: check kernel SCTP association to EPC (recommended);
    # log:   grep srsENB journal for S1AP state messages (fallback)
    method: str = "sctp"
    sctp_port: int = 36412
    journal_unit: str = "srsran-enb"


@dataclass
class LinuxCoreTrafficConfig:
    # interfaces carrying core network user traffic (srsEPC SGi / S1-U)
    interfaces: List[str] = field(default_factory=lambda: ["srs_spgw_sgi"])


@dataclass
class LinuxLogsConfig:
    """journalctl 日志源（看门狗核心判定依据）。"""
    enb_unit: str = "srsran-enb"
    epc_unit: str = "srsran-epc"
    # 首次拉取的历史窗口：看门狗重启后从既有日志恢复组件状态
    boot_history_s: float = 300.0


@dataclass
class LinuxConfig:
    services: LinuxServicesConfig = field(default_factory=LinuxServicesConfig)
    usrp: LinuxUsrpConfig = field(default_factory=LinuxUsrpConfig)
    metrics: LinuxMetricsConfig = field(default_factory=LinuxMetricsConfig)
    s1: LinuxS1Config = field(default_factory=LinuxS1Config)
    core_traffic: LinuxCoreTrafficConfig = field(default_factory=LinuxCoreTrafficConfig)
    logs: LinuxLogsConfig = field(default_factory=LinuxLogsConfig)


@dataclass
class AppConfig:
    mode: str = "auto"                 # auto | mock | linux
    log_level: str = "INFO"
    server: ServerConfig = field(default_factory=ServerConfig)
    mock: MockConfig = field(default_factory=MockConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    linux: LinuxConfig = field(default_factory=LinuxConfig)

    @property
    def resolved_mode(self) -> str:
        """Resolve 'auto': Linux -> linux providers, everything else -> mock.

        This is the ONLY place in the codebase where the platform is
        inspected. Business logic depends solely on provider interfaces
        (Adapter/Provider architecture, see docs/architecture.md).
        """
        if self.mode in ("mock", "linux"):
            return self.mode
        return "linux" if sys.platform == "linux" else "mock"


def _merge_dataclass(instance: Any, data: Dict[str, Any]) -> None:
    for f in fields(instance):
        if f.name in data and data[f.name] is not None:
            current = getattr(instance, f.name)
            value = data[f.name]
            if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                _merge_dataclass(current, value)
            else:
                setattr(instance, f.name, value)


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg = AppConfig()

    cfg_path: Optional[Path] = None
    if path:
        cfg_path = Path(path)
    elif os.environ.get("SRSRAN_CONFIG"):
        cfg_path = Path(os.environ["SRSRAN_CONFIG"])
    else:
        for p in DEFAULT_CONFIG_PATHS:
            if Path(p).exists():
                cfg_path = Path(p)
                break

    if cfg_path and cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        _merge_dataclass(cfg, data)

    # ---- environment overrides -------------------------------------------
    env = os.environ
    if env.get("SRSRAN_MODE"):
        cfg.mode = env["SRSRAN_MODE"]
    if env.get("SRSRAN_API_TOKEN"):
        cfg.security.api_token = env["SRSRAN_API_TOKEN"]
    if env.get("SRSRAN_DB_PATH"):
        cfg.database.path = env["SRSRAN_DB_PATH"]
    if env.get("SRSRAN_HOST"):
        cfg.server.host = env["SRSRAN_HOST"]
    if env.get("SRSRAN_PORT"):
        cfg.server.port = int(env["SRSRAN_PORT"])
    if env.get("SRSRAN_WATCHDOG_ONLY") == "1":
        cfg.server.run_web = False
        cfg.watchdog.run_watchdog = True
        cfg.watchdog.run_monitor = True
    if env.get("SRSRAN_MANAGER_ONLY") == "1":
        cfg.watchdog.run_watchdog = False
        cfg.watchdog.run_monitor = True

    if not cfg.security.api_token:
        cfg.security.api_token = None
    return cfg
