# core/common/llm_client.py
import os
import requests
from typing import Tuple, Dict, Any

API_BASE = os.getenv("CAPGEMINI_LLM_URL", "https://api.generative.engine.capgemini.com/v2/llm/invoke")


def _extract_text(resp_json: Dict[str, Any]) -> str:
    """
    Try common shapes returned by the Capgemini gateway.
    """
    if not isinstance(resp_json, dict):
        return ""
    # top-level "content"
    if isinstance(resp_json.get("content"), str):
        return resp_json["content"].strip()
    # nested under data.{text|output|result}
    data = resp_json.get("data") or {}
    for key in ("text", "output", "result"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def capgemini_llm_io(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 512,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Call Capgemini LLM endpoint and return:
      (extracted_text, request_payload_dict, response_json_dict)
    """
    api_key = os.getenv("CAPGEMINI_API_KEY")
    if not api_key:
        raise ValueError("CAPGEMINI_API_KEY not set in environment")

    model_name = model_name or os.getenv("CAPGEMINI_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")

    payload = {
        "action": "run",
        "modelInterface": "langchain",
        "data": {
            "mode": "chain",
            "text": prompt,
            "files": [],
            "modelName": model_name,
            "provider": "bedrock",
            "systemPrompt": system_prompt or "You are a helpful assistant.",
            "modelKwargs": {
                "maxTokens": int(max_tokens),
                "temperature": float(temperature),
                "streaming": False,
                "topP": float(top_p),
            },
        },
    }

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": api_key,
    }

    r = requests.post(API_BASE, headers=headers, json=payload, timeout=90)
    r.raise_for_status()
    resp_json = r.json()
    text = _extract_text(resp_json)
    return text, payload, resp_json


def capgemini_llm(
    prompt: str,
    system_prompt: str = "",
    model_name: str | None = None,
    temperature: float = 0.2,
    top_p: float = 0.9,
    max_tokens: int = 512,
) -> str:
    """
    Convenience wrapper that only returns the extracted text.
    """
    text, _req, _resp = capgemini_llm_io(
        prompt=prompt,
        system_prompt=system_prompt,
        model_name=model_name,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )
    return text
