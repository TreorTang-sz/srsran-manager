# srsRAN Manager

Ubuntu srsRAN 4G 基站服务器的管理、监控与看门狗系统。面向 **ARM64 / RK3588 / Ubuntu 20.04 或 22.04 / USRP B210** 无头（无显示器/键盘）运行环境，日常管理完全通过浏览器完成。

```
┌────────────────────────── 浏览器 (PC / 手机) ──────────────────────────┐
│            http://SERVER_IP:8080                                     │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ REST + WebSocket
┌───────────────────────────────▼───────────────────────────────────────┐
│  srsran-manager.service  (FastAPI + Vue 静态前端, 8080)               │
│      │  共享 SQLite (kv_state): desired_running / 故障复位            │
│  srsran-watchdog.service (状态机引擎 + 健康检查 + 有限次自动恢复)      │
│      │ systemctl start/stop/restart (仅预定义操作)                    │
│  srsran-epc.service ── srsepc     srsran-enb.service ── srsenb       │
│      └── /proc /sys · SCTP(S1) · UHD(B210) · srsRAN metrics CSV      │
└───────────────────────────────────────────────────────────────────────┘
```

## 核心特性

- **无人值守自启动**：开机后 systemd 拉起看门狗，`auto_start` 自动建立 LTE 网络（EPC→ENB→S1）
- **看门狗状态机**：`STOPPED → STARTING → RUNNING ⇄ WARNING → RECOVERING → FAULT`，显式 FSM 而非散落 if
- **深度健康判断**：不靠 `pgrep` —— 区分进程存在 / 服务正常 / S1 连接 / UHD 正常 / B210 在位
- **有限次恢复**：连续失败 3 次进入 FAULT 停止自动重启，等待人工复位（禁止无限重启）
- **故障注入**（Mock 模式）：eNB/EPC 崩溃、S1 断开、B210 拔出、高 CPU、高温、恢复失败 —— Windows 上即可完整验证状态机
- **监控指标**：CPU（总/每核）、内存、Swap、磁盘容量与 IO、网络 RX/TX、CPU 温度、运行时间；UE 数量/RNTI/CQI/MCS/DL/UL；空口与核心网吞吐量分离
- **事件与日志**：SQLite 持久化（events / logs / kv_state），Web 可查可过滤
- **安全**：控制接口需 API Token；Web 层不执行任意 shell，仅调用固定 systemctl 动作；服务单元带 systemd 加固

## 项目结构

```
srsran-manager/
├── backend/
│   ├── app/
│   │   ├── main.py               FastAPI 入口 (uvicorn app.main:app)
│   │   ├── watchdog_runner.py    分离部署的看门狗独立入口
│   │   ├── runtime.py            组件装配 (依赖注入)
│   │   ├── config.py             配置 (yaml + 环境变量)
│   │   ├── models.py             数据模型 (Pydantic)
│   │   ├── api/                  REST + WebSocket 路由
│   │   ├── watchdog/             状态机 / 健康检查 / 恢复策略
│   │   ├── providers/            Provider 抽象 + Linux 实现
│   │   ├── mock/                 Windows Mock 实现 + 故障注入
│   │   ├── core/                 事件总线 / 控制服务 / 吞吐量历史
│   │   └── database/             SQLite (events/logs/kv_state)
│   └── tests/                    51 个自动化测试
├── frontend/                     Vue 3 + TypeScript + ECharts
├── deploy/systemd/               4 个 systemd 服务单元
├── deploy/install.sh|uninstall.sh
├── config/config.example.yaml
└── docs/architecture.md
```

## 快速开始（Windows 开发 / Mock 模式）

前置：Python 3.10+（纯 Python 依赖，无编译），Node 18+（仅前端构建需要）。

