#!/usr/bin/env bash
# srsRAN Manager 安装脚本 —— Ubuntu 20.04 / 22.04 (ARM64/x86_64)
#
# 用法: sudo ./deploy/install.sh
#
# 做了什么:
#   0. 安装系统依赖 (python3-venv / rsync, 缺失时)
#   1. 复制项目到 /opt/srsran-manager
#   2. 创建 Python venv 并安装依赖 (纯 Python 包, ARM64 兼容)
#   3. 检测 srsepc/srsenb 实际路径并写入 systemd 单元
#   4. 生成 /etc/srsran-manager/config.yaml (若不存在) 并生成随机 API Token
#   5. 安装 4 个 systemd 单元并启用开机自启
#   6. 前端使用随包分发的 dist/ (在开发机构建); 若缺失且本机有 npm 才现场构建
set -euo pipefail

INSTALL_DIR=/opt/srsran-manager
CONF_DIR=/etc/srsran-manager
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ "$(id -u)" -eq 0 ] || { echo "ERROR: 请以 root 运行 (sudo $0)"; exit 1; }

echo "==> 源目录: $SRC_DIR"
echo "==> 安装到: $INSTALL_DIR"

# --------------------------------------------------------------------------
# 0. 系统依赖 (Ubuntu 20.04 与 22.04 均适用)
# --------------------------------------------------------------------------
NEED_PKGS=()
dpkg -s python3-venv  >/dev/null 2>&1 || NEED_PKGS+=(python3-venv)
command -v rsync      >/dev/null 2>&1 || NEED_PKGS+=(rsync)
command -v systemctl  >/dev/null 2>&1 || { echo "ERROR: 未找到 systemctl, 需要 systemd"; exit 1; }

if [ "${#NEED_PKGS[@]}" -gt 0 ]; then
    echo "==> 安装系统依赖: ${NEED_PKGS[*]}"
    apt-get update -qq
    apt-get install -y -qq "${NEED_PKGS[@]}"
fi

# --------------------------------------------------------------------------
# 1. 复制项目
# --------------------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude 'backend/.venv' --exclude 'backend/data' \
    --exclude 'frontend/node_modules' --exclude '__pycache__' \
    --exclude '.git' --exclude '.pytest_cache' \
    "$SRC_DIR"/ "$INSTALL_DIR"/
mkdir -p "$INSTALL_DIR/backend/data"

# --------------------------------------------------------------------------
# 2. Python 环境
#    Ubuntu 20.04 -> Python 3.8, 22.04 -> Python 3.10, 均满足要求 (>=3.8)
# --------------------------------------------------------------------------
if [ ! -d "$INSTALL_DIR/backend/.venv" ]; then
    echo "==> 创建 venv (python$(python3 -V 2>&1 | cut -d' ' -f2))"
    python3 -m venv "$INSTALL_DIR/backend/.venv"
fi
echo "==> 安装 Python 依赖"
"$INSTALL_DIR/backend/.venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/backend/.venv/bin/pip" install -q -r "$INSTALL_DIR/backend/requirements.txt"

# --------------------------------------------------------------------------
# 3. 检测 srsRAN 二进制路径 -> 写入 systemd 单元
# --------------------------------------------------------------------------
ENB_BIN="$(command -v srsenb || echo /usr/bin/srsenb)"
EPC_BIN="$(command -v srsepc || echo /usr/bin/srsepc)"
echo "==> srsepc: $EPC_BIN"
echo "==> srsenb: $ENB_BIN"
[ -x "$EPC_BIN" ] || echo "   !! 警告: $EPC_BIN 不存在, 请确认 srsRAN 已安装 (或在 PATH 中)"
[ -x "$ENB_BIN" ] || echo "   !! 警告: $ENB_BIN 不存在, 请确认 srsRAN 已安装 (或在 PATH 中)"

# 用检测到的实际路径替换单元中的 ExecStart
sed -i "s|^ExecStart=.*|ExecStart=${EPC_BIN}|" "$INSTALL_DIR/deploy/systemd/srsran-epc.service"
sed -i "s|^ExecStart=.*|ExecStart=${ENB_BIN}|" "$INSTALL_DIR/deploy/systemd/srsran-enb.service"

