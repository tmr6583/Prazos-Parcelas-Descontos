from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import BASE_DIR


RUNTIME_LOG_PATH = BASE_DIR / "Cagoete.runtime.log"


def write_runtime_event(event: str, message: str, level: str = "INFO", **context: Any) -> Path:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level.upper(),
        "event": event,
        "message": message,
        "context": context,
    }

    RUNTIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RUNTIME_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=True) + "\n")

    return RUNTIME_LOG_PATH
