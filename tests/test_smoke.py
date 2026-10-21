"""Offline end-to-end test using the mock provider."""

from agentlab.cli import main
from agentlab.config import Project, resolve_model
from agentlab.loop import Agent
from agentlab.tools import Tool


def test_init_and_run_with_mock(tmp_path, monkeypatch):
    main(["init", str(tmp_path)])
    assert (tmp_path / ".gitignore").exists()
    assert (tmp_path / ".env.example").exists()

    agent = Agent(Project(tmp_path), auto_approve=True, verbose=False)
    names = [t.name for t in agent.tools]
    assert {"read_file", "list_dir", "current_time", "word_count", "load_skill"} <= set(names)
    assert "explain-code" in agent.system_prompt()

    reply = agent.run("what's in this folder?")
    assert "agentlab.yaml" in reply
    assert (tmp_path / "agentlab.log").exists()  # after_tool hook ran


def test_per_agent_overrides(tmp_path):
    main(["init", str(tmp_path)])
    agent = Agent(Project(tmp_path), "tutor", verbose=False)
    assert sorted(t.name for t in agent.tools) == ["list_dir", "load_skill", "read_file"]
    assert list(agent.skills) == ["explain-code"]
    assert agent.harness["max_turns"] == 8


def test_model_override_and_schema():
    cfg = resolve_model({"provider": "openai", "name": "x"}, "ollama:llama3.1")
    assert cfg["base_url"] == "http://localhost:11434/v1" and cfg["name"] == "llama3.1"

    def f(a: int, b: str = "x"):
        """Do f.

        Args:
            a: the number
        """
    t = Tool(f)
    assert t.parameters["required"] == ["a"]
    assert t.parameters["properties"]["a"] == {"type": "integer", "description": "the number"}
