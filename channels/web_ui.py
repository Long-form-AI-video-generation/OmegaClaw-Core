
from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

_ROOT      = Path(__file__).resolve().parent.parent
_QUEUE_DIR = _ROOT / "brands" / "queue"
_IN        = _QUEUE_DIR / "in.jsonl"
_LOCK      = threading.Lock()
_PORT      = int(os.environ.get("WEB_UI_PORT", "8082"))
_API_BASE  = f"http://localhost:{os.environ.get('ATOMSPACE_API_PORT', '8081')}/api"

_JH_USER   = os.environ.get("JUPYTERHUB_USER", "")
_ROOT_PATH = (
    os.environ.get("WEB_STUDIO_ROOT_PATH")
    or (f"/user/{_JH_USER}/proxy/{_PORT}" if _JH_USER else "")
).rstrip("/")


def _url(path: str) -> str:
    
    return f"{_ROOT_PATH}{path}"


def _api_post_task(to_agent: str, message: str) -> str:
    
    body = json.dumps({"to": to_agent, "message": message}).encode()
    req = urllib.request.Request(
        f"{_API_BASE}/tasks",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read()).get("task_id", "unknown")
    except Exception as e:
        raise RuntimeError(f"AtomSpace API unavailable: {e}") from e


app = FastAPI(title="Brand Studio", root_path=_ROOT_PATH)



def _api(path: str) -> dict | list | None:
    
    try:
        url = f"{_API_BASE}{path}"
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def _list_brands() -> list[dict]:
    
    data = _api("/brands")
    return data if isinstance(data, list) else []


def _read_brand(sym: str) -> dict[str, str]:
    
    data = _api(f"/brands/{sym}")
    if not isinstance(data, dict) or "error" in data:
        return {}
    return {k: str(v) for k, v in data.items() if k != "sym"}


def _get_ideas(brand_sym: str, campaign_title: str) -> list[dict]:
    
    from urllib.parse import quote
    data = _api(f"/brands/{brand_sym}/campaigns/{quote(campaign_title, safe='')}/ideas")
    if isinstance(data, dict):
        raw = data.get("ideas", [])
        result = []
        for item in raw:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str) and item:
                result.append({"name": item})
        return result
    return []



def _meta_path(job_id: str) -> Path:
    return _QUEUE_DIR / f"meta_{job_id}.json"


def _response_path(job_id: str) -> Path:
    return _QUEUE_DIR / f"{job_id}.json"


def _write_job(job_id: str, meta: dict) -> None:
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = _meta_path(job_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_meta_path(job_id))


def _read_job(job_id: str) -> dict | None:
    try:
        return json.loads(_meta_path(job_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _poll_response(job_id: str) -> str | None:
    
    path = _response_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("done"):
            return data.get("response", "")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _enqueue(job_id: str, message: str) -> None:
    _QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    if not _IN.exists():
        _IN.write_text("", encoding="utf-8")
    with _LOCK:
        with _IN.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"job_id": job_id, "message": message}) + "\n")


def _extract_ideas(response: str) -> list[dict]:
    
    return [
        {"name": name.strip()}
        for name in re.findall(r"^\s+\d+\.\s+(.+)$", response, re.MULTILINE)
        if name.strip()
    ]



def _layout(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title} — Brand Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body class="bg-gray-50 min-h-screen text-gray-900">
  <header class="bg-gray-900 text-white px-8 py-4 flex items-center gap-4 shadow">
    <a href="{_url('/')}" class="text-lg font-bold tracking-tight"> Brand Studio</a>
   
  </header>
  <main class="max-w-5xl mx-auto px-6 py-10">{body}</main>
</body>
</html>"""


def _spinner(job_id: str, poll_url: str, label: str) -> str:
    return f"""
    <div id="status-{job_id}" class="text-center py-24"
         hx-get="{poll_url}" hx-trigger="every 2s" hx-swap="outerHTML">
      <div class="inline-block text-5xl mb-4 animate-spin">⚙️</div>
      <p class="text-gray-500 text-lg">{label}</p>
      <p class="text-gray-400 text-sm mt-2">OmegaClaw is working — usually 20–40 seconds.</p>
    </div>"""


def _format_script(text: str) -> str:
    """Highlight script field labels."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(
        r"^(SCENE \d+[^\n]*)",
        r'<strong class="text-indigo-700">\1</strong>',
        text, flags=re.MULTILINE,
    )
    text = re.sub(
        r"^(SCRIPT:|BRAND:|FORMAT:|CHANNELS:|CAPTION:|HASHTAGS:|VISUAL:|COPY:|CTA:)",
        r'<span class="text-indigo-500 font-semibold">\1</span>',
        text, flags=re.MULTILINE,
    )
    text = re.sub(r"^---$", '<hr class="border-gray-200 my-2">', text, flags=re.MULTILINE)
    return text


