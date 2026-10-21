"""Command line interface: agentlab init | chat | run | list | new."""

import argparse
import shutil
import sys
from pathlib import Path

from .config import PRESETS, Project, find_project
from .providers import ProviderError

TEMPLATES = Path(__file__).parent / "templates"
# packaged without leading dots so setuptools includes them
RENAMES = {"gitignore": ".gitignore", "env.example": ".env.example"}

NEW_AGENT = """---
description: {name} agent
# Optional overrides of agentlab.yaml for this agent:
# model: {{provider: ollama, name: llama3.1}}
# tools: [read_file, list_dir, load_skill]
# skills: [explain-code]
# max_turns: 10
---
You are {name}, a helpful agent. Describe its role, rules and style here.
"""

NEW_SKILL = """---
name: {name}
description: Describe WHEN the model should use this skill (this is all it sees until it loads it).
---
# {name}

Step-by-step instructions the agent should follow when using this skill.
"""

NEW_TOOL = '''from agentlab import tool


@tool
def {name}(text: str) -> str:
    """One line saying what this tool does (the model reads this).

    Args:
        text: describe the argument
    """
    return text
'''


def get_project():
    root = find_project()
    if not root:
        sys.exit("No agentlab.yaml found here or in a parent folder. Run `agentlab init` first.")
    return Project(root)


def cmd_init(args):
    dest = Path(args.dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for src in (TEMPLATES / "project").rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        rel = src.relative_to(TEMPLATES / "project")
        target = dest / rel.parent / RENAMES.get(rel.name, rel.name)
        if target.exists() and not args.force:
            print(f"skip   {target.relative_to(dest)} (exists)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, target)
        print(f"create {target.relative_to(dest)}")
    print(f"\nDone. Next:\n  cd {args.dir}\n  edit agentlab.yaml (pick a model) and .env (API key)\n  agentlab chat")


def cmd_list(args):
    project = get_project()
    from .skills import load_skills
    from .tools import REGISTRY, load_tools_dir
    load_tools_dir(project.tools_dir)
    print(f"Project: {project.root}")
    print(f"Model:   {project.config.get('model')}")
    print("\nAgents:  " + ", ".join(project.list_agents()))
    print("Tools:   " + ", ".join(list(REGISTRY) + ["load_skill"]))
    print("Skills:")
    for s in load_skills(project.skills_dir).values():
        print(f"  - {s.name}: {s.description}")
    print("\nProviders: " + ", ".join(PRESETS))


def cmd_new(args):
    project = get_project()
    name = args.name
    if args.kind == "agent":
        path = project.agents_dir / f"{name}.md"
        content = NEW_AGENT.format(name=name)
    elif args.kind == "skill":
        path = project.skills_dir / name / "SKILL.md"
        content = NEW_SKILL.format(name=name)
    else:
        path = project.tools_dir / f"{name}.py"
        content = NEW_TOOL.format(name=name.replace("-", "_"))
    if path.exists():
        sys.exit(f"{path} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"Created {path}")


def make_agent(args):
    from .loop import Agent
    try:
        return Agent(get_project(), args.agent, args.model, auto_approve=args.yes, verbose=not args.quiet)
    except ProviderError as e:
        sys.exit(f"Error: {e}")


def cmd_run(args):
    agent = make_agent(args)
    task = " ".join(args.task) if args.task else sys.stdin.read()
    try:
        print(agent.run(task))
    except ProviderError as e:
        sys.exit(f"Error: {e}")


def cmd_chat(args):
    agent = make_agent(args)
    m = agent.model_cfg
    print(f"agentlab · agent={agent.meta['name']} · model={m['provider']}:{m.get('name')} · "
          f"tools={', '.join(t.name for t in agent.tools)}")
    print("Commands: /reset  /system  /exit\n")
    while True:
        try:
            text = input("\033[1myou>\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/reset":
            agent.messages.clear()
            print("(conversation cleared)")
            continue
        if text == "/system":
            print(agent.system_prompt())
            continue
        try:
            print(f"\033[1;32m{agent.meta['name']}>\033[0m {agent.run(text)}\n")
        except ProviderError as e:
            print(f"\033[31mError: {e}\033[0m")
        except KeyboardInterrupt:
            print("\n(interrupted)")


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentlab", description="Tiny model-agnostic agent harness.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scaffold a new agent project")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--force", action="store_true", help="overwrite existing files")
    s.set_defaults(fn=cmd_init)

    for name, fn, help_ in (("chat", cmd_chat, "interactive chat with an agent"),
                            ("run", cmd_run, "run one task and exit")):
        s = sub.add_parser(name, help=help_)
        if name == "run":
            s.add_argument("task", nargs="*", help="the task (or pipe it via stdin)")
        s.add_argument("-a", "--agent", help="agent name from agents/ (default from agentlab.yaml)")
        s.add_argument("-m", "--model", help="override model, e.g. ollama:llama3.1 or anthropic:claude-sonnet-5-5")
        s.add_argument("-y", "--yes", action="store_true", help="auto-approve all tool calls")
        s.add_argument("-q", "--quiet", action="store_true", help="hide tool call logs")
        s.set_defaults(fn=fn)

    s = sub.add_parser("list", help="show agents, tools, skills and providers")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("new", help="create a new agent, skill or tool from a template")
    s.add_argument("kind", choices=["agent", "skill", "tool"])
    s.add_argument("name")
    s.set_defaults(fn=cmd_new)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
