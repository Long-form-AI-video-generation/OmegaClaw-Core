import json
import os
import re

_CAMPAIGNS_METTA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brands", "campaigns.metta",
)


def _metta_str(value: str) -> str:
    s = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
    return f'"{s}"'


def _brand_sym(brand: str) -> str:
    sym = re.sub(r"[^\w]", "_", str(brand).strip())
    return sym if sym else "Unknown"


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_instance_id() -> str:
    return os.environ.get("OMEGACLAW_INSTANCE_ID", "default") or "default"


def _resolve(relative_path: str) -> str:
    """Resolve a ./memory/... path relative to the repo root."""
    p = str(relative_path).lstrip("./")
    return os.path.join(_REPO_ROOT, p)


def read_instance_file(path: str) -> str:
    try:
        with open(_resolve(path), "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def read_instance_file_tail(path: str, max_chars: int) -> str:
    try:
        with open(_resolve(path), "r", encoding="utf-8") as f:
            content = f.read()
        try:
            n = int(max_chars)
        except (TypeError, ValueError):
            n = 30000
        return content[-n:] if len(content) > n else content
    except FileNotFoundError:
        return ""


def append_instance_history(path: str, content: str) -> str:
    resolved = _resolve(path)
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    with open(resolved, "a", encoding="utf-8") as f:
        f.write(str(content) + "\n")
    return "APPEND-FILE-SUCCESS"


def get_instance_prompt_file(instance_id: str) -> str:
    iid = str(instance_id).strip()
    if not iid or iid == "default":
        return "./memory/prompt.txt"
    return f"./memory/prompts/{iid}.txt"


def get_instance_history_file(instance_id: str) -> str:
    iid = str(instance_id).strip()
    if not iid or iid == "default":
        return "./memory/history.metta"
    return f"./memory/history/{iid}.metta"


def check_brand_existance(brief: str, timeout: int = 60) -> str:
    try:
        try:
            from lib_llm_ext import callProvider
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from lib_llm_ext import callProvider

        prompt = f"""
        You are an information extraction system for marketing briefs.
`
        Extract the following fields:
        - brand
        - campaign_title
        - audience
        - goal
        - tone

        Rules:
        - Return ONLY valid JSON.
        - Do not include markdown, explanations, or extra text.
        - Use this exact schema:
        {{
        "brand": "",
        "campaign_title": "",
        "audience": "",
        "goal": "",
        "tone": ""
        }}

        Extraction Guidelines:
        - Prefer explicitly stated information.
        - If a field is not explicitly stated, infer the most likely value from the campaign title, wording, and context.
        - Make reasonable marketing-oriented inferences when confidence is moderate or high.
        - Keep inferred values short and practical.
        - Only return an empty string if there is insufficient context to make a reasonable inference.
        - Do not hallucinate highly specific details.

        Marketing Brief:
        \"\"\"{brief}\"\"\"
        """

        try:
            from lib_llm_ext import _provider_registry
            provider_name = next(
                (name for name, p in _provider_registry.items() if p.is_available),
                "Ollama-local"
            )
        except Exception:
            provider_name = "Ollama-local"
        response = callProvider(provider_name, prompt, max_tokens=256)
        content = response.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content).strip()
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start: end + 1]
        parsed = json.loads(content)
        brand = " ".join(str(parsed.get("brand", "")).split())
        campaign_title = " ".join(str(parsed.get("campaign_title", "")).split())
        audience = " ".join(str(parsed.get("audience", "")).split())
        goal = " ".join(str(parsed.get("goal", "")).split())
        tone = " ".join(str(parsed.get("tone", "")).split())
        return f"BRAND: {brand or 'unknown'} , CAMPAIGN: {campaign_title or 'unknown'}, AUDIENCE: {audience or 'unknown'}, GOAL:{goal or 'unknown'}, TONE:{tone or 'unknown'}"
    except Exception as e:
        return f"error: {e}"


def extract_brand_from_check(check_str: str) -> str:
    m = re.search(r'BRAND:\s*([^,\n]+)', str(check_str), re.IGNORECASE)
    return m.group(1).strip() if m else ""


def str_contains(text: str, substring: str) -> str:
    return "True" if str(substring).strip().lower() in str(text).lower() else "False"


_ATOMSPACE_API = f"http://localhost:{os.environ.get('ATOMSPACE_API_PORT', '8081')}/api"