def _api_status_banner() -> str:
    if _api("/brands") is None:
        return """
        <div class="bg-yellow-50 border border-yellow-200 text-yellow-800 rounded-lg px-4 py-3 mb-6 text-sm">
          <strong>OmegaClaw is not running.</strong>
          Start OmegaClaw with <code>commchannel=web</code> to enable brand data and campaign generation.
        </div>"""
    return ""


def _page_dashboard(brands: list[dict]) -> str:
    banner = _api_status_banner()
    if not brands:
        cards = """
        <div class="text-center py-24 text-gray-400">
          
          <p class="text-lg">No brands in AtomSpace.</p>
          <p class="text-sm mt-2">Make sure OmegaClaw is running with <code>commchannel=web</code>
             and brands are loaded into the AtomSpace.</p>
        </div>"""
    else:
        def _card(b: dict) -> str:
            sym   = b.get("sym", "")
            name  = b.get("name", sym)
            desc  = b.get("description", "")
            short = desc[:100] + ("…" if len(desc) > 100 else "")
            meta  = " · ".join(filter(None, [b.get("industry", ""), b.get("price_tier", "")]))
            return f"""
            <a href="{_url(f'/brand/{sym}')}"
               class="block bg-white rounded-xl border border-gray-200 shadow-sm
                      hover:shadow-md transition p-6">
              <div class="flex items-center justify-between mb-2">
                <h2 class="text-xl font-semibold">{name}</h2>
                <span class="text-xs text-gray-400 bg-gray-100 rounded px-2 py-0.5">{sym}</span>
              </div>
              <p class="text-sm text-gray-500 mb-3">{short or "No description."}</p>
              <p class="text-xs text-gray-400">{meta}</p>
            </a>"""
        cards = (
            '<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">'
            + "".join(_card(b) for b in brands)
            + "</div>"
        )
    return _layout("Dashboard", f'{banner}<h1 class="text-3xl font-bold mb-8">Brands</h1>{cards}')


def _page_brand(sym: str, attrs: dict) -> str:
    name = attrs.get("name", sym)
    motto = attrs.get("motto", "")
    skip = {"name", "avatar", "voice-sample", "motto"}
    rows = "".join(
        f'<tr>'
        f'<td class="text-xs text-gray-400 pr-5 py-1.5 align-top capitalize whitespace-nowrap">'
        f'{k.replace("-", " ")}</td>'
        f'<td class="text-xs text-gray-700 py-1.5">{v}</td>'
        f'</tr>'
        for k, v in attrs.items()
        if v and k not in skip
    )
    return _layout(name, f"""
      <div class="flex flex-wrap items-center gap-3 mb-8">
        <a href="{_url('/')}" class="text-gray-400 hover:text-gray-600 text-sm">← Brands</a>
        <h1 class="text-3xl font-bold">{name}</h1>
        {f'<span class="text-gray-400 italic text-lg">{motto}</span>' if motto else ""}
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">

        <div class="bg-white rounded-xl border border-gray-200 p-6 h-fit">
          <p class="font-semibold text-xs uppercase tracking-wide text-gray-400 mb-3">
            Brand Identity
          </p>
          <table class="w-full"><tbody>{rows}</tbody></table>
        </div>

        <div class="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
          <p class="font-semibold text-xs uppercase tracking-wide text-gray-400 mb-4">
            Generate Campaign Ideas
          </p>
          <form method="POST" action="{_url('/campaign/start')}" class="space-y-4">
            <input type="hidden" name="brand_sym" value="{sym}">
            <div>
              <label class="block text-sm font-medium mb-1">
                Campaign Title <span class="text-red-400">*</span>
              </label>
              <input name="campaign_title" required
                     placeholder="e.g. Summer Sprint 2025"
                     class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                            focus:ring-2 focus:ring-indigo-500 outline-none">
            </div>
            <div>
              <label class="block text-sm font-medium mb-1">
                Brief
                <span class="text-gray-400 font-normal">(optional — goal, audience, tone)</span>
              </label>
              <textarea name="brief" rows="3"
                        placeholder="e.g. Goal: increase app downloads. Audience: athletes 18-35. Tone: bold."
                        class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                               focus:ring-2 focus:ring-indigo-500 outline-none resize-none"></textarea>
            </div>
            <button type="submit"
                    class="w-full bg-indigo-600 hover:bg-indigo-700 text-white
                           px-5 py-2.5 rounded-lg text-sm font-semibold transition">
              Generate Campaign Ideas →
            </button>
          </form>
        </div>

      </div>
    """)


