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
    def __init__(self, project, agent_name=None, model_override=None, auto_approve=False, verbose=True,
                 depth=0, parent=None):
        self.project = project
        self.meta, self.instructions = project.load_agent(agent_name)
        self.harness = project.harness(self.meta)
        self.model_override = model_override
        self.model_cfg = project.model(self.meta, model_override)
        self.provider = make_provider(self.model_cfg)
        self.auto_approve = auto_approve
        self.verbose = verbose
        self.depth = depth          # 0 = the agent you talk to; 1 = an agent it called; ...
        self.parent = parent
        self.prefix = "  │ " * depth
        self.always_allowed = parent.always_allowed if parent else set()
        self.messages = []
        self.subagents = {}         # agents this one has called, kept so follow-ups remember context

        toolmod.load_tools_dir(project.tools_dir)
        self.skills = load_skills(project.skills_dir, self.meta.get("skills"))
        self.hooks = _load_hooks(project.hooks_file)
        self.callable_agents = self._callable_agents()
        self.tools = self._select_tools()

    # ------------------------------------------------------------ setup

    def _select_tools(self):
        wanted = self.harness["tools"]
        names = list(REGISTRY) if wanted in ("*", None) else list(wanted)
        selected = []
        for n in names:
            if n in ("load_skill", "ask_agent"):
                continue
            if n not in REGISTRY:
                raise SystemExit(f"Tool '{n}' not found. Available: {', '.join(REGISTRY)}")
            selected.append(REGISTRY[n])
        if self.skills and (wanted in ("*", None) or "load_skill" in wanted):
            selected.append(self._skill_tool())
        if self.callable_agents and (wanted in ("*", None) or "ask_agent" in wanted):
            selected.append(self._agent_tool())
        return selected

    def _callable_agents(self):
        """Other agents this one may delegate to: frontmatter `agents:` or all others."""
        if self.depth >= self.harness["max_depth"]:
            return {}
        names = self.meta.get("agents") or [a for a in self.project.list_agents() if a != self.meta["name"]]
        return {n: self.project.load_agent(n)[0].get("description", "") for n in names}

    def _agent_tool(self):
        def ask_agent(agent: str, message: str) -> str:
            """Send a message to another agent and get its final reply. The other agent
            does not see this conversation, so include all the context it needs.

            Args:
                agent: the agent name, exactly as listed in the system prompt
                message: the task or question for that agent
            """
            if agent not in self.callable_agents:
                return f"No agent named '{agent}'. Available: {', '.join(self.callable_agents)}"
            if agent not in self.subagents:
                self.subagents[agent] = Agent(self.project, agent, self.model_override, self.auto_approve,
                                              self.verbose, depth=self.depth + 1, parent=self)
            self.log(f"── {self.meta['name']} → {agent} ──", CYAN)
            reply = self.subagents[agent].run(message)
            self.log(f"── {agent} → {self.meta['name']} ──", CYAN)
            return reply
        return Tool(ask_agent)

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
        if any(t.name == "ask_agent" for t in self.tools):
            lines = "\n".join(f"- {n}: {d}" for n, d in self.callable_agents.items())
            parts.append("## Other agents\nYou can delegate to these agents with `ask_agent`. They cannot see "
                         f"this conversation, so give them everything they need.\n{lines}")
        parts.append(f"## Environment\n- Working directory: {self.harness['workdir']}\n"
                     f"- OS: {platform.system()}\n- Date: {date.today().isoformat()}")
        prompt = "\n\n".join(parts)
        if self.hooks and hasattr(self.hooks, "system_prompt"):
            prompt = self.hooks.system_prompt(prompt, self) or prompt
        return prompt

    # ------------------------------------------------------------ loop

    def log(self, text, color=DIM):
        if self.verbose:
            text = self.prefix + text.replace("\n", "\n" + self.prefix)
            print(f"{color}{text}{RESET}")

    def _approve(self, call):
        if self.auto_approve or call["name"] not in (self.harness["confirm"] or []) or call["name"] in self.always_allowed:
            return True
        args = json.dumps(call["arguments"], ensure_ascii=False)
        who = f"[{self.meta['name']}] " if self.depth else ""
        answer = input(f"{YELLOW}{self.prefix}{who}Allow {call['name']}({args[:300]})? [y]es / [n]o / [a]lways: {RESET}").strip().lower()
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
        toolmod.CONTEXT["workdir"] = self.harness["workdir"]  # each agent may have its own workdir
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
