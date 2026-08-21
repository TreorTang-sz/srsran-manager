# 部署指南（Linux 实机）

适用环境：**Ubuntu 20.04 / 22.04（ARM64 / x86_64）+ srsRAN 已安装 + USRP B210**。
开发机 Windows Mock 模式验证请参考 [README](../README.md) 的开发部分。

---

## 0. 前置条件

| 项目 | 要求 | 检查命令 |
|---|---|---|
| 操作系统 | Ubuntu 20.04 / 22.04（systemd） | `lsb_release -a` |
| Python | ≥ 3.8（系统自带即可） | `python3 -V` |
| srsRAN | srsepc / srsenb 可执行且配置可用 | `command -v srsepc srsenb` |
| srsRAN 配置 | enb.conf / epc.conf 就绪 | 见下方「srsRAN 配置位置」 |
| USRP | B210 已连接（`lsusb` 可见） | `lsusb \| grep -i usrp` |
| 网络 | 局域网可达（浏览器访问用） | — |

**srsRAN 配置位置**：本项目以 systemd 方式管理 srsRAN，配置统一放在 `/etc/srsran/`：

```bash
sudo mkdir -p /etc/srsran
# 若配置在 ~/.config/srsran，复制过去：
sudo cp ~/.config/srsran/*.conf /etc/srsran/
```

> srsRAN 的 enb.conf / epc.conf 内容（频点、PRB、PLMN、IMSI 等）不在本文范围，
> 按你现有的可用配置放置即可。

---

## 1. 标准部署（推荐）：clone 后一条命令

```bash
git clone https://github.com/TreorTang-sz/srsran-manager.git
cd srsran-manager
sudo ./deploy/install.sh
```

**这一条命令会自动完成**（脚本约 1–3 分钟）：

1. 安装系统依赖（python3-venv、rsync，缺失时）
2. 复制项目到 `/opt/srsran-manager`
3. 创建 Python venv 并安装依赖（纯 Python 包，ARM64 兼容）
4. 检测 srsepc / srsenb 实际路径写入 systemd 单元
5. 生成 `/etc/srsran-manager/config.yaml` 并**随机生成 API Token**（终端会打印，务必保存）
6. 加载 SCTP 内核模块（S1 检测用）并设置开机自动加载
7. 安装 4 个 systemd 单元并 enable 开机自启
8. 启动 srsran-watchdog + srsran-manager；`auto_start: true` 使看门狗**自动拉起 EPC → eNB → S1**

前端使用仓库中已构建好的 `frontend/dist/`，无需在服务器上安装 Node.js。

**部署特定版本**：

```bash
git clone -b v2.0.1 https://github.com/TreorTang-sz/srsran-manager.git
```

---

## 2. 部署后验证（5 分钟）

### 2.1 看服务

```bash
systemctl status srsran-watchdog srsran-manager srsran-epc srsran-enb --no-pager
```

四个单元都应为 `active (running)`（epc/enb 由看门狗拉起，稍等几秒）。

### 2.2 看日志（看门狗状态机的实时判定）

```bash
journalctl -u srsran-watchdog -f
```

正常应看到启动链推进：`STARTING → EPC_READY → ENB_RF_INITIALIZING → ENB_RUNNING → S1_CONNECTING → RUNNING`。

### 2.3 看 Web

浏览器打开 `http://<服务器IP>:8080`：

- 顶栏应显示 `v2.0.1`（版本号与 git tag 一致）
- 状态徽章走完启动链后变绿（RUNNING）
- 右上角 🔑 填入 install.sh 打印的 **API Token**（不填只能看，不能控制）
- ServiceCards：EPC / eNB 服务状态、S1 五态（`S1 READY`）、USRP `CONNECTED`
- 有 UE 接入时 UeTable / 吞吐量图表出现数据

### 2.4 命令行快查

```bash
# 带 Token 查询状态（Token 换成自己的）
curl -H "X-API-Token: <TOKEN>" http://127.0.0.1:8080/api/status | python3 -m json.tool
```

关键字段：`watchdog.state`（应为 `RUNNING`）、`s1.state`（应为 `S1_READY`）、
`version`（部署版本）。

---

## 3. 部署后校准清单（按实际环境微调）

编辑 `/etc/srsran-manager/config.yaml` 后重启服务生效：
`sudo systemctl restart srsran-watchdog srsran-manager`

| # | 项目 | 位置 | 说明 |
|---|---|---|---|
| 1 | **eNB metrics CSV** | `linux.metrics.enb_metrics_file` | enb.conf 需开启 `[metrics] csv_file=...`，路径与此处一致（UE 表/吞吐量数据源）。默认 `/var/log/srsran/enb_metrics.csv`（目录需存在且可写） |
| 2 | **核心网接口名** | `linux.core_traffic.interfaces` | `ip link` 查看 srsEPC 创建的 SGi 接口（默认 `srs_spgw_sgi`），核心网流量统计用 |
| 3 | **日志单元名** | `linux.logs.enb_unit / epc_unit` | 必须与 systemd 单元名一致（默认 `srsran-enb` / `srsran-epc`，一般不用改） |
| 4 | **bitrate 单位** | `linux.metrics.bitrate_scale` | srsRAN 各版本 metrics 单位可能不同（bps/ Mbps），对不上时按倍率调整 |
| 5 | **关闭故障注入 API** | `security.dev_fault_api: false` | 生产环境建议关闭（mock 模式自动开启） |

**日志判定路径校验**（v2 核心）：

```bash
# 确认 journalctl 能看到 srsRAN 日志（看门狗靠这些日志判定状态）
journalctl -u srsran-enb --no-pager | grep -E "eNodeB started|RF device|S1 Setup"
journalctl -u srsran-epc --no-pager | grep "Initialized"
```