def _page_campaign(job_id: str, job: dict, response: str | None) -> str:
    brand_sym = job.get("brand_sym", "")
    campaign_title = job.get("campaign_title", "")

    if response is None:
        content = _spinner(job_id, _url(f"/campaign/{job_id}/poll"), "Generating campaign ideas…")
    else:
        
        ideas = _get_ideas(brand_sym, campaign_title)
        
        if not ideas:
            ideas = _extract_ideas(response)

        if ideas:
            idea_cards = ""
            for idea in ideas:
                name       = idea.get("name", "") if isinstance(idea, dict) else str(idea)
                theme      = idea.get("theme", "")      if isinstance(idea, dict) else ""
                hook       = idea.get("hook", "")       if isinstance(idea, dict) else ""
                activation = idea.get("activation", "") if isinstance(idea, dict) else ""
                channels   = idea.get("channels", [])   if isinstance(idea, dict) else []
                ch_str     = ", ".join(channels) if isinstance(channels, list) else str(channels)

                name_safe = name.replace('"', "&quot;")

                
                detail_rows = ""
                if theme:
                    detail_rows += f'<p class="text-sm text-gray-600"><span class="font-medium text-gray-700">Theme:</span> {theme}</p>'
                if hook:
                    detail_rows += f'<p class="text-sm text-gray-600"><span class="font-medium text-gray-700">Hook:</span> <em>"{hook}"</em></p>'
                if activation:
                    detail_rows += f'<p class="text-sm text-gray-600"><span class="font-medium text-gray-700">Activation:</span> {activation}</p>'
                if ch_str:
                    detail_rows += f'<p class="text-sm text-gray-600"><span class="font-medium text-gray-700">Channels:</span> {ch_str}</p>'

                idea_cards += f"""
                <details class="group bg-white border border-gray-200 rounded-xl overflow-hidden
                                hover:border-indigo-300 transition open:border-indigo-400 open:shadow-md">
                  <summary class="flex items-center justify-between px-5 py-4 cursor-pointer list-none select-none">
                    <span class="font-semibold text-gray-800 group-open:text-indigo-700">{name}</span>
                    <span class="text-gray-400 text-xs transition-transform group-open:rotate-180">▼</span>
                  </summary>
                  <div class="px-5 pb-5 pt-3 border-t border-gray-100 space-y-2">
                    {detail_rows if detail_rows else '<p class="text-sm text-gray-400 italic">No additional details available.</p>'}
                    <div class="pt-3">
                      <form method="POST" action="{_url('/script/start')}">
                        <input type="hidden" name="brand_sym"       value="{brand_sym}">
                        <input type="hidden" name="campaign_title"  value="{campaign_title}">
                        <input type="hidden" name="idea_name"       value="{name_safe}">
                        <input type="hidden" name="campaign_job_id" value="{job_id}">
                        <button type="submit"
                          class="bg-indigo-600 hover:bg-indigo-700 text-white text-sm
                                 px-4 py-2 rounded-lg font-medium transition">
                          Generate Script for this Idea →
                        </button>
                      </form>
                    </div>
                  </div>
                </details>"""

            ideas_section = f"""
            <div class="space-y-3">
              <p class="text-sm text-gray-500 mb-1">
                Expand an idea to see details and generate a script.
              </p>
              {idea_cards}
            </div>"""
        else:
            
            safe = response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ideas_section = f"""
            <pre class="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed mb-6">{safe}</pre>
            <form method="POST" action="{_url('/script/start')}" class="space-y-3">
              <input type="hidden" name="brand_sym"      value="{brand_sym}">
              <input type="hidden" name="campaign_title" value="{campaign_title}">
              <input name="idea_name" required placeholder="Type the idea name"
                class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm
                       focus:ring-2 focus:ring-indigo-500 outline-none">
              <button type="submit"
                class="w-full bg-green-600 hover:bg-green-700 text-white
                       px-5 py-2 rounded-lg text-sm font-semibold transition">
                Generate Script →
              </button>
            </form>"""

        content = f"""
        <div class="bg-white rounded-xl border border-gray-200 p-6">
          <p class="font-semibold text-xs uppercase tracking-wide text-gray-400 mb-5">
            Campaign Ideas — {campaign_title}
          </p>
          {ideas_section}
        </div>"""

    return _layout(campaign_title, f"""
      <div class="flex flex-wrap items-center gap-3 mb-8">
        <a href="{_url(f'/brand/{brand_sym}')}" class="text-gray-400 hover:text-gray-600 text-sm">
          ← {brand_sym}
        </a>
        <h1 class="text-2xl font-bold">{campaign_title}</h1>
      </div>
      {content}
    """)


