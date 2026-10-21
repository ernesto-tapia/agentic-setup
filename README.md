# agentlab

A tiny, hackable harness for building **agentic loops** with **any model**.
Swap models with one line, and shape agent behaviour with plain files:

| What | Where | Format |
|---|---|---|
| **Model** | `agentlab.yaml` | provider + model name (OpenAI, Anthropic, Ollama, Groq, OpenRouter, Gemini, any OpenAI-compatible server) |
| **Agent instructions** | `agents/<name>.md` | system prompt + optional per-agent model/tools/limits |
| **Skills** | `skills/<name>/SKILL.md` | instructions the agent loads on demand (Anthropic Agent Skills format) |
| **Tools** | `tools/*.py` | Python functions with `@tool` |
| **Harness** | `agentlab.yaml` → `harness:` | max turns, allowed tools, approvals, sandbox folder |
| **Hooks** | `hooks.py` | intercept/block/log tool calls, edit the system prompt |

The core is ~600 lines of Python with two dependencies (`httpx`, `pyyaml`). Read it, break it, change it.

## Install

Requires Python 3.9+.

```bash
pip install git+https://github.com/<YOUR_USER>/agentlab.git
```

Or clone it to hack on the harness itself:

```bash
git clone https://github.com/<YOUR_USER>/agentlab.git
cd agentlab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip && pip install -e ".[dev]"
pytest
```

## Quick start

```bash
agentlab init my-agent      # scaffold a project
cd my-agent
agentlab chat               # uses the offline "mock" model: no key needed
```

Then pick a real model in `agentlab.yaml`:

```yaml
model:
  provider: ollama          # free and local: https://ollama.com, then `ollama pull llama3.1`
  name: llama3.1
```

For hosted models, copy `.env.example` to `.env` and add your key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...).

You can also switch models for one run without editing anything:

```bash
agentlab chat -m anthropic:claude-sonnet-5-5
agentlab chat -m openai:gpt-4o-mini
agentlab chat -m groq:llama-3.3-70b-versatile
agentlab run  -m ollama:qwen2.5 "summarize README.md"
```

> Tool calling needs a model that supports it. For local models, try `llama3.1`, `qwen2.5` or `mistral-nemo`.

## Commands

| Command | Does |
|---|---|
| `agentlab init [dir]` | Create a starter project |
| `agentlab chat [-a agent] [-m provider:model]` | Interactive chat (`/reset`, `/system`, `/exit`) |
| `agentlab run "task" [-a agent] [-y]` | One task, then exit (`-y` auto-approves tools) |
| `agentlab list` | Show agents, tools, skills, providers |
| `agentlab new agent\|skill\|tool NAME` | Scaffold a new one from a template |

## Customizing

### Agents: `agents/<name>.md`

```markdown
---
description: Read-only tutor
tools: [read_file, list_dir, load_skill]   # restrict tools
skills: [explain-code]                     # restrict skills
max_turns: 8
model: {provider: ollama, name: llama3.1}  # give this agent its own model
---
You are a patient programming tutor...
```

Run it with `agentlab chat -a tutor`.

### Skills: `skills/<name>/SKILL.md`

```markdown
---
name: explain-code
description: Use when the user asks what some code does.
---
1. Read the file with read_file ...
```

Only the `name` and `description` go into the system prompt. The model calls `load_skill` to get the full text when it needs it, so you can keep many skills without bloating the prompt. Put extra reference files next to `SKILL.md` and the agent can `read_file` them.

### Tools: `tools/*.py`

```python
from agentlab import tool

@tool
def get_weather(city: str, units: str = "metric") -> str:
    """Get the current weather for a city.

    Args:
        city: city name, e.g. "Lima"
        units: metric or imperial
    """
    ...
```

Type hints become the JSON schema; the docstring becomes the description. Exceptions are sent back to the model as errors so it can retry.

Built-in tools: `read_file`, `write_file`, `list_dir`, `run_shell` (confined to `harness.workdir`), plus `load_skill`.

### Harness: `agentlab.yaml`

```yaml
harness:
  max_turns: 20                      # model calls per message before stopping
  tools: "*"                         # or a list
  confirm: [run_shell, write_file]   # ask y/n/always before these
  workdir: .
  max_tool_output: 20000
```

### Hooks: `hooks.py`

```python
def before_tool(call, agent):      # return a string to block the call
def after_tool(call, result, agent):  # return a string to replace the result
def on_message(message, agent):    # after each model reply
def system_prompt(prompt, agent):  # return a modified prompt
```

The template blocks `rm -rf` and `sudo` and logs every tool call to `agentlab.log`.

## How the loop works

```
user message
   └─► model(system prompt + history + tool schemas)
          ├─ text only?  → done, print reply
          └─ tool calls? → hooks → approval → run tool → append results → ask model again
                           (repeat up to max_turns)
```

See [`src/agentlab/loop.py`](src/agentlab/loop.py). It's short.

## Adding a provider

Any OpenAI-compatible endpoint works with no code changes:

```yaml
model:
  provider: openai
  name: my-model
  base_url: http://my-server:8000/v1
  api_key_env: MY_KEY
```

For a different API style, add a class with `complete(system, messages, tools)` in [`providers.py`](src/agentlab/providers.py) and register it in `PROVIDERS`.

## Safety

Agents can run shell commands and write files. Keep `confirm:` on for `run_shell`/`write_file`, keep `workdir` pointed at a project folder, and don't use `-y` on things you care about.

## License

MIT
