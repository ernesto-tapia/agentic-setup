"""Loading agentlab.yaml, agent files, .env, and model presets."""

import os
from pathlib import Path

import yaml

CONFIG_NAME = "agentlab.yaml"

# Provider presets. "api" picks the wire format; everything OpenAI-compatible
# shares one implementation. Add your own here or override base_url in config.
PRESETS = {
    "openai":     {"api": "openai",    "base_url": "https://api.openai.com/v1",                               "api_key_env": "OPENAI_API_KEY"},
    "anthropic":  {"api": "anthropic", "base_url": "https://api.anthropic.com/v1",                            "api_key_env": "ANTHROPIC_API_KEY"},
    "ollama":     {"api": "openai",    "base_url": "http://localhost:11434/v1",                               "api_key_env": None},
    "lmstudio":   {"api": "openai",    "base_url": "http://localhost:1234/v1",                                "api_key_env": None},
    "groq":       {"api": "openai",    "base_url": "https://api.groq.com/openai/v1",                          "api_key_env": "GROQ_API_KEY"},
    "openrouter": {"api": "openai",    "base_url": "https://openrouter.ai/api/v1",                            "api_key_env": "OPENROUTER_API_KEY"},
    "gemini":     {"api": "openai",    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    "deepseek":   {"api": "openai",    "base_url": "https://api.deepseek.com/v1",                             "api_key_env": "DEEPSEEK_API_KEY"},
    "mistral":    {"api": "openai",    "base_url": "https://api.mistral.ai/v1",                               "api_key_env": "MISTRAL_API_KEY"},
    "together":   {"api": "openai",    "base_url": "https://api.together.xyz/v1",                             "api_key_env": "TOGETHER_API_KEY"},
    "mock":       {"api": "mock",      "base_url": None,                                                      "api_key_env": None},
}

DEFAULT_HARNESS = {
    "max_turns": 20,
    "tools": "*",
    "confirm": ["run_shell", "write_file"],
    "workdir": ".",
    "max_tool_output": 20000,
    "max_depth": 2,   # how deep agents may call agents (stops A → B → A → B ... loops)
}


def find_project(start=None):
    """Walk up from `start` looking for agentlab.yaml."""
    path = Path(start or os.getcwd()).resolve()
    for p in [path, *path.parents]:
        if (p / CONFIG_NAME).exists():
            return p
    return None


def load_dotenv(path):
    """Minimal .env loader: KEY=value lines; existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parse_frontmatter(text):
    """Split a markdown file with optional YAML frontmatter into (meta, body)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return yaml.safe_load(parts[1]) or {}, parts[2].strip()
    return {}, text.strip()


def resolve_model(model_cfg, override=None):
    """Merge a model config with its provider preset.

    `override` is a "provider:model" string from the CLI, e.g. "ollama:llama3.1".
    """
    cfg = dict(model_cfg or {})
    if override:
        provider, _, name = override.partition(":")
        if provider not in PRESETS:
            raise SystemExit(f"Unknown provider '{provider}'. Options: {', '.join(PRESETS)}")
        if provider != cfg.get("provider"):
            # switching providers: drop provider-specific settings
            cfg = {k: v for k, v in cfg.items() if k not in ("base_url", "api_key_env", "api")}
        cfg["provider"] = provider
        if name:
            cfg["name"] = name
    provider = cfg.get("provider", "openai")
    if provider not in PRESETS:
        raise SystemExit(f"Unknown provider '{provider}'. Options: {', '.join(PRESETS)}")
    merged = {**PRESETS[provider], **cfg}
    merged["provider"] = provider
    return merged


class Project:
    def __init__(self, root):
        self.root = Path(root)
        load_dotenv(self.root / ".env")
        self.config = yaml.safe_load((self.root / CONFIG_NAME).read_text()) or {}
        self.agents_dir = self.root / self.config.get("agents_dir", "agents")
        self.skills_dir = self.root / self.config.get("skills_dir", "skills")
        self.tools_dir = self.root / self.config.get("tools_dir", "tools")
        self.hooks_file = self.root / self.config.get("hooks_file", "hooks.py")

    def list_agents(self):
        return sorted(p.stem for p in self.agents_dir.glob("*.md"))

    def load_agent(self, name=None):
        """Return (meta, system_prompt) for an agent file in agents/."""
        name = name or self.config.get("agent", "default")
        path = self.agents_dir / f"{name}.md"
        if not path.exists():
            raise SystemExit(f"Agent '{name}' not found in {self.agents_dir}. Available: {', '.join(self.list_agents())}")
        meta, body = parse_frontmatter(path.read_text())
        meta.setdefault("name", name)
        return meta, body

    def harness(self, agent_meta):
        """Global harness settings with per-agent overrides from frontmatter."""
        h = {**DEFAULT_HARNESS, **(self.config.get("harness") or {})}
        for key in DEFAULT_HARNESS:
            if key in agent_meta:
                h[key] = agent_meta[key]
        h["workdir"] = str((self.root / h["workdir"]).resolve())
        return h

    def model(self, agent_meta, override=None):
        base = dict(self.config.get("model") or {})
        base.update(agent_meta.get("model") or {})
        return resolve_model(base, override)
