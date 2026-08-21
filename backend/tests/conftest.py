"""Shared test fixtures — fast-interval mock runtime."""
from __future__ import annotations

import time
from typing import Callable, Optional

import pytest

from app.config import AppConfig
from app.runtime import Runtime

API_TOKEN = "test-token-123"


def make_config(tmp_path, **overrides) -> AppConfig:
    cfg = AppConfig()
    cfg.mode = "mock"
    cfg.database.path = str(tmp_path / "test.db")
    cfg.security.api_token = API_TOKEN
    cfg.watchdog.check_interval = 0.05
    cfg.watchdog.monitor_interval = 0.05
    cfg.watchdog.auto_start = False  # tests drive the network explicitly
    cfg.watchdog.recovery_cooldown = 0.05
    cfg.watchdog.verify_delay = 0.25
    cfg.watchdog.max_recovery_attempts = 3
    # fast stage timeouts (log-evidence startup chain)
    cfg.watchdog.stages.epc_ready_timeout = 0.5
    cfg.watchdog.stages.enb_rf_timeout = 0.5
    cfg.watchdog.stages.enb_running_timeout = 0.5
    cfg.watchdog.stages.s1_ready_timeout = 0.5
    cfg.watchdog.stages.s1_reconnect_grace = 0.3
    cfg.mock.start_delay = 0.05
    cfg.mock.stop_delay = 0.02
    cfg.mock.s1_connect_delay = 0.05
    # mock log-script timing (real-log sequences at test speed)
    cfg.mock.epc_ready_delay = 0.05
    cfg.mock.enb_rf_delay = 0.05
    cfg.mock.enb_started_delay = 0.05
    cfg.mock.ue_attach_probability = 0.0  # deterministic tests
    cfg.mock.ue_detach_probability = 0.0
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


@pytest.fixture()
def config(tmp_path) -> AppConfig:
    return make_config(tmp_path)


@pytest.fixture()
def runtime(config) -> Runtime:
    rt = Runtime(config)
    rt.start()  # engine + monitor threads
    yield rt
    rt.stop()


def wait_for(predicate: Callable[[], bool], timeout: float = 5.0,
             interval: float = 0.02) -> bool:
    """Poll until predicate() is true or timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def find_event(runtime: Runtime, type: str) -> Optional[dict]:
    for record in runtime.bus.recent_events(200):
        if record.type == type:
            return record.model_dump(mode="json")
    return None