# srsRAN 配置位置检测: systemd 单元 WorkingDirectory=/etc/srsran,
# srsRAN 会从工作目录读取 enb.conf / epc.conf (其次 ~/.config/srsran)
if [ ! -f /etc/srsran/enb.conf ]; then
    FOUND="$(find /root/.config/srsran /home/*/.config/srsran -maxdepth 1 -name enb.conf 2>/dev/null | head -1 || true)"
    echo ""
    echo "   !! 注意: /etc/srsran/enb.conf 不存在"
    if [ -n "${FOUND:-}" ]; then
        echo "      检测到配置位于: $FOUND"
        echo "      建议复制到系统目录: mkdir -p /etc/srsran && cp ${FOUND%/enb.conf}/*.conf /etc/srsran/"
    else
        echo "      未找到现成 enb.conf —— 请将 srsRAN 配置放到 /etc/srsran/"
    fi
    echo ""
fi

# --------------------------------------------------------------------------
# 4. 配置文件 + API Token
# --------------------------------------------------------------------------
mkdir -p "$CONF_DIR"
if [ ! -f "$CONF_DIR/config.yaml" ]; then
    echo "==> 生成 $CONF_DIR/config.yaml"
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
    sed "s|^  api_token: .*|  api_token: ${TOKEN}|" \
        "$INSTALL_DIR/config/config.example.yaml" > "$CONF_DIR/config.yaml"
    echo ""
    echo "=============================================================="
    echo "  已生成 API Token (保存在 $CONF_DIR/config.yaml):"
    echo "      $TOKEN"
    echo "  请保存此 Token —— 浏览器右上角 🔑 处填写后才能执行控制操作。"
    echo "=============================================================="
    echo ""
else
    echo "==> 配置已存在, 跳过 ($CONF_DIR/config.yaml)"
fi

# --------------------------------------------------------------------------
# 5. SCTP 内核模块 (S1 检测需要, 且确保开机自动加载)
# --------------------------------------------------------------------------
if ! lsmod | grep -q '^sctp '; then
    echo "==> 加载 SCTP 内核模块"
    modprobe sctp 2>/dev/null || echo "   !! modprobe sctp 失败, S1 检测将退化为日志匹配方式"
fi
if [ ! -f /etc/modules-load.d/srsran-sctp.conf ]; then
    echo "sctp" > /etc/modules-load.d/srsran-sctp.conf
fi

# --------------------------------------------------------------------------
# 6. 前端静态文件 (优先使用开发机随包分发的 dist/)
# --------------------------------------------------------------------------
if [ ! -f "$INSTALL_DIR/frontend/dist/index.html" ] && command -v npm >/dev/null 2>&1; then
    echo "==> 构建前端"
    (cd "$INSTALL_DIR/frontend" && npm install --no-audit --no-fund && npm run build)
elif [ ! -f "$INSTALL_DIR/frontend/dist/index.html" ]; then
    echo "!! 未找到 frontend/dist —— 前端不可用 (后端 API 正常)。"
    echo "!! 请在开发机执行: cd frontend && npm install && npm run build 后重新分发。"
else
    echo "==> 前端静态文件就绪 (frontend/dist)"
fi

# --------------------------------------------------------------------------
# 7. systemd 单元
# --------------------------------------------------------------------------
echo "==> 安装 systemd 单元"
for unit in srsran-epc srsran-enb srsran-watchdog srsran-manager; do
    install -m 644 "$INSTALL_DIR/deploy/systemd/${unit}.service" \
        "/etc/systemd/system/${unit}.service"
done
systemctl daemon-reload
systemctl enable srsran-epc.service srsran-enb.service \
                srsran-watchdog.service srsran-manager.service

# 先起看门狗和 Web; epc/enb 由看门狗 auto_start 拉起
systemctl restart srsran-watchdog.service
systemctl restart srsran-manager.service

echo ""
echo "==> 安装完成。服务状态:"
systemctl --no-pager -l status srsran-watchdog srsran-manager | head -20 || true
echo ""
echo "    Web 界面:   http://<服务器IP>:8080"
echo "    查看日志:   journalctl -u srsran-watchdog -f"
echo "                journalctl -u srsran-manager -f"
echo "                journalctl -u srsran-enb -f"
echo ""
echo "    部署后校准清单:"
echo "    1. 确认 srsENB metrics CSV 已开启 (enb.conf [metrics] csv_file=...)"
echo "       并与 config.yaml 的 linux.metrics.enb_metrics_file 一致"
echo "    2. ip link 确认核心网接口名, 更新 linux.core_traffic.interfaces"
echo "    3. 观察 Web 页面 UE 表/吞吐量是否正常, 必要时调整 bitrate_scale"