def _register_ideas_api(brand_sym: str, campaign: str, ideas: list) -> None:
    """POST generated ideas to the AtomSpace API server so the web UI sees them."""
    from urllib.request import Request, urlopen
    from urllib.parse import quote
    url = (f"{_ATOMSPACE_API}/brands/{quote(str(brand_sym), safe='')}"
           f"/campaigns/{quote(str(campaign), safe='')}/ideas")
    try:
        req = Request(
            url,
            data=json.dumps({"ideas": ideas}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5):
            pass
        print(f"[store_campaign_ideas] registered {len(ideas)} idea(s) at {url}")
    except Exception as e:
        print(f"[store_campaign_ideas] failed to register ideas with API: {e}")


def store_campaign_ideas(result_json: str) -> str:
    try:
        data = json.loads(str(result_json))
    except (json.JSONDecodeError, TypeError):
        return "()"

    brand_raw = str(data.get("brand", "unknown")).strip()
    campaign_title = str(data.get("campaign", "")).strip()
    ideas = data.get("ideas", []) if isinstance(data.get("ideas"), list) else []

    bsym = _brand_sym(brand_raw)
    ctitle = _metta_str(campaign_title)

    atoms: list[str] = []
    atoms.append(f"(BrandCampaign {bsym} {ctitle})")

    for field in ("audience", "goal", "tone"):
        val = str(data.get(field, "")).strip()
        if val and val.lower() != "unknown":
            atoms.append(f"(Campaign {bsym} {ctitle} {field} {_metta_str(val)})")

    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        idea_name = str(idea.get("name", "")).strip()
        if not idea_name:
            continue
        iname = _metta_str(idea_name)
        for attr in ("theme", "hook", "activation"):
            val = str(idea.get(attr, "")).strip()
            if val:
                atoms.append(f"(CampaignIdea {bsym} {ctitle} {iname} {attr} {_metta_str(val)})")
        channels = idea.get("channels")
        if isinstance(channels, list) and channels:
            ch_val = ", ".join(str(c) for c in channels)
            atoms.append(f"(CampaignIdea {bsym} {ctitle} {iname} channels {_metta_str(ch_val)})")

    
    full_ideas = [
        {
            "name":       str(idea.get("name", "")).strip(),
            "theme":      str(idea.get("theme", "")).strip(),
            "hook":       str(idea.get("hook", "")).strip(),
            "activation": str(idea.get("activation", "")).strip(),
            "channels":   idea.get("channels", []) if isinstance(idea.get("channels"), list) else [],
        }
        for idea in ideas
        if isinstance(idea, dict) and idea.get("name")
    ]
    if full_ideas:
        _register_ideas_api(bsym, campaign_title, full_ideas)

    marker = f"!(add-atom &self (BrandCampaign {bsym} {ctitle}))"
    existing = ""
    try:
        with open(_CAMPAIGNS_METTA, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        pass

    if marker in existing:
        return "()"

    metta_lines = [f"!(add-atom &self {a})" for a in atoms]
    try:
        with open(_CAMPAIGNS_METTA, "a", encoding="utf-8") as f:
            f.write(f"\n; Campaign: {campaign_title} | Brand: {brand_raw}\n")
            f.write("\n".join(metta_lines) + "\n")
    except Exception:
        pass

    add_calls = " ".join(f"(add-atom &self {a})" for a in atoms)
    return f"(progn {add_calls})" if atoms else "()"


def store_generated_script(brand_name, campaign, idea, script) -> str:
    
    from urllib.request import Request, urlopen
    from urllib.parse import quote
    bsym     = _brand_sym(brand_name)
    campaign = str(campaign).strip()
    idea     = str(idea).strip()
    if not (campaign and idea and str(script).strip()):
        return "STORE-SCRIPT-SKIPPED"
    url = (f"{_ATOMSPACE_API}/brands/{quote(bsym, safe='')}"
           f"/campaigns/{quote(campaign, safe='')}/script")
    try:
        req = Request(
            url,
            data=json.dumps({"idea": idea, "script": str(script)}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5):
            pass
        print(f"[store_generated_script] stored script for {bsym}/{campaign}/{idea}")
        return "STORE-SCRIPT-OK"
    except Exception as e:
        print(f"[store_generated_script] failed: {e}")
        return f"STORE-SCRIPT-FAILED: {e}"


def build_campaign_brief(brand_sym: str, check_str: str, context_attrs: str) -> str:
    brand = str(brand_sym).strip()
    check_str = str(check_str)

    if not brand or brand.lower() in {"unknown", ""}:
        m = re.search(r'BRAND:\s*([^,\n]+)', check_str, re.IGNORECASE)
        brand = m.group(1).strip() if m else "unknown"

    def extract(field: str) -> str:
        m = re.search(rf'{field}:\s*([^,\n]+)', check_str, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    context = {}
    attrs_str = str(context_attrs).strip()
    if attrs_str:
        for line in attrs_str.splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                context[k.strip()] = v.strip()

    return json.dumps({
        "company":  brand,
        "campaign": extract("CAMPAIGN"),
        "audience": extract("AUDIENCE"),
        "goal":     extract("GOAL"),
        "tone":     extract("TONE"),
        "context":  context,
    }, indent=2)


def _parse_metta_tokens(s: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(s):
        if s[i].isspace():
            i += 1
        elif s[i] == '"':
            j = i + 1
            while j < len(s):
                if s[j] == "\\":
                    j += 2
                elif s[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            tokens.append(s[i:j])
            i = j
        else:
            j = i
            while j < len(s) and not s[j].isspace():
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _read_idea_details(brand_sym: str, campaign_title: str, idea_name: str) -> dict:
    ctitle = campaign_title.strip('"')
    iname = idea_name.strip('"')
    details: dict[str, str] = {"name": iname}
    prefix = "!(add-atom &self (CampaignIdea "
    try:
        with open(_CAMPAIGNS_METTA, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith(prefix):
                    continue
                inner = line[len("!(add-atom &self ("):]
                if inner.endswith("))"):
                    inner = inner[:-2]
                elif inner.endswith(")"):
                    inner = inner[:-1]
                tokens = _parse_metta_tokens(inner)
                if len(tokens) < 6:
                    continue
                if (tokens[1] == brand_sym
                        and tokens[2].strip('"') == ctitle
                        and tokens[3].strip('"') == iname):
                    attr = tokens[4]
                    val = tokens[5].strip('"') if tokens[5].startswith('"') else tokens[5]
                    details[attr] = val
    except Exception:
        pass
    return details


def format_ideas_menu(result_json: str) -> str:
    result_json = str(result_json)
    ideas: list[str] = []
    brand = "the brand"
    campaign = ""

    try:
        data = json.loads(result_json)
        brand = str(data.get("brand", "the brand")).strip()
        campaign = str(data.get("campaign", "")).strip()
        raw = data.get("ideas", [])
        if isinstance(raw, list):
            ideas = [str(i.get("name", "")).strip() for i in raw
                     if isinstance(i, dict) and i.get("name")]
    except (json.JSONDecodeError, TypeError):
        pass

    if not ideas:
        for line in result_json.splitlines():
            m = re.match(r"IDEA:\s*([^|]+)", line, re.IGNORECASE)
            if m:
                ideas.append(m.group(1).strip())

    if not ideas:
        return (
            "Campaign ideas have been stored in AtomSpace. "
            "To generate a script, use: generate-script <brand> | <campaign title> | <idea name>"
        )

    header = (f"Campaign '{campaign}' ({brand}) — choose an idea for script generation:"
              if campaign else f"Campaign ideas for {brand}:")
    lines = [header]
    for i, name in enumerate(ideas, 1):
        lines.append(f"  {i}. {name}")
    lines.append(
        "\nReply with the idea name or number, e.g.:\n"
        f"  generate-script {brand} | {campaign} | {ideas[0]}"
    )
    return "\n".join(lines)


def parse_script_request(brief: str) -> str:
    brief = str(brief).strip()

    parts = [p.strip() for p in re.split(r"[|]", brief) if p.strip()]
    if len(parts) >= 3:
        
        brand    = parts[0].splitlines()[0].strip()
        campaign = parts[1].splitlines()[0].strip()
        idea     = parts[2].splitlines()[0].strip()
        return json.dumps({"brand": brand, "campaign": campaign, "idea": idea})

    try:
        try:
            from lib_llm_ext import callProvider
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from lib_llm_ext import callProvider

        prompt = (
            "Extract the brand name, campaign title, and idea/concept name from the text below. "
            "Return valid JSON only — no markdown, no commentary. "
            'Schema: {"brand": "", "campaign": "", "idea": ""}. '
            "Use an empty string if a field cannot be determined.\n\n"
            f"Text: {brief}"
        )
        response = callProvider("Ollama-local", prompt, max_tokens=256)
        content = response.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content).strip()
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start:end + 1]
        parsed = json.loads(content)
        return json.dumps({
            "brand":    str(parsed.get("brand", "")).strip(),
            "campaign": str(parsed.get("campaign", "")).strip(),
            "idea":     str(parsed.get("idea", "")).strip(),
        })
    except Exception:
        return json.dumps({"brand": "", "campaign": "", "idea": brief})


def extract_field_from_json(json_str: str, field: str) -> str:
    try:
        return str(json.loads(str(json_str)).get(str(field), "")).strip()
    except Exception:
        return ""


def build_script_brief(brand_name: str, campaign_title: str, idea_name: str,
                       brand_context: str) -> str:
    bsym = _brand_sym(str(brand_name).strip())
    details = _read_idea_details(bsym, campaign_title, idea_name)

    lines = [
        f"brand: {brand_name}",
        f"campaign: {campaign_title}",
        f"idea: {idea_name}",
    ]
    for key in ("theme", "hook", "activation", "channels"):
        val = details.get(key, "")
        if val:
            lines.append(f"{key}: {val}")
    ctx = str(brand_context).strip()
    if ctx:
        lines.append(f"brand_context: {ctx}")
    return "\n".join(lines)
