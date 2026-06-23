from __future__ import annotations

import json
import os
import threading
import uuid as _uuid_mod
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import unquote, urlparse

_PORT = int(os.environ.get("ATOMSPACE_API_PORT", "8081"))
_ROOT = os.environ.get(
    "OMEGACLAW_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
_TASKS_LOG   = os.path.join(_ROOT, "brands", "tasks_log.json")
_TASKS_METTA = os.path.join(_ROOT, "brands", "tasks.metta")
_CAMPAIGNS_METTA = os.path.join(_ROOT, "brands", "campaigns.metta")
print(f"[AtomSpaceAPI] ROOT={_ROOT} TASKS_METTA={_TASKS_METTA}")


def _esc_metta(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _esc_script(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace('"', '\\"')
                  .replace("\r", "").replace("\n", "\\n"))


def _unesc_script(s: str) -> str:
    import re
    return re.sub(r"\\(.)",
                  lambda m: {"n": "\n", '"': '"', "\\": "\\"}.get(m.group(1), m.group(1)),
                  s)


def _append_metta_atom(line: str) -> None:
    print(f"[tasks.metta] writing to {_TASKS_METTA}: {line}")
    try:
        existing = open(_TASKS_METTA, "r", encoding="utf-8").read() if os.path.exists(_TASKS_METTA) else ""
        if line not in existing:
            os.makedirs(os.path.dirname(_TASKS_METTA), exist_ok=True)
            with open(_TASKS_METTA, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            print(f"[tasks.metta] wrote OK")
        else:
            print(f"[tasks.metta] skipped (already exists)")
    except OSError as e:
        print(f"[tasks.metta] OSError: {e}")


def _append_campaigns_atom(line: str) -> None:
    
    try:
        existing = open(_CAMPAIGNS_METTA, "r", encoding="utf-8").read() if os.path.exists(_CAMPAIGNS_METTA) else ""
        if line not in existing:
            os.makedirs(os.path.dirname(_CAMPAIGNS_METTA), exist_ok=True)
            with open(_CAMPAIGNS_METTA, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            print(f"[campaigns.metta] wrote: {line}")
    except OSError as e:
        print(f"[campaigns.metta] OSError: {e}")



_store: dict = {
    "brands": [],
    "brand_attrs": {},
    "campaigns": {},
    "tasks": {},
    "decisions": {},     
    "scripts": {},      
}
_lock = threading.Lock()
_started = False



def clear_brand_atoms() -> None:
    
    with _lock:
        _store["brands"] = []
        _store["brand_attrs"] = {}


def _report_loaded_brands() -> None:
    
    with _lock:
        brands = list(_store["brands"])

    if brands:
        print(f"[AtomSpaceAPI] Synced {len(brands)} brand(s) from AtomSpace: "
              f"{', '.join(brands)}")
    else:
        print("[AtomSpaceAPI] No Brand atoms synced from AtomSpace")




def add_brand_atom(sym: str, attr: str, val: str) -> None:
    
    sym  = str(sym).strip()
    attr = str(attr).strip()
    val  = str(val).strip()
    if not sym or not attr:
        return
    with _lock:
        if sym not in _store["brands"]:
            _store["brands"].append(sym)
        _store["brand_attrs"].setdefault(sym, {})[attr] = val



def register_campaign_ideas(brand: str, campaign: str, ideas: list) -> None:
    
    brand    = str(brand).strip()
    campaign = str(campaign).strip()
    normalized = []
    for idea in ideas:
        if isinstance(idea, dict) and idea.get("name"):
            normalized.append({
                "name":       str(idea.get("name", "")).strip(),
                "theme":      str(idea.get("theme", "")).strip(),
                "hook":       str(idea.get("hook", "")).strip(),
                "activation": str(idea.get("activation", "")).strip(),
                "channels":   idea.get("channels", []) if isinstance(idea.get("channels"), list) else [],
            })
        elif isinstance(idea, str) and idea.strip():
            normalized.append({"name": idea.strip()})
    with _lock:
        _store["campaigns"].setdefault(brand, {})[campaign] = {"ideas": normalized}


def register_idea_decision(brand: str, campaign: str, idea: str, status: str) -> bool:
    
    brand    = str(brand).strip()
    campaign = str(campaign).strip()
    idea     = str(idea).strip()
    status   = str(status).strip().lower()
    if status not in ("approved", "rejected") or not (brand and campaign and idea):
        return False
    with _lock:
        _store["decisions"].setdefault(brand, {}).setdefault(campaign, {})[idea] = status
    atom = "ApprovedIdea" if status == "approved" else "RejectedIdea"
    _append_campaigns_atom(
        f'!(add-atom &self ({atom} {brand} "{_esc_metta(campaign)}" "{_esc_metta(idea)}"))'
    )
    return True


def register_script(brand: str, campaign: str, idea: str, script: str) -> bool:
    
    brand    = str(brand).strip()
    campaign = str(campaign).strip()
    idea     = str(idea).strip()
    script   = str(script)
    if not (brand and campaign and idea and script.strip()):
        return False
    with _lock:
        _store["scripts"].setdefault(brand, {}).setdefault(campaign, {})[idea] = script
    _append_campaigns_atom(
        f'!(add-atom &self (CampaignScript {brand} "{_esc_script(campaign)}" '
        f'"{_esc_script(idea)}" "{_esc_script(script)}"))'
    )
    return True




def _append_task_log(task: dict) -> None:
    os.makedirs(os.path.dirname(_TASKS_LOG), exist_ok=True)
    try:
        try:
            with open(_TASKS_LOG, "r", encoding="utf-8") as f:
                log = json.load(f)
        except (OSError, json.JSONDecodeError):
            log = []
        log.append(task)
        with open(_TASKS_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def post_task_api(to_agent: str, message: str) -> str:
    
    to_norm  = str(to_agent).strip()
    msg_norm = str(message).strip()
    task_id = "t" + _uuid_mod.uuid4().hex[:8]
    task = {
        "id":      task_id,
        "to":      to_norm,
        "message": msg_norm,
        "done":    False,
        "result":  "",
    }
    with _lock:
        for t in _store["tasks"].values():
            if not t["done"] and t["to"].lower() == to_norm.lower() and t["message"] == msg_norm:
                return t["id"]
        _store["tasks"][task_id] = task
    _append_task_log(dict(task))
    _append_metta_atom(f'!(add-atom &self (Task {task["to"]} {task_id} "{_esc_metta(task["message"])}"))')
    return task_id


def complete_task_api(task_id: str, result: str) -> bool:
    
    res = str(result).strip()
    with _lock:
        task = _store["tasks"].get(task_id)
        if task is None:
            return False
        task["done"]   = True
        task["result"] = res
        siblings = [
            t for t in _store["tasks"].values()
            if not t["done"]
            and t["to"].lower() == task["to"].lower()
            and t["message"] == task["message"]
        ]
        for t in siblings:
            t["done"]   = True
            t["result"] = res
    for tid in [task_id] + [t["id"] for t in siblings]:
        _write_queue_response(tid, res)
        _append_metta_atom(f'!(add-atom &self (TaskDone {tid} "{_esc_metta(res)}"))')
    return True


def _write_queue_response(task_id: str, result: str) -> None:
    
    import glob
    queue_dir = os.path.join(_ROOT, "brands", "queue")
    for meta_path in glob.glob(os.path.join(queue_dir, "meta_*.json")):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("task_id") != task_id:
            continue
        job_id = meta.get("id") or os.path.basename(meta_path)[len("meta_"):-len(".json")]
        response_path = os.path.join(queue_dir, f"{job_id}.json")
        try:
            with open(response_path, "w", encoding="utf-8") as f:
                json.dump({"done": True, "response": result}, f, ensure_ascii=False)
            print(f"[AtomSpaceAPI] Wrote response for job {job_id} (task {task_id})")
        except OSError as e:
            print(f"[AtomSpaceAPI] Failed to write queue response for job {job_id}: {e}")
        break


def get_pending_tasks_api(agent_id: str) -> list[dict]:
    
    agent_id_lower = str(agent_id).lower()
    with _lock:
        return [
            dict(t) for t in _store["tasks"].values()
            if t["to"].lower() == agent_id_lower and not t["done"]
        ]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  

    def _respond(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None: 
        parts = [p for p in urlparse(self.path).path.strip("/").split("/") if p]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond({"error": "invalid JSON"}, 400)
            return

        # POST /api/brands/{sym}/campaigns/{title}/ideas  {"ideas": [...]}
        
        if (len(parts) == 6
                and parts[:2] == ["api", "brands"]
                and parts[3] == "campaigns"
                and parts[5] == "ideas"):
            sym      = unquote(parts[2])
            campaign = unquote(parts[4])
            ideas    = data.get("ideas", [])
            if not isinstance(ideas, list):
                self._respond({"error": "'ideas' must be a list"}, 400)
                return
            register_campaign_ideas(sym, campaign, ideas)
            print(f"[AtomSpaceAPI] Registered {len(ideas)} idea(s) for {sym} / {campaign}")
            self._respond({"registered": len(ideas)}, 201)
            return

        # POST /api/brands/{sym}/campaigns/{title}/script  {"idea": "...", "script": "..."}
        if (len(parts) == 6
                and parts[:2] == ["api", "brands"]
                and parts[3] == "campaigns"
                and parts[5] == "script"):
            sym      = unquote(parts[2])
            campaign = unquote(parts[4])
            idea     = str(data.get("idea", "")).strip()
            script   = str(data.get("script", ""))
            if not register_script(sym, campaign, idea, script):
                self._respond({"error": "missing 'idea' or 'script'"}, 400)
                return
            print(f"[AtomSpaceAPI] Stored script: {sym} / {campaign} / {idea} ({len(script)} chars)")
            self._respond({"stored": True}, 201)
            return

        # POST /api/brands/{sym}/campaigns/{title}/decision  {"idea": "...", "status": "approved"|"rejected"}
        if (len(parts) == 6
                and parts[:2] == ["api", "brands"]
                and parts[3] == "campaigns"
                and parts[5] == "decision"):
            sym      = unquote(parts[2])
            campaign = unquote(parts[4])
            idea     = str(data.get("idea", "")).strip()
            status   = str(data.get("status", "")).strip().lower()
            if not register_idea_decision(sym, campaign, idea, status):
                self._respond({"error": "missing 'idea' or invalid 'status'"}, 400)
                return
            print(f"[AtomSpaceAPI] Idea {status}: {sym} / {campaign} / {idea}")
            self._respond({"sym": sym, "campaign": campaign, "idea": idea, "status": status}, 201)
            return

        # POST /api/tasks  {"to": "CDA", "message": "..."}
        if parts == ["api", "tasks"]:
            to_agent = str(data.get("to", "")).strip()
            message  = str(data.get("message", "")).strip()
            if not to_agent or not message:
                self._respond({"error": "missing 'to' or 'message'"}, 400)
                return
            task_id = post_task_api(to_agent, message)
            self._respond({"task_id": task_id}, 201)
            return

        self._respond({"error": "Not found"}, 404)

    def do_PATCH(self) -> None:  
        parts = [p for p in urlparse(self.path).path.strip("/").split("/") if p]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond({"error": "invalid JSON"}, 400)
            return

        # PATCH /api/tasks/{task_id}  {"result": "..."}
        if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
            task_id = unquote(parts[2])
            result  = str(data.get("result", "")).strip()
            ok = complete_task_api(task_id, result)
            if ok:
                self._respond({"task_id": task_id, "done": True})
            else:
                self._respond({"error": f"task '{task_id}' not found"}, 404)
            return

        self._respond({"error": "Not found"}, 404)

    def do_GET(self) -> None:  
        parts = [p for p in urlparse(self.path).path.strip("/").split("/") if p]

        with _lock:
            # GET /api/brands
            if parts == ["api", "brands"]:
                out = []
                for sym in _store["brands"]:
                    a = _store["brand_attrs"].get(sym, {})
                    out.append({
                        "sym":         sym,
                        "name":        a.get("name", sym),
                        "description": a.get("description", ""),
                        "industry":    a.get("industry", ""),
                        "price_tier":  a.get("price-tier", ""),
                        "motto":       a.get("motto", ""),
                        "tone":        a.get("tone", ""),
                    })
                self._respond(out)
                return

            # GET /api/brands/{sym}
            if len(parts) == 3 and parts[:2] == ["api", "brands"]:
                sym   = unquote(parts[2])
                attrs = _store["brand_attrs"].get(sym)
                if attrs is None:
                    self._respond({"error": f"Brand '{sym}' not found"}, 404)
                else:
                    self._respond({"sym": sym, **attrs})
                return

            # GET /api/brands/{sym}/campaigns/{title}/ideas
            if (len(parts) == 6
                    and parts[:2] == ["api", "brands"]
                    and parts[3] == "campaigns"
                    and parts[5] == "ideas"):
                sym      = unquote(parts[2])
                campaign = unquote(parts[4])
                data     = _store["campaigns"].get(sym, {}).get(campaign)
                if data is None:
                    
                    for b, camps in _store["campaigns"].items():
                        if b.lower() != sym.lower():
                            continue
                        for c, d in camps.items():
                            if c.lower() == campaign.lower():
                                data = d
                                break
                        break
                self._respond(data if data else {"ideas": []})
                return

            # GET /api/brands/{sym}/campaigns/{title}/script?idea=...  — finished
            if (len(parts) == 6
                    and parts[:2] == ["api", "brands"]
                    and parts[3] == "campaigns"
                    and parts[5] == "script"):
                from urllib.parse import parse_qs
                sym      = unquote(parts[2])
                campaign = unquote(parts[4])
                idea     = unquote(parse_qs(urlparse(self.path).query).get("idea", [""])[0])
                script   = _store["scripts"].get(sym, {}).get(campaign, {}).get(idea)
                self._respond({"script": script})
                return

            # GET /api/brands/{sym}/approvals  — operator decisions for a brand,
            if (len(parts) == 4
                    and parts[:2] == ["api", "brands"]
                    and parts[3] == "approvals"):
                sym       = unquote(parts[2])
                decisions = {c: dict(ideas) for c, ideas in _store["decisions"].get(sym, {}).items()}
                camps     = _store["campaigns"].get(sym, {})
                approved: dict = {}
                for campaign, ideas in decisions.items():
                    names = [n for n, s in ideas.items() if s == "approved"]
                    if not names:
                        continue
                    detail_map = {
                        it["name"]: it
                        for it in camps.get(campaign, {}).get("ideas", [])
                        if isinstance(it, dict) and it.get("name")
                    }
                    approved[campaign] = [detail_map.get(n, {"name": n}) for n in names]
                self._respond({"approved": approved, "decisions": decisions})
                return

            # GET /api/tasks/{agent_id}  — pending tasks for an agent
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                agent_id_lower = unquote(parts[2]).lower()
                tasks_out = [
                    dict(t) for t in _store["tasks"].values()
                    if t["to"].lower() == agent_id_lower and not t["done"]
                ]
                self._respond(tasks_out)
                return

            self._respond({"error": "Not found"}, 404)


def _restore_tasks_from_metta() -> None:
   
    import re
    print(f"[AtomSpaceAPI] restoring tasks from {_TASKS_METTA} (exists={os.path.exists(_TASKS_METTA)})")
    if not os.path.exists(_TASKS_METTA):
        return
    try:
        text = open(_TASKS_METTA, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"[AtomSpaceAPI] failed to read tasks.metta: {e}")
        return

    done_ids: set[str] = set(re.findall(r'\(TaskDone\s+(\S+)', text))
    for m in re.finditer(r'\(Task\s+(\S+)\s+(t[0-9a-f]+)\s+"((?:[^"\\]|\\.)*)"\)', text):
        to_agent, task_id, message = m.group(1), m.group(2), m.group(3)
        message = message.replace('\\"', '"').replace("\\\\", "\\")
        with _lock:
            if task_id not in _store["tasks"]:
                _store["tasks"][task_id] = {
                    "id":      task_id,
                    "to":      to_agent,
                    "message": message,
                    "done":    task_id in done_ids,
                    "result":  "",
                }
    print(f"[AtomSpaceAPI] Restored {len(_store['tasks'])} task(s) from tasks.metta")


def _restore_decisions_from_campaigns() -> None:
    
    import re
    if not os.path.exists(_CAMPAIGNS_METTA):
        return
    try:
        text = open(_CAMPAIGNS_METTA, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"[AtomSpaceAPI] failed to read campaigns.metta: {e}")
        return

    count = 0
    pattern = r'\((Approved|Rejected)Idea\s+(\S+)\s+"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"\)'
    for m in re.finditer(pattern, text):
        kind, sym, campaign, idea = m.group(1), m.group(2), m.group(3), m.group(4)
        campaign = campaign.replace('\\"', '"').replace("\\\\", "\\")
        idea     = idea.replace('\\"', '"').replace("\\\\", "\\")
        status   = "approved" if kind == "Approved" else "rejected"
        with _lock:
            _store["decisions"].setdefault(sym, {}).setdefault(campaign, {})[idea] = status
        count += 1
    print(f"[AtomSpaceAPI] Restored {count} idea decision(s) from campaigns.metta")


def _restore_scripts_from_campaigns() -> None:
   
    import re
    if not os.path.exists(_CAMPAIGNS_METTA):
        return
    try:
        text = open(_CAMPAIGNS_METTA, "r", encoding="utf-8").read()
    except OSError as e:
        print(f"[AtomSpaceAPI] failed to read campaigns.metta: {e}")
        return

    count = 0
    pattern = (r'\(CampaignScript\s+(\S+)\s+"((?:[^"\\]|\\.)*)"\s+'
               r'"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"\)')
    for m in re.finditer(pattern, text):
        sym      = m.group(1)
        campaign = _unesc_script(m.group(2))
        idea     = _unesc_script(m.group(3))
        script   = _unesc_script(m.group(4))
        with _lock:
            _store["scripts"].setdefault(sym, {}).setdefault(campaign, {})[idea] = script
        count += 1
    print(f"[AtomSpaceAPI] Restored {count} script(s) from campaigns.metta")


def start_server() -> None:
    global _started
    if _started:
        return
    _started = True
    _restore_tasks_from_metta()
    _restore_decisions_from_campaigns()
    _restore_scripts_from_campaigns()
    _report_loaded_brands()
    try:
        server = HTTPServer(("localhost", _PORT), _Handler)
    except OSError as e:
        if e.errno == 98:  
            print(f"[AtomSpaceAPI] Port {_PORT} already in use — assuming server is running")
            return
        raise
    t = threading.Thread(target=server.serve_forever, daemon=True, name="atomspace-api")
    t.start()
    print(f"[AtomSpaceAPI] http://localhost:{_PORT}/api/")


if os.environ.get("COMMCHANNEL", "").lower() == "web":
    start_server()
