import time

import requests
from config import NTFY_URL, NTFY_TOPIC

_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}
_RETRIES = 3


def notify(title: str, body: str, priority: str = "default", tags: list[str] | None = None):
    payload: dict = {
        "topic":    NTFY_TOPIC,
        "title":    title,
        "message":  body,
        "priority": _PRIORITY.get(priority, 3),
    }
    if tags:
        payload["tags"] = tags
    for attempt in range(_RETRIES):
        try:
            resp = requests.post(NTFY_URL, json=payload, timeout=5)
            resp.raise_for_status()
            return
        except Exception as e:
            if attempt < _RETRIES - 1:
                time.sleep(2 ** attempt)  # 1s, 2s
            else:
                print(f"[ntfy 오류] {_RETRIES}회 시도 실패: {e}")
