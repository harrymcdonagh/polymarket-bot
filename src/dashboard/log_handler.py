import logging
import collections


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
