
from __future__ import annotations

import json
import os
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INSTANCE = os.environ.get("OMEGACLAW_INSTANCE_ID", "")
_QUEUE_DIR = (os.path.join(_ROOT, "brands", "queue", _INSTANCE)
              if _INSTANCE else os.path.join(_ROOT, "brands", "queue"))
_IN = os.path.join(_QUEUE_DIR, "in.jsonl")
_lock = threading.Lock()

_current_job_id: str | None = None


def _cleanup_old_responses() -> None:
    try:
        for fname in os.listdir(_QUEUE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(_QUEUE_DIR, fname)
            if time.time() - os.path.getmtime(fpath) > 3600:
                os.remove(fpath)
    except FileNotFoundError:
        pass


def start_web_channel() -> None:
    os.makedirs(_QUEUE_DIR, exist_ok=True)
    if not os.path.exists(_IN):
        open(_IN, "w", encoding="utf-8").close()
    print(f"[WebChannel] Queue active — {_IN}")


def getLastMessage() -> str:
   
    global _current_job_id
    _cleanup_old_responses()
    with _lock:
        try:
            lines = open(_IN, "r", encoding="utf-8").readlines()
        except FileNotFoundError:
            return ""
        pending = [l for l in lines if l.strip()]
        if not pending:
            return ""
        line = pending[0].strip()
        with open(_IN, "w", encoding="utf-8") as f:
            f.writelines(pending[1:])
    try:
        data = json.loads(line)
        _current_job_id = data.get("job_id")
        return data.get("message", "")
    except json.JSONDecodeError:
        _current_job_id = None
        return line


def send_message(msg: str) -> str:
    
    if not _current_job_id:
        return "SEND-NO-JOB"
    out_path = os.path.join(_QUEUE_DIR, f"{_current_job_id}.json")
    with _lock:
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"job_id": _current_job_id, "response": msg, "done": True}, f, ensure_ascii=False)
        os.replace(tmp, out_path)
    return "SEND-OK"
