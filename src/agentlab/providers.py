"""Model providers.

Internally every conversation uses one simple message format:

    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "...", "tool_calls": [{"id", "name", "arguments": {...}}]}
    {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}

Each provider converts to/from its own wire format. To add a new API style,
write a class with `complete(system, messages, tools) -> assistant message`
and register it in PROVIDERS at the bottom.
"""

import json
import os
import sys
import time
import uuid

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504, 529}


class ProviderError(Exception):
    pass


def _retry_after(response):
    """Seconds the server asked us to wait, if it said (capped at 60)."""
    try:
        return min(float(response.headers.get("retry-after")), 60)
    except (AttributeError, TypeError, ValueError):
        return None


class BaseProvider:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = cfg.get("name")
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        key_env = cfg.get("api_key_env")
        self.api_key = cfg.get("api_key") or (os.environ.get(key_env) if key_env else None)
        if key_env and not self.api_key:
            raise ProviderError(f"Missing API key: set {key_env} in your environment or .env file")
        self.timeout = cfg.get("timeout", 120)

    def _post(self, url, headers, body):
        """POST with retries on rate limits (429) and overloaded servers (5xx)."""
        retries = self.cfg.get("retries", 4)
        for attempt in range(retries + 1):
            try:
                r = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
            except httpx.HTTPError as e:
                if attempt == retries:
                    raise ProviderError(f"Request to {url} failed: {e}") from e
                r = None
            if r is not None and r.status_code not in RETRY_STATUS:
                break
            if attempt == retries:
                break
            wait = _retry_after(r) or min(2 ** (attempt + 1), 30)
            reason = f"{r.status_code}" if r is not None else "network error"
            print(f"\033[2m({reason}: model busy, retrying in {wait:.0f}s, attempt {attempt + 1}/{retries})\033[0m",
                  file=sys.stderr)
            time.sleep(wait)
        if r.status_code >= 400:
            raise ProviderError(f"{r.status_code} from {url}: {r.text[:1000]}")
        return r.json()


class OpenAICompatProvider(BaseProvider):
    """Works with OpenAI, Ollama, LM Studio, Groq, OpenRouter, Gemini, vLLM, ..."""

    def complete(self, system, messages, tools):
        wire = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {"id": tc["id"], "type": "function",
                         "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                        for tc in m["tool_calls"]
                    ]
                wire.append(msg)
            elif m["role"] == "tool":
                wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
            else:
                wire.append({"role": m["role"], "content": m["content"]})

        body = {"model": self.model, "messages": wire}
        if tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
        for key in ("temperature", "max_tokens"):
            if self.cfg.get(key) is not None:
                body[key] = self.cfg[key]
        body.update(self.cfg.get("extra") or {})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = self._post(f"{self.base_url}/chat/completions", headers, body)

        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise ProviderError(f"Unexpected response: {str(data)[:1000]}")
        calls = []
        for tc in msg.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append({"id": tc.get("id") or uuid.uuid4().hex[:12], "name": tc["function"]["name"], "arguments": args})
        return {"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls}


class AnthropicProvider(BaseProvider):
    """Native Anthropic Messages API."""

    def complete(self, system, messages, tools):
        wire = []
        for m in messages:
            if m["role"] == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
                wire.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                # consecutive tool results must share one user turn
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})
            else:
                wire.append({"role": "user", "content": m["content"]})

        body = {"model": self.model, "system": system, "messages": wire,
                "max_tokens": self.cfg.get("max_tokens") or 4096}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        if self.cfg.get("temperature") is not None:
            body["temperature"] = self.cfg["temperature"]
        body.update(self.cfg.get("extra") or {})

        headers = {"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        data = self._post(f"{self.base_url}/messages", headers, body)

        text, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                text.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append({"id": block["id"], "name": block["name"], "arguments": block.get("input") or {}})
        return {"role": "assistant", "content": "\n".join(text), "tool_calls": calls}


class MockProvider(BaseProvider):
    """Offline fake model for testing your harness without an API key.

    Calls the first available tool once (list_dir if present), then replies.
    """

    def complete(self, system, messages, tools):
        last = messages[-1]
        if last["role"] == "user" and tools:
            t = next((t for t in tools if t.name == "list_dir"), tools[0])
            args = {"path": "."} if t.name == "list_dir" else {}
            return {"role": "assistant", "content": f"(mock) calling {t.name}",
                    "tool_calls": [{"id": uuid.uuid4().hex[:12], "name": t.name, "arguments": args}]}
        if last["role"] == "tool":
            return {"role": "assistant", "content": f"(mock) Tool {last['name']} returned:\n{last['content'][:500]}", "tool_calls": []}
        return {"role": "assistant", "content": f"(mock) You said: {last['content']}", "tool_calls": []}


PROVIDERS = {
    "openai": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "mock": MockProvider,
}


def make_provider(cfg):
    api = cfg.get("api", "openai")
    if api not in PROVIDERS:
        raise ProviderError(f"Unknown api '{api}'. Options: {', '.join(PROVIDERS)}")
    return PROVIDERS[api](cfg)