若以上命令有输出，看门狗的状态判定即可正常工作（journalctl 由
`linux.logs.*` 配置驱动，与脚本单元一一对应）。

---

## 4. 日常运维命令

### 4.1 服务控制

```bash
# 基站网络（EPC + eNB 一起）——推荐通过 Web 界面或 API，也可直接：
sudo systemctl stop srsran-epc srsran-enb     # 停止网络（看门狗会在下个周期发现并按策略处理）

# 管理系统自身
sudo systemctl restart srsran-manager     # 重启 Web（不影响基站）
sudo systemctl restart srsran-watchdog    # 重启看门狗（auto_start 会重新拉起网络）
```

> 停 epc/enb 单元会触发看门狗恢复逻辑。**临时维护**请先在 Web 界面点
> 「停止网络」（这会把 desired_running 置 false，看门狗不会去拉起）。

### 4.2 看日志

```bash
journalctl -u srsran-watchdog -f          # 看门狗状态机 + 恢复动作
journalctl -u srsran-manager -f           # Web/API
journalctl -u srsran-enb -f               # srsRAN eNB 原始日志
journalctl -u srsran-epc -f               # srsRAN EPC 原始日志
```

### 4.3 FAULT 处理

看门狗连续恢复失败 3 次（或检测到配置错误如 unknown-PLMN）进入 **FAULT**，
停止一切自动动作。处理方式：

1. Web 界面查看 FAULT 原因 badge（如 `CONFIG_ERROR: ...`）
2. 配置错误 → 修 `/etc/srsran/*.conf`，然后 Web 点「启动网络」复位（FAULT 下启动会自动清零计数并重启网络），或：
   ```bash
   curl -X POST -H "X-API-Token: <TOKEN>" http://127.0.0.1:8080/api/network/start
   ```
3. 复位会清零失败计数并强制重启 EPC + eNB 从新日志重建状态

### 4.4 升级版本

```bash
cd /opt/srsran-manager    # 或原 clone 目录
sudo systemctl stop srsran-watchdog srsran-manager
git fetch --tags
git checkout v2.0.1                # 或 main
sudo ./deploy/install.sh           # 幂等：配置/Token 保留，代码与依赖更新
```

SQLite 数据库（events / logs / kv_state）位于 `/opt/srsran-manager/backend/data/`，
升级不会清除。

---

## 5. 卸载

```bash
sudo ./deploy/uninstall.sh
```

停止并移除 4 个 systemd 单元；`/opt/srsran-manager` 与 `/etc/srsran-manager`
按脚本提示决定是否删除。

---

## 6. 常见问题

**Q: install.sh 提示 srsepc/srsenb 不存在？**
srsRAN 未安装或不在 PATH。确认 `command -v srsenb` 有输出后重跑脚本；
自定义路径可手动改 `/etc/systemd/system/srsran-enb.service` 的 ExecStart。

**Q: `sudo ./deploy/install.sh` 报 command not found？**
v2.0.1 及更早版本克隆的仓库中脚本丢失可执行位。执行：

```bash
chmod +x deploy/*.sh
sudo ./deploy/install.sh
```

或直接 `sudo bash deploy/install.sh`（v2.0.2 起已修复，新克隆无此问题）。

**Q: Web 打得开但 S1 一直 `S1_DOWN`？**
1. `journalctl -u srsran-enb | grep "S1 Setup"` —— 无输出说明 eNB 没走到 S1 阶段，看 RF 是否打开成功（B210 初始化慢，enb_rf_timeout 默认 90s）
2. 有 `S1 Setup Failure cause: misc - unknown-PLMN` → epc.conf 的 PLMN 与 enb.conf 不匹配，看门狗会正确地停在 FAULT 等你改配置
3. SCTP 模块：`lsmod | grep sctp`，无则 `sudo modprobe sctp`

**Q: USRP 显示 DISCONNECTED 但基站在跑？**
v2 中 USRP 运行期判定依据 eNB 日志（`RF device 'UHD' successfully opened`），
uhd_find_devices 仅启动期辅助。`journalctl -u srsran-enb | grep "RF device"` 确认。

**Q: eNB 启动期间 CPU 很高、页面状态停在 ENB_RF_INITIALIZING 很久？**
正常。B210 初始化 + UHD 固件加载期间单核打满是已知现象，v2 看门狗按
日志证据（而非响应速度）判定，enb_rf_timeout 默认 90 秒，一般不需要改。

**Q: 看门狗重启后要重启基站吗？**
不需要。日志管线启动时回拉 `boot_history_s`（默认 300s）内的 journalctl
历史，从既有日志重建 EPC/eNB/S1 状态。

**Q: Token 丢了？**
`sudo grep api_token /etc/srsran-manager/config.yaml`，或生成新的：
`python3 -c "import secrets; print(secrets.token_hex(16))"` 替换后重启服务。

---

## 7. 架构速览（排障用）

```
浏览器 ── HTTP/WS ──> srsran-manager (uvicorn :8080, FastAPI + 静态前端)
                          │ 读写
                          ▼
                     SQLite kv_state（跨进程协调 desired_running 等）
                          │ 轮询
                          ▼
                     srsran-watchdog（独立进程）
                       │ journalctl 增量拉取 ──> 日志解析 ──> 状态聚合 ──> 状态机
                       │ systemctl start/stop/restart（有限次恢复）
                       ▼
                 srsran-epc / srsran-enb（systemd 管理的 srsRAN）
```

- Web 与看门狗**互不依赖**：Web 挂了看门狗照常保护基站；看门狗挂了 Web 照常可看
- 看门狗判定依据：**日志事件（主）+ 进程状态 + SCTP + 系统指标**
- 自动恢复上限 3 次进 FAULT；配置类错误直接 FAULT 不消耗次数
