import collections
import json
import logging
import os
from datetime import datetime, timezone

LOG_FILE = "data/logs.jsonl"
MAX_LOG_LINES = 200


class DashboardLogHandler(logging.Handler):
    """Captures log records into a shared deque for dashboard display."""

    def __init__(self, buffer: collections.deque):
        super().__init__()
        self.buffer = buffer
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            self.handleError(record)


class SharedFileLogHandler(logging.Handler):
    """Appends log lines to a shared JSONL file for cross-process reading."""

    def __init__(self, path: str = LOG_FILE):
        super().__init__()
        self.path = path
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
        ))
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = json.dumps({"t": datetime.now(timezone.utc).isoformat(), "msg": msg})
            with open(self.path, "a") as f:
                f.write(entry + "\n")
            self._trim()
        except Exception:
            self.handleError(record)

    def _trim(self):
        """Keep file from growing unbounded."""
        try:
            with open(self.path, "r") as f:
                lines = f.readlines()
            if len(lines) > MAX_LOG_LINES * 2:
                with open(self.path, "w") as f:
                    f.writelines(lines[-MAX_LOG_LINES:])
        except Exception:
            pass


def read_shared_logs(limit: int = 50, path: str = LOG_FILE) -> list[str]:
    """Read recent log lines from the shared log file."""
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        result = []
        for line in lines[-limit:]:
            try:
                entry = json.loads(line.strip())
                result.append(entry["msg"])
            except (json.JSONDecodeError, KeyError):
                continue
        return result
    except FileNotFoundError:
        return []
