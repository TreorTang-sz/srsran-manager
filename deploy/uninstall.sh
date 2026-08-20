#!/usr/bin/env bash
# srsRAN Manager 卸载脚本
# 用法: sudo ./deploy/uninstall.sh [--purge]
#   默认: 停止并移除服务, 保留 /opt/srsran-manager 与配置/数据
#   --purge: 同时删除程序目录、配置与数据库
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "ERROR: 请以 root 运行 (sudo $0)"; exit 1; }

echo "==> 停止服务"
systemctl stop srsran-manager.service srsran-watchdog.service \
               srsran-enb.service srsran-epc.service 2>/dev/null || true

echo "==> 移除 systemd 单元"
systemctl disable srsran-manager.service srsran-watchdog.service \
                  srsran-enb.service srsran-epc.service 2>/dev/null || true
rm -f /etc/systemd/system/srsran-{epc,enb,watchdog,manager}.service
systemctl daemon-reload

if [ "${1:-}" = "--purge" ]; then
    echo "==> 删除程序与数据 (--purge)"
    rm -rf /opt/srsran-manager /etc/srsran-manager
    echo "==> 卸载完成（已删除全部文件）"
else
    echo "==> 卸载完成。保留以下内容:"
    echo "    /opt/srsran-manager      (程序, 含数据库 backend/data/)"
    echo "    /etc/srsran-manager      (配置)"
    echo "    使用 --purge 可彻底删除。"
fi