```bash
# 1. 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 前端（构建静态文件, FastAPI 直接托管）
cd ../frontend
npm install
npm run build

# 3. 运行（Mock 模式 + 控制 Token）
cd ../backend
set SRSRAN_MODE=mock
set SRSRAN_API_TOKEN=dev-token-123
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

浏览器打开 <http://127.0.0.1:8080>：

- 概览页：服务状态卡（EPC/ENB/S1/B210）、系统资源、实时吞吐量曲线（LTE DL/UL + Core DL/UL）、在线 UE 表
- 右上角 🔑 填入 API Token 后可使用控制面板（启动/停止/重启，危险操作二次确认）
- Mock 模式下页面底部有 **故障注入** 面板：点击「eNB 崩溃」可观察 `RUNNING → RECOVERING → RUNNING` 全过程

前端开发模式（热更新）：`npm run dev`（Vite :5173，代理 /api 与 /ws 到 :8080）。

## 运行测试

```bash
cd backend
.venv\Scripts\python -m pytest tests -q        # Windows
# Linux: .venv/bin/python -m pytest tests -q
```

覆盖：状态机转移表、健康分级、恢复策略、Mock Provider、SQLite 读写、
REST API + Token 鉴权、看门狗端到端（崩溃恢复 / S1 断开 / B210 拔出 /
连续失败 → FAULT / 人工复位 / 开机自启动 / 分离部署协调）。

## 部署到 Ubuntu（RK3588）

支持 Ubuntu 20.04（Python 3.8）与 22.04（Python 3.10），安装脚本会自动安装缺失的
`python3-venv`/`rsync`、检测 `srsepc`/`srsenb` 实际路径并写入 systemd 单元。

```bash
# 在服务器上（已安装 srsRAN + UHD）
sudo ./deploy/install.sh
```

安装脚本会：

1. 复制项目到 `/opt/srsran-manager`，创建 venv 安装依赖（纯 Python，ARM64 无兼容问题）
2. 生成 `/etc/srsran-manager/config.yaml` 与随机 API Token（终端会打印一次，请保存）
3. 安装并启用 4 个 systemd 服务：`srsran-epc` / `srsran-enb` / `srsran-watchdog` / `srsran-manager`
4. 启动看门狗与 Web；基站服务由看门狗 `auto_start` 自动拉起

卸载：`sudo ./deploy/uninstall.sh`（加 `--purge` 删除全部数据）。

常用运维命令：

```bash
systemctl status srsran-watchdog srsran-manager
journalctl -u srsran-watchdog -f          # 看门狗日志
journalctl -u srsran-enb -f               # 基站日志
```

## 配置

完整示例见 [config/config.example.yaml](config/config.example.yaml)。要点：

| 配置 | 说明 |
|---|---|
| `mode` | `auto`（推荐）：Linux 自动用真实 Provider，Windows 自动 Mock |
| `watchdog.max_recovery_attempts` | 连续恢复上限（默认 3，之后 FAULT） |
| `watchdog.auto_start` | 无人值守开机自启（默认 true） |
| `security.api_token` | 控制 API Token；留空则控制接口全部禁用 |
| `linux.metrics.enb_metrics_file` | srsENB metrics CSV 路径 |
| `linux.s1.method` | `sctp`（内核 SCTP 关联，推荐）或 `log`（journal 匹配） |
| `linux.core_traffic.interfaces` | 核心网流量统计接口（默认 `srs_spgw_sgi`） |

环境变量可覆盖配置：`SRSRAN_MODE` / `SRSRAN_API_TOKEN` / `SRSRAN_DB_PATH` /
`SRSRAN_HOST` / `SRSRAN_PORT` / `SRSRAN_WATCHDOG_ONLY` / `SRSRAN_MANAGER_ONLY`。

## API 一览

查询类（无需 Token）：

```
GET /api/status      综合快照      GET /api/system   系统指标
GET /api/enb         eNB 状态+指标 GET /api/epc      EPC 状态
GET /api/usrp        B210 状态     GET /api/s1       S1 状态
GET /api/ue          在线 UE       GET /api/throughput  吞吐量历史
GET /api/events      事件查询      GET /api/logs     日志查询
WS  /ws              每秒推送完整快照
```

控制类（需 `X-API-Token` 头）：

```
POST /api/enb/start|stop|restart      POST /api/epc/start|stop|restart
POST /api/network/start|stop|restart
POST /api/dev/fault/{name}            故障注入（仅 Mock / 开发）
POST /api/dev/fault/clear             清除全部注入故障
```

## 架构原则

1. Windows 开发，Linux 生产；Mock 与 Linux 使用**完全相同**的接口（Adapter/Provider）
2. Watchdog 不依赖 Web（独立 systemd 服务，可各自重启）
3. Web 不执行任意 shell，仅预定义 systemctl 动作
4. 进程存在 ≠ 正常：健康 = 服务 + S1 + UHD + B210 + LTE 业务
5. 自动恢复有限次数，禁止无限重启
6. 关键故障全部记录事件（ENB_CRASH / S1_DISCONNECTED / USRP_DISCONNECTED / …）

详见 [docs/architecture.md](docs/architecture.md)。

## Linux Provider 部署校准清单

以下实现已在代码就绪，部署时按实际环境校准：

- [ ] `srsepc` / `srsenb` 二进制路径（默认 `/usr/bin`）
- [ ] srsENB metrics CSV 开启与路径（`enb_metrics_file`）
- [ ] `bitrate_scale`（按 srsRAN 版本的 metrics 单位校准 Mbps 换算）
- [ ] 核心网流量接口名（`ip link` 确认 SGi/S1-U 接口）
- [ ] `uhd_find_devices` 可用且 B210 被 udev 识别
- [ ] SCTP 内核模块（`modprobe sctp`）
