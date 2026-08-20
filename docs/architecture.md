# 架构设计

## 1. 分层与依赖方向

```
                 ┌────────────────────────────────────┐
                 │  api/ (FastAPI REST + WebSocket)   │  ← 仅此层知道 HTTP
                 ├────────────────────────────────────┤
                 │  core/  ControlService · EventBus  │
                 │         ThroughputHistory          │
                 ├────────────────────────────────────┤
                 │  watchdog/  状态机 · 健康检查 · 恢复 │  ← 不 import FastAPI
                 ├────────────────────────────────────┤
                 │  providers/base.py  抽象接口        │  ← 业务只依赖这里
                 ├──────────┬─────────────────────────┤
                 │  mock/   │  providers/linux_*      │  ← 平台差异只在这两层
                 └──────────┴─────────────────────────┘
```

规则：

- **业务逻辑（watchdog / core / api）只 import `providers.base` 中的抽象接口**。
- 平台判定只发生在 `providers/factory.py` + `config.resolved_mode`（全代码库唯一
  `sys.platform` 检查点），杜绝散落的 `if windows ... else ...`。
- `watchdog/` 永不 import FastAPI —— 生产上可作为独立进程运行
  （`python -m app.watchdog_runner`），Web 挂掉不影响看门狗。

## 2. Provider 抽象（providers/base.py）

| 接口 | 职责 | Mock 实现 | Linux 实现 |
|---|---|---|---|
| `SystemMetricsProvider` | CPU/内存/磁盘/温度/IO/网络 | `mock/system.py`（随机波动+故障注入） | `linux_system.py`（/proc、/sys） |
| `ProcessManager` | 服务 start/stop/restart/status | `mock/process.py`（含 STARTING 延迟、模拟 systemd） | `linux_process.py`（systemctl show/start/stop/restart） |
| `UsrpProvider` | B210 在位/设备信息 | `mock/usrp.py` | `linux_usrp.py`（uhd_find_devices，带缓存） |
| `S1Provider` | S1 连接状态 | `mock/world.py` | `linux_network.py`（SCTP 关联 / journal 匹配） |
| `SrsranMetricsProvider` | UE/CQI/MCS/吞吐量 | `mock/srsran.py` | `linux_srsran.py`（metrics CSV tail / journalctl） |
| `CoreTrafficProvider` | 核心网实际流量 | `mock/srsran.py` | `linux_network.py`（/proc/net/dev 按接口差分） |

Mock 实现不是"假数据发生器"那么简单：`mock/world.py` 维护一个带时间演化的世界
（服务启动延迟、S1 建立延迟、UE 附着/ detach 概率），使看门狗在 Windows 上
经历与真实系统相同的时间行为。

## 3. 看门狗状态机（watchdog/state_machine.py）

```
                START
  STOPPED ───────────────► STARTING ──HEALTHY──► RUNNING ◄──HEALTHY──┐
     ▲                        │                     │  ▲             │
     │ STOP                   │CRITICAL             │  │WARNING      │HEALTHY
     │                        ▼                     ▼  │             │
     │                    RECOVERING ◄──CRITICAL── WARNING            │
     │                     │    │                                        │
     │  RECOVERY_OK ───────┘    │FAULT(连续失败≥max)                    │
     │                          ▼                                       │
     └───────── STOP ◄─────── FAULT ──RESET(人工)──► STARTING          │
```

- 转移表是**数据**（`TRANSITIONS` 字典），非法 (state, event) 组合被拒绝。
- `WatchdogEngine._tick()` 是唯一驱动者，按 `check_interval` 轮询：
  - 健康分级：`HealthChecker` 输出 OK / WARNING（软阈值）/ CRITICAL（硬故障）
  - CRITICAL → RECOVERING → `RecoveryManager.execute()`（重启 EPC/ENB 序列，
    `verify_delay` 后复检）
  - 连续失败计数达到 `max_recovery_attempts` → FAULT（停止一切自动重启）
  - FAULT 只能人工复位（Web「启动网络」按钮触发 `manual_reset_fault`）
- 组件级故障事件（ENB_CRASH 等）由引擎在**观测到的瞬间**确定性发布
  （`_announce_failures`，按"不健康周期"去重），不依赖恢复速度。

## 4. 事件总线与持久化

`core/bus.py`（EventBus，进程内发布订阅）→ `BusPersister` → SQLite：

- `events` 表：时间 / 类型 / 来源 / 级别 / 消息 / data(JSON)
- `logs` 表：时间 / 级别 / 模块 / 消息
- `kv_state` 表：看门狗状态快照、`desired_running`、`reset_fault_requested`

## 5. 单进程 vs 分离部署

**开发/Mock（单进程）**：`uvicorn app.main:app` —— Web + 看门狗 + 监控同进程，
`ControlService` 直接持有 engine 引用（同锁协调）。

**生产（分离，deploy/systemd/）**：

```
srsran-watchdog.service   SRSRAN_WATCHDOG_ONLY=1   engine + monitor, 无 Web
srsran-manager.service    SRSRAN_MANAGER_ONLY=1    FastAPI, 无 engine
```

跨进程协调全部经由共享 SQLite `kv_state`：

| key | 写者 | 读者 | 语义 |
|---|---|---|---|
| `desired_running` | ControlService（无 engine 时）/ engine | engine 每 tick | 期望运行状态（Web 下发的启停意图） |
| `watchdog_status` | engine 每 tick | manager `/api/status` | 状态机快照 |
| `reset_fault_requested` | ControlService | engine 每 tick | 人工 FAULT 复位请求 |

任一进程崩溃重启，另一进程不受影响；重启后从 kv_state 恢复协调状态。

## 6. 安全模型

1. **无任意 shell**：Web 控制链路为 `API → ControlService → ProcessManager`，
   Linux 实现只执行固定参数的 `systemctl <verb> <固定 unit>`，动词与单元名
   均来自配置，不接受用户输入拼接。
2. **API Token**：控制端点要求 `X-API-Token`；Token 只来自配置文件/环境变量；
   未配置 Token 时控制端点整体禁用（fail-closed）。
3. **故障注入 API**：仅在 Mock 模式或显式 `security.dev_fault_api: true` 时挂载。
4. **systemd 加固**：所有单元 `NoNewPrivileges`；manager 有
   `ProtectSystem=full` / `ProtectHome`；eNB `LimitMEMLOCK`（UHD 实时性）。
5. 恢复上限（max_recovery_attempts）本身也是一种保护——防止风暴式重启
   损害射频硬件与核心网稳定性。

## 7. 吞吐量数据流

```
srsENB metrics CSV ──► LinuxSrsranMetricsProvider ──► EnbMetrics (空口 DL/UL)
/proc/net/dev(SGi) ──► LinuxCoreTrafficProvider ───► CoreTraffic (核心网 DL/UL)
       两者 ──► MonitorLoop(1Hz) ──► ThroughputHistory(环形缓冲)
                            └──► Snapshot ──► /ws 每秒推送 ──► ECharts 曲线
```

`/api/throughput?window=N` 支持历史回填；`ThroughputHistory` 为环形缓冲，
未来接 Prometheus 时只需再加一个订阅者把同样的点推给 client 库，业务层不变。
