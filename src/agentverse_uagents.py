import asyncio
import json
import os
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
SCRIPT_GENERATOR_AGENT_ADDRESS = (
    os.environ.get("SCRIPT_GENERATOR_AGENT_ADDRESS")
    or os.environ.get("CAMPAIGN_IDEAS_AGENT_ADDRESS", "")
)
SCRIPT_GENERATOR_AGENT_ENDPOINT = (
    os.environ.get("SCRIPT_GENERATOR_AGENT_ENDPOINT")
    or os.environ.get("SCRIPT_GENERATOR_AGENT_ENDPOINTS")
    or CAMPAIGN_IDEAS_AGENT_ENDPOINT
)


class WebSearchRequest(Model):
    query: str


class TechAnalysisRequest(Model):
    ticker: str


class CampaignIdeasRequest(Model):
    brief: str


class CampaignIdeasResponse(Model):
    result: str


class ScriptGeneratorRequest(Model):
    brief: str


class ScriptGeneratorResponse(Model):
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
        
        if isinstance(response, str):
            try:
                data = json.loads(response)
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                return response
            except json.JSONDecodeError:
                return response
        return f"error: unexpected response type {type(response).__name__}: {response}"
    except Exception as e:
        return f"error: {e}"


def generate_script(brief: str, timeout: int = 90) -> str:
    if not SCRIPT_GENERATOR_AGENT_ADDRESS:
        return (
            "error: CAMPAIGN_IDEAS_AGENT_ADDRESS is not set. "
            "Start agents/campaign_generator/agent.py and export both printed addresses."
        )
    try:
        request = ScriptGeneratorRequest(brief=brief)
        resolver = RulesBasedResolver(
            {SCRIPT_GENERATOR_AGENT_ADDRESS: SCRIPT_GENERATOR_AGENT_ENDPOINT}
        )
        response = asyncio.run(
            _ask_agent(
                SCRIPT_GENERATOR_AGENT_ADDRESS,
                request,
                int(timeout),
                response_type=ScriptGeneratorResponse,
                resolver=resolver,
            )
        )
        if isinstance(response, ScriptGeneratorResponse):
            return response.result
        if isinstance(response, str):
            try:
                data = json.loads(response)
                if isinstance(data, dict) and "result" in data:
                    return data["result"]
                return response
            except json.JSONDecodeError:
                return response
        return f"error: unexpected response type {type(response).__name__}: {response}"
    except Exception as e:
        return f"error: {e}"
