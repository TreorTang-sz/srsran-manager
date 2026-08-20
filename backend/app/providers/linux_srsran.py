"""srsENB metrics provider + SrsranMetricsAdapter (production).

DEPLOYMENT STATUS: written for Phase 6, to be verified against the
actual srsRAN 4G version installed on the RK3588. The adapter maps the
CSV columns published by ``srsenb`` metrics into the internal EnbMetrics
model; column aliases cover the known srsRAN 4G variants. If the field
names differ on the deployed version, only ALIASES below needs tuning —
business logic stays untouched.

Sources:
  * file    - tail of a metrics CSV file (configure srsenb to write it,
              or Redirect= in the systemd unit)
  * journal - ``journalctl -u srsran-enb --output cat`` last lines
"""
from __future__ import annotations

import csv
import io
import subprocess
import time
from typing import Dict, List, Optional

from app.config import AppConfig
from app.models import EnbMetrics, UEInfo

# column aliases (lowercase) -> internal field
ALIASES: Dict[str, List[str]] = {
    "rnti": ["rnti"],
    "cqi": ["cqi", "dl_cqi"],
    "mcs_dl": ["mcs_dl", "dl_mcs", "mcs", "mcs1_dl"],
    "mcs_ul": ["mcs_ul", "ul_mcs", "mcs2_ul"],
    "dl_bps": ["dl_brate", "dbrl", "dl_bitrate", "tx_brate", "dl_mcsx"],
    "ul_bps": ["ul_brate", "dbtr", "ul_bitrate", "rx_brate", "ul_mcsx"],
    "ue_id": ["ue", "ue_id", "ue_idx"],
}


class SrsranMetricsAdapter:
    """Normalises srsRAN metrics CSV rows into EnbMetrics."""

    def __init__(self, bitrate_scale: float = 1.0) -> None:
        # bitrate_scale converts source bitrate unit to bps
        self._scale = bitrate_scale

    def parse_rows(self, header: List[str], rows: List[List[str]], source: str) -> EnbMetrics:
        now = time.time()
        colmap: Dict[str, int] = {}
        for idx, col in enumerate(header):
            key = col.strip().strip('"').lower()
            for field, aliases in ALIASES.items():
                if key in aliases and field not in colmap:
                    colmap[field] = idx

        ues: List[UEInfo] = []
        for row in rows:
            if not row or all(not c.strip() for c in row):
                continue
            get = lambda f: row[colmap[f]].strip() if f in colmap and colmap[f] < len(row) else ""
            rnti_s = get("rnti") or get("ue_id")
            if not rnti_s:
                continue
            try:
                rnti = int(rnti_s, 0)  # handles hex like 0x4601
            except ValueError:
                continue
            def _int(f: str) -> Optional[int]:
                v = get(f)
                try:
                    return int(float(v)) if v else None
                except ValueError:
                    return None
            def _float(f: str) -> float:
                v = get(f)
                try:
                    return float(v) if v else 0.0
                except ValueError:
                    return 0.0
            ues.append(UEInfo(
                rnti=rnti,
                cqi=_int("cqi"),
                mcs_dl=_int("mcs_dl"),
                mcs_ul=_int("mcs_ul"),
                dl_bitrate_mbps=round(_float("dl_bps") * self._scale / 1e6, 3),
                ul_bitrate_mbps=round(_float("ul_bps") * self._scale / 1e6, 3),
                last_seen=now,
                state="CONNECTED",
            ))

        dl = round(sum(u.dl_bitrate_mbps for u in ues), 3)
        ul = round(sum(u.ul_bitrate_mbps for u in ues), 3)
        return EnbMetrics(ts=now, ue_count=len(ues), ues=ues,
                          dl_bitrate_mbps=dl, ul_bitrate_mbps=ul, source=source)


def _split_csv_line(line: str) -> List[str]:
    return list(csv.reader(io.StringIO(line)))[0] if line.strip() else []


class LinuxSrsranMetricsProvider:
    def __init__(self, config: AppConfig) -> None:
        self._cfg = config.linux.metrics
        self._adapter = SrsranMetricsAdapter(self._cfg.bitrate_scale)
        self._last_file_pos = 0

    def _collect_lines(self) -> List[str]:
        if self._cfg.source == "journal":
            try:
                proc = subprocess.run(
                    ["journalctl", "-u", self._cfg.journal_unit, "-n", "80", "--output", "cat"],
                    capture_output=True, text=True, timeout=10,
                )
                return [l for l in proc.stdout.splitlines() if "," in l and not l.startswith(" ")]
            except (subprocess.TimeoutExpired, OSError):
                return []
        try:
            with open(self._cfg.enb_metrics_file, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                if size < self._last_file_pos:
                    self._last_file_pos = 0  # rotated
                fh.seek(self._last_file_pos)
                data = fh.read()
                self._last_file_pos = fh.tell()
            return [l for l in data.splitlines() if l.strip()]
        except OSError:
            return []

    def get_enb_metrics(self) -> EnbMetrics:
        lines = self._collect_lines()
        header: List[str] = []
        header_idx = -1
        for i, line in enumerate(lines):
            cols = _split_csv_line(line)
            low = [c.strip().lower() for c in cols]
            if any(a in low for aliases in ALIASES.values() for a in aliases):
                header = cols
                header_idx = i
                break
        if header_idx < 0:
            return EnbMetrics(source="no-metrics")
        rows = [_split_csv_line(l) for l in lines[header_idx + 1:]]
        # keep only the most recent row per RNTI
        by_rnti: Dict[int, List[str]] = {}
        for row in rows:
            if not row:
                continue
            try:
                key = int(row[0].strip(), 0)
            except ValueError:
                continue
            by_rnti[key] = row
        return self._adapter.parse_rows(header, list(by_rnti.values()), self._cfg.source)
