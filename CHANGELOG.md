# Changelog

本项目的所有显著变更记录在此。版本号遵循 [语义化版本](https://semver.org/)：
版本唯一权威定义在 `backend/app/__init__.py` 的 `__version__`，
git tag 与 GitHub Release 与之保持一致（API `/api/status` 与前端顶栏均显示该版本）。

## [2.0.3] - 2026-08-21

### 修复（RK3588 + B210 + Ubuntu 22.04 实机部署发现）

- **LinuxSystemProvider 磁盘统计崩溃**：`shutil.disk_usage()` 返回值没有
  `.percent` 属性（那是 psutil 的），看门狗每秒崩溃重启；另有
  `_last_diskstats` 属性名笔误。修复后看门狗与 `/api/status` 均正常。
- **srsRAN 配置回退行误判为 CONFIG_ERROR**：`Couldn't open , trying
  /root/.config/srsran/enb.conf` 是 srsRAN 正常的配置查找回退输出，
  旧正则会捕获逗号并直接进 FAULT。正则改为 `[^\s,]+\s` 后不再误伤。
- **看门狗重启后 EPC 误报"未就绪"→ 无限恢复失败 → FAULT**：旧实现首次
  只拉 `boot_history_s=300s` 日志，而 EPC 可能已连续运行数小时，其
  `Initialized` 日志在窗口外 → `epc_stage` 卡在 STARTING → 45s 超时 →
  恢复动作是幂等 start（无新日志可验证）→ 3 次失败进 FAULT（实机复现）。
  修复：首次拉取改为 `journalctl -b`（本次开机全量），服务当前运行周期
  的日志证据完整重放；恢复策略对「EPC 挂在初始化（READY 超时）」也执行
  restart（幂等 start 对卡死进程无效）。
- **分进程部署下 Web 显示 USRP 离线**：manager 进程（SRSRAN_MANAGER_ONLY）
  原先不装配日志聚合器，S1/USRP 状态回退到 provider 探测 —— 而 eNB 持有
  B210 时 `uhd_find_devices` 结果不可靠。现在 manager 进程也装配日志管线
  （monitor tick 泵送），USRP/S1 状态一律以 eNB 日志证据为准。
- **新增 `RF_INIT_ERROR` 日志事件**（`uhd_init failed` / `Error initializing
  radio`）：B210 USB 句柄未释放等可恢复的 RF 初始化失败按「进程死亡」正常
  自动恢复，不再误入 CONFIG_ERROR/FAULT。

### 变更

- `watchdog.stages.enb_rf_timeout` 默认 90s → 180s（RK3588 上 B210 +
  大 PRB 初始化实测较慢；板端配置以 `/etc/srsran-manager/config.yaml` 为准）

## [2.0.2] - 2026-08-21

### 修复

- **install.sh / uninstall.sh 可执行位丢失**：此前上传脚本以 100644 模式入库，
  导致 Linux 上 `sudo ./deploy/install.sh` 报 `command not found`。
  现已改为 100755，clone 后可直接执行。
  旧版本克隆的临时解决办法：`chmod +x deploy/*.sh` 或 `sudo bash deploy/install.sh`
- deployment.md 常见问题补充上述说明

## [2.0.1] - 2026-08-21

### 新增

- **完整部署指南** `docs/deployment.md`：前置条件检查表、一条命令部署、
  部署后验证（服务/日志/Web/curl）、按环境校准清单、日常运维命令、
  FAULT 处理流程、版本升级步骤、常见问题（S1 不通/USRP 显示/Token 丢失等）、
  排障用架构图
- README 部署章节重写并链接部署指南

### 修正

- `config.example.yaml`：移除 v1 遗留的 `start_timeout`（v2 已改分阶段超时），
  补充 `watchdog.stages.*` 与 `linux.logs.*`（journalctl 日志源配置）注释说明

## [2.0.0] - 2026-08-21

### 破坏性变更（看门狗判定体系重构）

- **看门狗核心改为日志事件驱动**：不再使用「进程存在 = 正常 / S1 断开 = 故障 /
  uhd_find_devices 失败 = 掉线 / 30 秒未成功 = 失败」的粗粒度判定，
  改为 `日志事件 + 进程状态 + 网络状态 + 时间状态` 联合判定。
- `S1Status.connected`（bool）降级为兼容视图，**新增 `S1Status.state` 枚举**：
  `S1_DOWN / S1_CONNECTING / S1_READY / S1_LOST / S1_CONFIG_ERROR`
- 统一 `start_timeout` 删除，改为**分阶段超时**（`watchdog.stages.*`）。

### 新增

- **日志事件解析器** `watchdog/log_events.py`：基于实机 journalctl 样本逐条匹配
  （eNB banner / Reading configuration file / RF device 'UHD' successfully opened /
  ==== eNodeB started === / Setting frequency / EPC 7 条 Initialized /
  Received S1 Setup Request / Sending S1 Setup Response / SCTP Association Shutdown /
  S1 Setup Failure / No UHD Devices Found / usrp_b200_fw.hex 缺失 /
  Tx while waiting for EOB timed out / underflow / Couldn't open / Unrecognised options）
- **组件状态聚合器** `watchdog/aggregator.py`：
  - `enb_stage`: DOWN → STARTING → CONFIG_LOADING → RF_READY → RUNNING
  - `epc_stage`: DOWN → STARTING → READY（7 条 Initialized 全部出现）
  - `s1_state` 五态机（见上）
- **日志采集管线** `watchdog/pipeline.py` + `providers/linux_logs.py`
  （journalctl JSON 增量拉取，去重 + 重叠窗口；看门狗重启后可从既有日志恢复状态）
  与 `mock/logs.py`（Windows 剧本，与真实日志同格式、走同一条解析路径）
- **看门狗新状态**：`EPC_READY / ENB_RF_INITIALIZING / ENB_RUNNING / S1_CONNECTING / DEGRADED`
  （DEGRADED = S1_LOST 等待 eNB 自行重连的宽限期）
- **CONFIG_ERROR → FAULT**：unknown-PLMN / 配置文件打不开 / 选项不识别 /
  USRP 固件缺失等，重启无意义——直接 FAULT 等待人工修复，不消耗自动恢复次数
- **S1_LOST 处理**：S1_READY 后 SCTP Association Shutdown ≠ 启动失败；
  宽限期内 DEGRADED，超时后仅重启 eNB（最小影响半径）
- **恢复等待中止**：恢复轮询期间一旦出现配置错误立即中止，不再空等超时
- **时间戳字段**：`last_rf_ready_time / last_s1_ready_time / last_sctp_shutdown_time`
- **版本管理**：`__version__` 单点定义 + `/api/status` 返回 `version` +
  前端顶栏版本 badge + 本 CHANGELOG
- 前端适配：看门狗新状态配色、S1 五态卡片、FAULT 原因 badge
- 测试从 51 项扩至 **66 项**（日志解析 / 聚合器 / 分阶段超时 / S1_LOST /
  CONFIG_ERROR / auto-start 时序竞态修复）

### 变更

- CPU 判定只保留 WARNING（50 PRB 时 eNB 单核 104% 属正常），永不 CRITICAL
- USRP 运行期判定依据 eNB 日志（RF opened / No UHD Devices Found），
  `uhd_find_devices` 仅作启动期辅助（eNB 持有设备时探测结果不可靠）
- systemd 的 activating/deactivating 视为存活，避免慢启动被误判为崩溃

## [1.0.0] - 2026-08-20

### 初始版本

- Provider 架构（Mock/Linux 同接口）、看门狗状态机（进程/网络判定）、
  有限次自动恢复（3 次 → FAULT）、FastAPI + WebSocket 后端、
  Vue 3 前端、SQLite 事件/日志/kv_state、API Token 认证、
  systemd 部署脚本（manager/watchdog/epc/enb 四单元）、51 项自动化测试
