import asyncio
import json
import os
import re
from typing import Any

from uagents import Model
from uagents.query import send_sync_message
from uagents.resolver import RulesBasedResolver

TECHNICAL_ANALYSIS_AGENT_ADDRESS = os.environ.get(
    "TECHNICAL_ANALYSIS_AGENT_ADDRESS",
    "agent1q085746wlr3u2uh4fmwqplude8e0w6fhrmqgsnlp49weawef3ahlutypvu6",
)
TAVILY_SEARCH_AGENT_ADDRESS = os.environ.get(
    "TAVILY_SEARCH_AGENT_ADDRESS",
    "agent1qt5uffgp0l3h9mqed8zh8vy5vs374jl2f8y0mjjvqm44axqseejqzmzx9v8",
)
CAMPAIGN_IDEAS_AGENT_ADDRESS = os.environ.get("CAMPAIGN_IDEAS_AGENT_ADDRESS", "")
CAMPAIGN_IDEAS_AGENT_ENDPOINT = (
    os.environ.get("CAMPAIGN_IDEAS_AGENT_ENDPOINT")
    or os.environ.get("CAMPAIGN_IDEAS_AGENT_ENDPOINTS", "http://127.0.0.1:8010/submit")
    .split(",")[0]
    .strip()
)


class WebSearchRequest(Model):
    query: str


class TechAnalysisRequest(Model):
    ticker: str


class CampaignIdeasRequest(Model):
    brief: str


class CampaignIdeasResponse(Model):
    result: str


def _truncate_text(value: Any, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _format_tavily_results(response: str, max_results: int = 5) -> str:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return response

    if not isinstance(data, dict):
        return response

    results = data.get("results")
    if not isinstance(results, list):
        return response

    formatted = []
    for result in results[:max_results]:
        if not isinstance(result, dict):
            continue

        title = _truncate_text(result.get("title", ""), 160)
        url = _truncate_text(result.get("url", ""), 240)
        snippet = _truncate_text(result.get("content", ""), 400)

        parts = []
        if title:
            parts.append(f"TITLE: {title}")
        if url:
            parts.append(f"URL: {url}")
        if snippet:
            parts.append(f"SNIPPET: {snippet}")

        if parts:
            formatted.append(f"({' '.join(parts)})")

    return f"({' '.join(formatted)})" if formatted else response

async def _ask_agent(
    destination: str,
    request: Model,
    timeout: int = 60,
    response_type: type[Model] | None = None,
    resolver: RulesBasedResolver | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"destination": destination, "message": request, "timeout": timeout}
    if response_type is not None:
        kwargs["response_type"] = response_type
    if resolver is not None:
        kwargs["resolver"] = resolver
    return await send_sync_message(**kwargs)


def technical_analysis(ticker: str, timeout: int = 60) -> str:
    try:
        request = TechAnalysisRequest(ticker=ticker)
        return asyncio.run(
            _ask_agent(TECHNICAL_ANALYSIS_AGENT_ADDRESS, request, int(timeout))
        )
    except Exception as e:
        return f"error: {e}"


def tavily_search(search_query: str, timeout: int = 60) -> str:
    try:
        request = WebSearchRequest(query=search_query)
        response = asyncio.run(
            _ask_agent(TAVILY_SEARCH_AGENT_ADDRESS, request, int(timeout))
        )
        return _format_tavily_results(response)
    except Exception as e:
        return f"error: {e}"

def campaign_ideas(brief: str, timeout: int = 60) -> str:
    if not CAMPAIGN_IDEAS_AGENT_ADDRESS:
        return (
            "error: CAMPAIGN_IDEAS_AGENT_ADDRESS is not set. "
            "Start agents/campaign_generator/agent.py and export its printed address."
        )

    try:
        request = CampaignIdeasRequest(brief=brief)
        resolver = RulesBasedResolver(
            {CAMPAIGN_IDEAS_AGENT_ADDRESS: CAMPAIGN_IDEAS_AGENT_ENDPOINT}
        )
        response = asyncio.run(
            _ask_agent(
                CAMPAIGN_IDEAS_AGENT_ADDRESS,
                request,
                int(timeout),
                response_type=CampaignIdeasResponse,
                resolver=resolver,
            )
        )
        if isinstance(response, CampaignIdeasResponse):
            return response.result
        return str(response)
    except Exception as e:
        return f"error: {e}"

def check_brand_existance(brief: str, timeout: int = 60) -> str:
    try:
        try:
            from lib_llm_ext import callProvider
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from lib_llm_ext import callProvider

        prompt = (
            "Extract the brand name and campaign title from the text below. "
            "Return valid JSON only — no markdown, no commentary. "
            'Schema: {"brand": "", "campaign_title": ""}. '
            "Use an empty string if you cannot determine a field.\n\n"
            f"Text: {brief}"
        )
        response = callProvider("Ollama-local", prompt, max_tokens=256)
        content = response.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
            content = re.sub(r"\s*```$", "", content).strip()
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            content = content[start : end + 1]
        parsed = json.loads(content)
        brand = " ".join(str(parsed.get("brand", "")).split())
        campaign_title = " ".join(str(parsed.get("campaign_title", "")).split())
        return f"BRAND: {brand or 'unknown'} , CAMPAIGN: {campaign_title or 'unknown'}"
    except Exception as e:
        return f"error: {e}"


def build_campaign_brief(brand_sym: str, check_str: str, context_attrs: str) -> str:
    """Build the structured brief for the campaign agent.

    brand_sym:     brand symbol from atomspace (e.g. "Tesla"), or "" if not found
    check_str:     "BRAND: Tesla , CAMPAIGN: fast car campaign"
    context_attrs: newline-separated "attr: val" string from get-brand-context, or ""
    """
    brand = str(brand_sym).strip()
    check_str = str(check_str)

    if not brand or brand.lower() in {"unknown", ""}:
        m = re.search(r'BRAND:\s*([^,\n]+)', check_str, re.IGNORECASE)
        brand = m.group(1).strip() if m else "unknown"

    m = re.search(r'CAMPAIGN:\s*([^,\n]+)', check_str, re.IGNORECASE)
    campaign = m.group(1).strip() if m else ""

    context_json = "{}"
    attrs_str = str(context_attrs).strip()
    if attrs_str:
        attrs: dict[str, str] = {}
        for line in attrs_str.splitlines():
            if ": " in line:
                k, v = line.split(": ", 1)
                attrs[k.strip()] = v.strip()
        if attrs:
            context_json = json.dumps(attrs)

    lines = [f"company: {brand}"]
    if campaign and campaign.lower() != "unknown":
        lines.append(f"campaign: {campaign}")
    lines.append(f"context: {context_json}")
    return "\n".join(lines)
        