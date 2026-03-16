import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ACTIVITY_FILE = "data/activity.json"


def write_activity(stage: str, detail: str = "", base_dir: str = ""):
    """Write current activity to a shared JSON file."""
    path = os.path.join(base_dir, ACTIVITY_FILE) if base_dir else ACTIVITY_FILE
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        data = {
            "stage": stage,
            "detail": detail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug(f"Failed to write activity: {e}")


def read_activity(base_dir: str = "") -> dict:
    """Read current activity from the shared JSON file."""
    path = os.path.join(base_dir, ACTIVITY_FILE) if base_dir else ACTIVITY_FILE
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"stage": "idle", "detail": "", "updated_at": None}
