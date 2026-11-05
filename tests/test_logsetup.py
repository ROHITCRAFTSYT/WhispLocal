"""Rotating file logging: writes to whisp.log, rotates at the size cap,
keeps a bounded number of backups, survives an unwritable folder, and
routes uncaught thread exceptions to the log. Stdlib only."""
import logging
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "whisp"))

import logsetup  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    logger = logsetup.get_logger()
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
    logsetup._configured_path = None


def _flush():
    for h in logsetup.get_logger().handlers:
        h.flush()


def test_writes_to_whisp_log(tmp_path):
    path = logsetup.setup_logging(str(tmp_path), console=False,
                                  install_hooks=False)
    assert path == str(tmp_path / "whisp.log")
    logsetup.get_logger("audio").info("hello %s", "world")
    _flush()
    text = (tmp_path / "whisp.log").read_text(encoding="utf-8")
    assert "hello world" in text and "INFO" in text


def test_rotates_and_caps_backups(tmp_path):
    logsetup.setup_logging(str(tmp_path), max_bytes=2000, backup_count=2,
                           console=False, install_hooks=False)
    log = logsetup.get_logger()
    for i in range(400):
        log.info("line %04d %s", i, "x" * 40)
    _flush()
    names = sorted(os.listdir(tmp_path))
    assert names == ["whisp.log", "whisp.log.1", "whisp.log.2"]
    for n in names:
        assert os.path.getsize(tmp_path / n) <= 2000 + 200
    # Newest lines are in the live file, never discarded.
    assert "line 0399" in (tmp_path / "whisp.log").read_text(encoding="utf-8")


def test_setup_is_idempotent(tmp_path):
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=False)
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=False)
    assert len(logsetup.get_logger().handlers) == 1


def test_unwritable_dir_degrades_without_raising(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise PermissionError("denied")
    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", boom)
    path = logsetup.setup_logging(str(tmp_path), console=False,
                                  install_hooks=False)
    assert path is None
    logsetup.get_logger().error("still fine")  # must not raise


def test_no_console_handler_under_pythonw(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    logsetup.setup_logging(str(tmp_path), install_hooks=False)
    kinds = [type(h).__name__ for h in logsetup.get_logger().handlers]
    assert kinds == ["RotatingFileHandler"]


def test_env_var_sets_level(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISP_LOG_LEVEL", "debug")
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=False)
    assert logsetup.get_logger().level == logging.DEBUG


def test_bad_env_level_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("WHISP_LOG_LEVEL", "LOUD")
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=False)
    assert logsetup.get_logger().level == logging.INFO


@pytest.mark.parametrize("msg,level", [
    ("config applied", "INFO"),
    ("model load failed: boom", "ERROR"),
    ("pipeline error: x", "ERROR"),
    ("fatal: y", "ERROR"),
    ("command: 'open chrome' -> True 'Opening'", "INFO"),
    ("x\nTraceback (most recent call last):\n  ...", "ERROR"),
])
def test_log_message_levels(tmp_path, msg, level):
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=False)
    logsetup.log_message(msg)
    _flush()
    line = (tmp_path / "whisp.log").read_text(encoding="utf-8").splitlines()[0]
    assert level in line


def test_thread_exceptions_reach_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    logsetup.setup_logging(str(tmp_path), console=False, install_hooks=True)

    def worker():
        raise ValueError("kaboom in worker")

    t = threading.Thread(target=worker, name="mic-scan")
    t.start()
    t.join()
    _flush()
    text = (tmp_path / "whisp.log").read_text(encoding="utf-8")
    assert "uncaught exception in thread mic-scan" in text
    assert "ValueError: kaboom in worker" in text


def test_hooks_install_once(monkeypatch):
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    logsetup.install_exception_hooks()
    first = threading.excepthook
    logsetup.install_exception_hooks()
    assert threading.excepthook is first
