"""
Timestamped run log directories and session-scoped file logging.

``begin_run`` creates ``logs/<UTC-timestamp>_<label>/`` with ``run.txt``, records the
active directory in a :class:`contextvars.ContextVar`, and attaches a
``session.log`` :class:`logging.FileHandler` to the root logger so INFO (and above)
from any module is copied to that file for the rest of the run.
"""

from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import config

_write_lock = threading.Lock()

_ACTIVE_RUN_DIR: ContextVar[Optional[Path]] = ContextVar(
    "osrsbox_run_log_dir", default=None
)

# Root logger handlers we add per run (removed on the next begin_run).
_RUN_SESSION_HANDLER_ATTR = "_osrsbox_run_session_handler"


def _detach_run_session_handlers() -> None:
    root = logging.getLogger()
    to_remove = [
        h for h in root.handlers if getattr(h, _RUN_SESSION_HANDLER_ATTR, False)
    ]
    for h in to_remove:
        root.removeHandler(h)
        try:
            h.close()
        except OSError:
            pass


def _attach_run_session_handler(run_dir: Path) -> None:
    """Append one UTF-8 file handler on the root logger for this run."""
    path = run_dir / "session.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    setattr(handler, _RUN_SESSION_HANDLER_ATTR, True)
    root = logging.getLogger()
    # Ensure INFO from library code reaches the session file.
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    root.addHandler(handler)


def begin_run(label: str) -> Path:
    """Create a new log directory for this run, set context, and log to session.log.

    :param label: Short name for the folder suffix (e.g. ``items_database``).
    :return: Path to the new run directory.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label).strip("_")
    if not safe:
        safe = "build"
    root = config.PROJECT_ROOT_PATH / "logs"
    path = root / f"{ts}_{safe}"
    with _write_lock:
        root.mkdir(parents=True, exist_ok=True)
        path.mkdir(parents=True, exist_ok=True)
        (path / "run.txt").write_text(
            f"started_utc={datetime.now(timezone.utc).isoformat()}\n"
            f"label={label}\n",
            encoding="utf-8",
        )
        _detach_run_session_handlers()
        _attach_run_session_handler(path)
    _ACTIVE_RUN_DIR.set(path)
    logging.getLogger("builders.run_log").info("Run log directory: %s", path)
    return path


def current_run_dir() -> Optional[Path]:
    """Return the active run log directory, if any."""
    return _ACTIVE_RUN_DIR.get()