def _page_script(job_id: str, job: dict, response: str | None) -> str:
    brand_sym = job.get("brand_sym", "")
    campaign_title = job.get("campaign_title", "")
    idea_name = job.get("idea_name", "")
    campaign_job_id = job.get("campaign_job_id", "")

    back_href = _url(f"/campaign/{campaign_job_id}") if campaign_job_id else _url(f"/brand/{brand_sym}")
    back_label = "← Back to Ideas" if campaign_job_id else f"← {brand_sym}"

    if response is None:
        content = _spinner(job_id, _url(f"/script/{job_id}/poll"), f'Writing script for "{idea_name}"…')
    else:
        formatted = _format_script(response)
        content = f"""
        <div class="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <pre class="whitespace-pre-wrap text-sm text-gray-800 leading-relaxed font-mono">{formatted}</pre>
        </div>
        <div class="flex gap-3">
          <a href="{back_href}"
             class="px-5 py-2 rounded-lg border border-gray-300 text-sm hover:bg-gray-50 transition">
            {back_label}
          </a>
          <a href="{_url(f'/brand/{brand_sym}')}"
             class="px-5 py-2 rounded-lg border border-gray-300 text-sm hover:bg-gray-50 transition">
            ← {brand_sym}
          </a>
        </div>"""

    return _layout(f"Script: {idea_name}", f"""
      <div class="flex flex-wrap items-center gap-2 mb-8 text-sm">
        <a href="{_url(f'/brand/{brand_sym}')}" class="text-gray-400 hover:text-gray-600">← {brand_sym}</a>
        <span class="text-gray-300">/</span>
        <span class="text-gray-500">{campaign_title}</span>
        <span class="text-gray-300">/</span>
        <h1 class="text-2xl font-bold text-gray-900">{idea_name}</h1>
      </div>
      {content}
    """)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return _page_dashboard(_list_brands())


@app.get("/brand/{sym}", response_class=HTMLResponse)
def brand_page(sym: str):
    attrs = _read_brand(sym)
    if not attrs:
        api_up = _api("/brands") is not None
        msg = (
            f'Brand "<b>{sym}</b>" not found in AtomSpace.'
            if api_up else
            "OmegaClaw is not running — cannot load brand data from AtomSpace."
        )
        return HTMLResponse(
            _layout("Not found", f"""
              <p class="text-red-500 mb-4">{msg}</p>
              <a href="{_url('/')}" class="text-indigo-600 text-sm hover:underline">← Dashboard</a>
            """),
            status_code=404,
        )
    return _page_brand(sym, attrs)


