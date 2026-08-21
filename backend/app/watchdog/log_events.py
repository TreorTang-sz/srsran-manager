"""srsRAN 日志事件解析器 —— 基于真实日志样本的规则层。

每一条匹配串都来自 RK3588 / Ubuntu / srsRAN 4G 实机的 journalctl 输出，
不虚构任何日志格式。新增异常类型时，先用真实样本扩展本表。

解析器是纯函数：一行日志 -> 0..1 个 LogEvent。平台无关，
Linux(journalctl) 与 Mock(剧本) 走同一条解析路径（同一接口原则）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LogEventName(str, Enum):
    # ---- srsENB lifecycle (eNB unit logs) ----
    ENB_BANNER = "ENB_BANNER"                # ---  Software Radio Systems LTE eNodeB  ---
    ENB_CONFIG_LOADING = "ENB_CONFIG_LOADING"  # Reading configuration file ...
    ENB_RF_OPENED = "ENB_RF_OPENED"          # RF device 'UHD' successfully opened
    ENB_STARTED = "ENB_STARTED"              # ==== eNodeB started ===
    ENB_FREQ_SET = "ENB_FREQ_SET"            # Setting frequency: DL=... Mhz, UL=... MHz ...

    # ---- srsEPC lifecycle (EPC unit logs) ----
    EPC_BANNER = "EPC_BANNER"                # ---  Software Radio Systems EPC  ---
    EPC_INIT_LINE = "EPC_INIT_LINE"          # HSS Initialized. / MME ... Initialized ...
    EPC_S1_REQUEST = "EPC_S1_REQUEST"        # Received S1 Setup Request.
    EPC_S1_RESPONSE = "EPC_S1_RESPONSE"      # Sending S1 Setup Response
    EPC_S1_FAILURE = "EPC_S1_FAILURE"        # S1 Setup Failure ...
    EPC_SCTP_SHUTDOWN = "EPC_SCTP_SHUTDOWN"  # SCTP Association Shutdown

    # ---- UHD / RF anomalies ----
    UHD_NO_DEVICE = "UHD_NO_DEVICE"          # No UHD Devices Found
    UHD_FW_MISSING = "UHD_FW_MISSING"        # Could not find usrp_b200_fw.hex
    RF_TX_ERROR = "RF_TX_ERROR"              # Tx while waiting for EOB, timed out
    RF_UNDERFLOW = "RF_UNDERFLOW"            # underflow / U (连续欠载字符)
    RF_INIT_ERROR = "RF_INIT_ERROR"          # uhd_init failed / Error initializing radio
    # ^ 可恢复的 RF 硬件初始化失败（B210 USB 句柄未释放/USB 抖动等），
    #   重启 eNB 通常可恢复 —— 与 CONFIG_ERROR 严格区分

    # ---- configuration errors (restart is pointless) ----
    CONFIG_FILE_ERROR = "CONFIG_FILE_ERROR"  # Couldn't open ...
    CONFIG_OPTION_ERROR = "CONFIG_OPTION_ERROR"  # Unrecognised options:


@dataclass
class LogEvent:
    name: LogEventName
    service: str            # "enb" | "epc"
    ts: float               # epoch seconds (from journal timestamp)
    raw: str                # original log line (truncated)
    detail: str = ""        # captured groups / extra info
    fields: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 真实日志匹配规则（顺序即优先级；一行业务上只属于一个事件）
# ---------------------------------------------------------------------------
_RE_FREQ = re.compile(
    r"Setting frequency:\s*DL=([\d.]+)\s*Mhz,\s*UL=([\d.]+)\s*MHz.*nof_prb=(\d+)")
_RE_S1_FAILURE_CAUSE = re.compile(r"S1 Setup Failure.*cause:\s*(\S+[^,\n]*)")
_RE_COULDNT_OPEN = re.compile(r"Couldn't open\s+(\S+)")
_RE_UNRECOGNISED = re.compile(r"Unrecognised options?\s*:\s*(.*)")

# EPC 初始化完成的真实日志行（前缀匹配；READY 需要全部出现）
EPC_INIT_LINES: tuple[str, ...] = (
    "HSS Initialized",
    "MME S11 Initialized",
    "MME GTP-C Initialized",
    "MME Initialized.",
    "SPGW GTP-U Initialized",
    "SPGW S11 Initialized",
    "SP-GW Initialized",
)

# (compiled pattern, event name, service) — 依次匹配
_RULES: list[tuple[re.Pattern, LogEventName, str]] = [
    # 配置类错误优先级最高（重启无意义）。
    # 正则用 [^\s,]+ 排除配置回退行: "Couldn't open , trying /root/.config/..."
    # 是 srsRAN 正常的查找顺序输出（空命令行路径 -> 回退 ~/.config），不是错误；
    # 只有跟了真实路径（无逗号紧跟）才是打不开配置文件。
    (re.compile(r"Couldn't open\s+[^\s,]+\s"), LogEventName.CONFIG_FILE_ERROR, "enb"),
    (re.compile(r"Unrecognised options?\s*:"), LogEventName.CONFIG_OPTION_ERROR, "enb"),
    # eNB lifecycle
    (re.compile(r"Software Radio Systems LTE eNodeB"), LogEventName.ENB_BANNER, "enb"),
    (re.compile(r"Reading configuration file\s+(\S+)"), LogEventName.ENB_CONFIG_LOADING, "enb"),
    (re.compile(r"RF device 'UHD' successfully opened"), LogEventName.ENB_RF_OPENED, "enb"),
    (re.compile(r"={2,}\s*eNodeB started\s*={2,}"), LogEventName.ENB_STARTED, "enb"),
    (re.compile(r"Setting frequency:\s*DL="), LogEventName.ENB_FREQ_SET, "enb"),
    # EPC lifecycle
    (re.compile(r"Software Radio Systems EPC"), LogEventName.EPC_BANNER, "epc"),
    (re.compile(r"Received S1 Setup Request"), LogEventName.EPC_S1_REQUEST, "epc"),
    (re.compile(r"Sending S1 Setup Response"), LogEventName.EPC_S1_RESPONSE, "epc"),
    (re.compile(r"S1 Setup Failure"), LogEventName.EPC_S1_FAILURE, "epc"),
    (re.compile(r"SCTP Association Shutdown"), LogEventName.EPC_SCTP_SHUTDOWN, "epc"),
    # UHD / RF
    (re.compile(r"No UHD Devices Found"), LogEventName.UHD_NO_DEVICE, "enb"),
    (re.compile(r"Could not find usrp_b200_fw\.hex"), LogEventName.UHD_FW_MISSING, "enb"),
    (re.compile(r"Tx while waiting for EOB, timed out"), LogEventName.RF_TX_ERROR, "enb"),
    (re.compile(r"underflow", re.IGNORECASE), LogEventName.RF_UNDERFLOW, "enb"),
    # RF 初始化失败（可恢复）: 实机样本 uhd_init failed, freeing... /
    # Error initializing radio. —— eNB 进程随后退出, 看门狗按进程死亡正常恢复
    (re.compile(r"uhd_init failed"), LogEventName.RF_INIT_ERROR, "enb"),
    (re.compile(r"Error initializing radio"), LogEventName.RF_INIT_ERROR, "enb"),
]

_EPC_INIT_COMPILED = [(re.compile(re.escape(line)), line) for line in EPC_INIT_LINES]


class LogEventParser:
    """把一行 srsRAN 日志映射为一个 LogEvent（或 None）。

    service 参数是日志来源单元（"enb"/"epc"），用于校验规则归属：
    EPC 侧规则（S1 Request/Response、SCTP Shutdown、EPC init）只在
    epc 单元日志中生效，避免 eNB 侧相似文本造成误判。
    """

    def parse(self, service: str, ts: float, line: str) -> Optional[LogEvent]:
        if not line:
            return None

        # EPC init lines: prefix match against the known real lines
        if service == "epc":
            for pat, canon in _EPC_INIT_COMPILED:
                if line.lstrip().startswith(canon.rstrip(".")) or canon in line:
                    return LogEvent(LogEventName.EPC_INIT_LINE, service, ts,
                                    line[:300], detail=canon)

        for pat, name, rule_service in _RULES:
            if rule_service != service:
                continue
            m = pat.search(line)
            if not m:
                continue
            # 配置回退行不算错误（实机样本）:
            #   "Couldn't open , trying /root/.config/srsran/enb.conf"
            # 空命令行路径 -> 回退到 ~/.config 是 srsRAN 正常查找顺序。
            if name == LogEventName.CONFIG_FILE_ERROR and ", trying" in line:
                return None
            detail = ""
            if name == LogEventName.ENB_FREQ_SET:
                fm = _RE_FREQ.search(line)
                if fm:
                    detail = f"DL={fm.group(1)}MHz UL={fm.group(2)}MHz prb={fm.group(3)}"
            elif name == LogEventName.EPC_S1_FAILURE:
                cm = _RE_S1_FAILURE_CAUSE.search(line)
                detail = cm.group(1).strip() if cm else "unknown cause"
            elif name == LogEventName.CONFIG_FILE_ERROR:
                cm = _RE_COULDNT_OPEN.search(line)
                detail = cm.group(1) if cm else ""
            elif name == LogEventName.CONFIG_OPTION_ERROR:
                cm = _RE_UNRECOGNISED.search(line)
                detail = cm.group(1).strip()[:200] if cm else ""
            return LogEvent(name, service, ts, line[:300], detail=detail)
        return None
