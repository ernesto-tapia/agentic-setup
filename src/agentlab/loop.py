"""The agentic loop: ask the model, run the tools it asks for, repeat."""

import importlib.util
import json
import platform
from datetime import date

from . import tools as toolmod
from .providers import make_provider
from .skills import load_skills
from .tools import REGISTRY, Tool

DIM, CYAN, YELLOW, RED, RESET = "\033[2m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"


def _load_hooks(path):
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("agentlab_user_hooks", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Agent:
    def __init__(self, project, agent_name=None, model_override=None, auto_approve=False, verbose=True):
        self.project = project
        self.meta, self.instructions = project.load_agent(agent_name)
        self.harness = project.harness(self.meta)
        self.model_cfg = project.model(self.meta, model_override)
        self.provider = make_provider(self.model_cfg)
        self.auto_approve = auto_approve
        self.verbose = verbose
        self.always_allowed = set()
        self.messages = []

        toolmod.CONTEXT["workdir"] = self.harness["workdir"]
        toolmod.load_tools_dir(project.tools_dir)
        self.skills = load_skills(project.skills_dir, self.meta.get("skills"))
        self.hooks = _load_hooks(project.hooks_file)
        self.tools = self._select_tools()

    # ------------------------------------------------------------ setup

    def _select_tools(self):
        wanted = self.harness["tools"]
        names = list(REGISTRY) if wanted in ("*", None) else list(wanted)
        selected = []
        for n in names:
            if n == "load_skill":
                continue
            if n not in REGISTRY:
                raise SystemExit(f"Tool '{n}' not found. Available: {', '.join(REGISTRY)}")
            selected.append(REGISTRY[n])
        if self.skills and (wanted in ("*", None) or "load_skill" in wanted):
            selected.append(self._skill_tool())
        return selected

    def _skill_tool(self):
        def load_skill(name: str) -> str:
            """Load the full instructions for a skill by name.

            Args:
                name: the skill name, exactly as listed in the system prompt
            """
            if name not in self.skills:
                return f"No skill named '{name}'. Available: {', '.join(self.skills)}"
            return self.skills[name].full_text()
        return Tool(load_skill)

    def system_prompt(self):
        parts = [self.instructions]
        if self.skills:
            lines = "\n".join(f"- {s.name}: {s.description}" for s in self.skills.values())
            parts.append("## Skills\nYou have these skills. When a task matches one, call `load_skill` "
                         f"to read its instructions before starting.\n{lines}")
        parts.append(f"## Environment\n- Working directory: {self.harness['workdir']}\n"
                     f"- OS: {platform.system()}\n- Date: {date.today().isoformat()}")
        prompt = "\n\n".join(parts)
        if self.hooks and hasattr(self.hooks, "system_prompt"):
            prompt = self.hooks.system_prompt(prompt, self) or prompt
        return prompt

    # ------------------------------------------------------------ loop

    def log(self, text, color=DIM):
        if self.verbose:
            print(f"{color}{text}{RESET}")

    def _approve(self, call):
        if self.auto_approve or call["name"] not in (self.harness["confirm"] or []) or call["name"] in self.always_allowed:
            return True
        args = json.dumps(call["arguments"], ensure_ascii=False)
        answer = input(f"{YELLOW}Allow {call['name']}({args[:300]})? [y]es / [n]o / [a]lways: {RESET}").strip().lower()
        if answer == "a":
            self.always_allowed.add(call["name"])
        return answer in ("y", "yes", "a")

    def _run_tool(self, call):
        if self.hooks and hasattr(self.hooks, "before_tool"):
            verdict = self.hooks.before_tool(call, self)
            if isinstance(verdict, str):
                return verdict  # hook blocked the call and returned a message
        tool = next((t for t in self.tools if t.name == call["name"]), None)
        if tool is None:
            return f"Error: unknown tool '{call['name']}'"
        if not self._approve(call):
            return "The user denied this tool call."
        try:
            result = str(tool(**call["arguments"]))
        except Exception as e:  # report errors back to the model so it can recover
            result = f"Error: {type(e).__name__}: {e}"
        if self.hooks and hasattr(self.hooks, "after_tool"):
            result = self.hooks.after_tool(call, result, self) or result
        limit = self.harness["max_tool_output"]
        if len(result) > limit:
            result = result[:limit] + f"\n... (truncated {len(result) - limit} chars)"
        return result

    def run(self, user_input):
        """Send a user message and loop until the model stops calling tools."""
        self.messages.append({"role": "user", "content": user_input})
        system = self.system_prompt()
        for turn in range(self.harness["max_turns"]):
            reply = self.provider.complete(system, self.messages, self.tools)
            self.messages.append(reply)
            if self.hooks and hasattr(self.hooks, "on_message"):
                self.hooks.on_message(reply, self)
            if not reply["tool_calls"]:
                return reply["content"]
            if reply["content"]:
                self.log(reply["content"])
            for call in reply["tool_calls"]:
                self.log(f"→ {call['name']}({json.dumps(call['arguments'], ensure_ascii=False)[:200]})", CYAN)
                result = self._run_tool(call)
                self.log("  " + result[:300].replace("\n", "\n  "))
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})
        self.log(f"Stopped after max_turns={self.harness['max_turns']}", RED)
        return reply["content"] or "(stopped: hit max_turns)"
