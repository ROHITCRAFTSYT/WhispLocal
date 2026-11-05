"""Rotating file logging for WhispLocal.

The app runs under pythonw.exe with no console, so whisp.log is the only
place a user (or a bug report) can see what happened. This module:

- writes to ``whisp.log`` through a size-capped RotatingFileHandler
  (``whisp.log``, ``whisp.log.1`` ... ``whisp.log.N``) so the log never
  grows without bound and the newest lines are never thrown away;
- also logs to stderr when there is one (``debug.bat`` / a console run);
- routes uncaught exceptions on the main thread and on worker threads to
  the log, which otherwise vanish silently under pythonw;
- never raises: if the log file cannot be opened (read-only folder,
  locked by another process) logging degrades to stderr / a no-op and the
  app keeps working.

Stdlib only, so it can be imported and tested anywhere.
"""
import logging
import logging.handlers
import os
import sys
import threading

LOGGER_NAME = "whisp"
LOG_FILENAME = "whisp.log"
MAX_BYTES = 1024 * 1024  # 1 MB per file
BACKUP_COUNT = 3  # whisp.log + 3 rotated files = at most ~4 MB on disk
FORMAT = "%(asctime)s  %(levelname)-7s %(threadName)s  %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_lock = threading.Lock()
_configured_path = None


def get_logger(name=None):
    """The app logger, or a child of it (``get_logger("audio")``)."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def _level_from_env(default):
    """WHISP_LOG_LEVEL=DEBUG (etc.) turns on verbose logging for a run."""
    name = os.environ.get("WHISP_LOG_LEVEL", "").strip().upper()
    level = logging.getLevelName(name) if name else default
    return level if isinstance(level, int) else default


def setup_logging(log_dir, level=logging.INFO, max_bytes=MAX_BYTES,
                  backup_count=BACKUP_COUNT, console=None,
                  install_hooks=True):
    """Configure the ``whisp`` logger to write to ``<log_dir>/whisp.log``.

    Idempotent: calling it again with the same directory is a no-op, and
    with a different directory it replaces the old handlers. Returns the
    log file path, or None when the file could not be opened.
    """
    global _configured_path
    path = os.path.join(log_dir, LOG_FILENAME)
    with _lock:
        logger = get_logger()
        if _configured_path == path and logger.handlers:
            return path
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:  # pragma: no cover - best effort
                pass
        logger.setLevel(_level_from_env(level))
        logger.propagate = False
        fmt = logging.Formatter(FORMAT, DATEFMT)

        file_ok = False
        try:
            os.makedirs(log_dir, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backup_count,
                encoding="utf-8", delay=True)
            fh.setFormatter(fmt)
            logger.addHandler(fh)
            file_ok = True
        except OSError as e:
            sys_err = getattr(sys, "stderr", None)
            if sys_err is not None:
                try:
                    print(f"WhispLocal: cannot open log file {path}: {e}",
                          file=sys_err)
                except Exception:  # pragma: no cover
                    pass

        if console is None:
            # pythonw sets sys.stderr to None; only add a console handler
            # when there is somewhere for it to write.
            console = getattr(sys, "stderr", None) is not None
        if console and getattr(sys, "stderr", None) is not None:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(fmt)
            logger.addHandler(sh)

        if not logger.handlers:
            logger.addHandler(logging.NullHandler())

        _configured_path = path if file_ok else None
    if install_hooks:
        install_exception_hooks()
    return _configured_path


def log_path():
    """Path of the active log file, or None if file logging is off."""
    return _configured_path


def install_exception_hooks():
    """Send uncaught exceptions (main thread and worker threads) to the
    log. Under pythonw they would otherwise disappear without a trace."""
    logger = get_logger()
    prev_sys_hook = sys.excepthook

    def _sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            prev_sys_hook(exc_type, exc, tb)
            return
        logger.critical("uncaught exception", exc_info=(exc_type, exc, tb))
        prev_sys_hook(exc_type, exc, tb)

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = getattr(args.thread, "name", "?")
        logger.error("uncaught exception in thread %s", name,
                     exc_info=(args.exc_type, args.exc_value,
                               args.exc_traceback))

    if not getattr(sys.excepthook, "_whisp_hook", False):
        _sys_hook._whisp_hook = True
        sys.excepthook = _sys_hook
    if not getattr(threading.excepthook, "_whisp_hook", False):
        _thread_hook._whisp_hook = True
        threading.excepthook = _thread_hook


def log_message(msg):
    """Compatibility shim for the app's historical ``log(msg)`` helper.

    Messages that carry a traceback or start with a failure word are
    logged at ERROR, the rest at INFO, so ``whisp.log`` can be filtered
    by level without touching every call site.
    """
    text = str(msg)
    head = text.split(":", 1)[0].lower()
    is_error = "Traceback (most recent call last)" in text or any(
        w in head for w in ("error", "failed", "fatal"))
    get_logger().log(logging.ERROR if is_error else logging.INFO, "%s", text)