@app.post("/campaign/start")
def campaign_start(
    brand_sym: str = Form(""),
    campaign_title: str = Form(""),
    brief: str = Form(""),
):
    if not brand_sym or not campaign_title.strip():
        return RedirectResponse(_url("/"), status_code=303)

    attrs = _read_brand(brand_sym)
    brand_name = attrs.get("name", brand_sym)

    job_id = uuid.uuid4().hex[:8]

    clean_brief = " ".join(brief.strip().split())  
    brief_parts = [f"Brand: {brand_name}", f"Campaign title: {campaign_title.strip()}"]
    if clean_brief:
        brief_parts.append(f"Context: {clean_brief}")
    full_brief = " | ".join(brief_parts)

    try:
        task_id = _api_post_task("CDA", full_brief)
    except RuntimeError as e:
        return HTMLResponse(
            _layout("Error", f'<p class="text-red-500">{e}</p>'
                             f'<p class="text-sm text-gray-500 mt-2">Make sure OmegaClaw (CoSA) is running.</p>'
                             f'<a href="{_url(f"/brand/{brand_sym}")}" class="text-indigo-600 text-sm">← Back</a>'),
            status_code=503,
        )

    _write_job(job_id, {
        "id": job_id,
        "type": "campaign",
        "brand_sym": brand_sym,
        "campaign_title": campaign_title.strip(),
        "task_id": task_id,
    })

    
    _enqueue(job_id, f"Task {task_id} posted to CDA for {brand_name}. Send a one-line confirmation to the operator.")

    return RedirectResponse(_url(f"/campaign/{job_id}"), status_code=303)


@app.get("/campaign/{job_id}", response_class=HTMLResponse)
def campaign_page(job_id: str):
    job = _read_job(job_id)
    if not job:
        return HTMLResponse(
            _layout("Not found", '<p class="text-red-500">Job not found.</p>'),
            status_code=404,
        )
    return _page_campaign(job_id, job, _poll_response(job_id))


@app.get("/campaign/{job_id}/poll", response_class=HTMLResponse)
def campaign_poll(job_id: str):
    job = _read_job(job_id)
    if not job:
        return HTMLResponse("")
    if _poll_response(job_id) is None:
        return HTMLResponse(_spinner(job_id, _url(f"/campaign/{job_id}/poll"), "Generating campaign ideas…"))
    return HTMLResponse(
        f'<div hx-get="{_url(f"/campaign/{job_id}")}" hx-trigger="load" hx-target="body" hx-swap="innerHTML"></div>'
    )


@app.post("/script/start")
def script_start(
    brand_sym: str = Form(""),
    campaign_title: str = Form(""),
    idea_name: str = Form(""),
    campaign_job_id: str = Form(""), 
):
    if not brand_sym or not idea_name.strip():
        return RedirectResponse(_url("/"), status_code=303)

    attrs = _read_brand(brand_sym)
    brand_name = attrs.get("name", brand_sym)

    job_id = uuid.uuid4().hex[:8]
    _write_job(job_id, {
        "id": job_id,
        "type": "script",
        "brand_sym": brand_sym,
        "campaign_title": campaign_title,
        "idea_name": idea_name.strip(),
        "campaign_job_id": campaign_job_id,
    })

    
    message = f"USER-APPROVED: call generate-script exactly once with: {brand_name} | {campaign_title} | {idea_name.strip()}"
    _enqueue(job_id, message)

    return RedirectResponse(_url(f"/script/{job_id}"), status_code=303)


@app.get("/script/{job_id}", response_class=HTMLResponse)
def script_page(job_id: str):
    job = _read_job(job_id)
    if not job:
        return HTMLResponse(
            _layout("Not found", '<p class="text-red-500">Job not found.</p>'),
            status_code=404,
        )
    return _page_script(job_id, job, _poll_response(job_id))


@app.get("/script/{job_id}/poll", response_class=HTMLResponse)
def script_poll(job_id: str):
    job = _read_job(job_id)
    if not job:
        return HTMLResponse("")
    if _poll_response(job_id) is None:
        idea_name = job.get("idea_name", "")
        return HTMLResponse(
            _spinner(job_id, _url(f"/script/{job_id}/poll"), f'Writing script for "{idea_name}"…')
        )
    return HTMLResponse(
        f'<div hx-get="{_url(f"/script/{job_id}")}" hx-trigger="load" hx-target="body" hx-swap="innerHTML"></div>'
    )


if __name__ == "__main__":
    print(f"[BrandStudio] http://localhost:{_PORT}")
    print(f"[BrandStudio] AtomSpace API: {_API_BASE}")
    print(f"[BrandStudio] Queue dir:     {_QUEUE_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=_PORT, log_level="info")
