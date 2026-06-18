
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_API_BASE = f"http://localhost:{os.environ.get('ATOMSPACE_API_PORT', '8081')}/api"
_TASKS_METTA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brands", "tasks.metta",
)


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _append_tasks_metta(tasks: list[dict]) -> None:
    try:
        existing = open(_TASKS_METTA, "r", encoding="utf-8").read() if os.path.exists(_TASKS_METTA) else ""
        with open(_TASKS_METTA, "a", encoding="utf-8") as f:
            for t in tasks:
                line = f'!(add-atom &self (Task {t["to"]} {t["id"]} "{_esc(t["message"])}"))'
                if line not in existing:
                    f.write(line + "\n")
    except OSError:
        pass


def _append_taskdone_metta(task_id: str, result: str) -> None:
    try:
        existing = open(_TASKS_METTA, "r", encoding="utf-8").read() if os.path.exists(_TASKS_METTA) else ""
        line = f'!(add-atom &self (TaskDone {task_id} "{_esc(result)}"))'
        if line not in existing:
            with open(_TASKS_METTA, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass


def _request(method: str, path: str, body: dict | None = None) -> dict | list:
    url = f"{_API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(errors="replace")}
    except Exception as e:
        return {"error": str(e)}


def post_task(to_agent: str, message: str) -> str:
    
    result = _request("POST", "/tasks", {"to": to_agent, "message": message})
    if isinstance(result, dict) and "task_id" in result:
        task_id = result["task_id"]
        _append_tasks_metta([{"to": to_agent, "id": task_id, "message": message}])
        return task_id
    return f"error: {result}"


def get_my_pending_tasks(agent_id: str) -> str:
    
    result = _request("GET", f"/tasks/{agent_id}")
    if isinstance(result, dict) and "error" in result:
        return f"error: {result['error']}"
    if not isinstance(result, list) or len(result) == 0:
        return "NO-PENDING-TASKS"
    return "\n".join(f"{t['id']}: {t['message']}" for t in result)


def complete_task(task_id: str, result: str) -> str:
    
    resp = _request("PATCH", f"/tasks/{task_id}", {"result": result})
    if isinstance(resp, dict) and resp.get("done"):
        _append_taskdone_metta(task_id, result)
        return f"(TaskDone {task_id})"
    return f"error: {resp}"


def post_task_summary(to_agent, message) -> str:
    
    tid = post_task(str(to_agent), str(message))
    if tid.startswith("error"):
        return f"POST-TASK-FAILED: {tid}"
    return f"Task {tid} posted to {to_agent}"


def complete_task_summary(task_id, result) -> str:
    
    resp = complete_task(str(task_id), str(result))
    if resp.startswith("error"):
        return f"COMPLETE-TASK-FAILED for {task_id}: {resp}"
    return f"Task {task_id} completed"


def get_pending_tasks_as_metta(agent_id=None) -> str:
    
    resolved_id = os.environ.get("OMEGACLAW_INSTANCE_ID", "default") or "default"
    result = _request("GET", f"/tasks/{resolved_id}")
    print(f"[check-my-tasks] agent={resolved_id} api={_API_BASE} response={result}")
    if isinstance(result, dict) and "error" in result:
        return f"TASK-API-ERROR: {result['error']}"
    if not isinstance(result, list) or len(result) == 0:
        return "NO-TASKS"

    
    unique: dict[str, dict] = {}
    for t in result:
        unique.setdefault(t["message"], t)
    tasks = list(unique.values())[:3]

    summary = " ||| ".join(f'TASK_ID={t["id"]} MSG={t["message"]}' for t in tasks)
    print(f"[check-my-tasks] returning {len(tasks)} unique of {len(result)} pending task(s)")
    return summary
