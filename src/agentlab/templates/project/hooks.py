"""Optional hooks into the agent loop. Delete any function you don't need.

Each receives the running `agent` (agent.messages, agent.harness, agent.model_cfg, ...).
"""

import json
from datetime import datetime

BLOCKED = ["rm -rf", "sudo ", "git push --force"]


def before_tool(call, agent):
    """Runs before every tool call. Return a string to block the call
    (the string is sent to the model as the tool result)."""
    if call["name"] == "run_shell":
        cmd = call["arguments"].get("command", "")
        if any(b in cmd for b in BLOCKED):
            return f"Blocked by hooks.py: '{cmd}' is not allowed."
    return None


def after_tool(call, result, agent):
    """Runs after every tool call. Return a new string to replace the result."""
    with open(agent.project.root / "agentlab.log", "a") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(), "tool": call["name"],
                            "args": call["arguments"], "result": result[:500]}) + "\n")
    return None


def on_message(message, agent):
    """Runs after every model reply (e.g. to count turns or log costs)."""


def system_prompt(prompt, agent):
    """Return a modified system prompt (or None to keep it)."""
    return None
