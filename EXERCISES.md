# Exercises

A hands-on path through agentlab. Each exercise changes **one file** and shows
how that changes the agent. They're small on purpose, so they fit in free-tier
rate limits (see the [README](README.md) for free model options).

Start from a fresh project:

```bash
agentlab init practice
cd practice
# pick a model in agentlab.yaml (or use -m provider:model on each command)
```

> Tip: free tiers cap requests per day. Every tool call is one more model request,
> so if you hit a limit, switch provider with `-m` (e.g. `-m groq:openai/gpt-oss-20b`).

---

## 1. Watch the loop

**Concept:** the agentic loop (model → tool → model → ...)

```bash
agentlab chat
you> What files are in this folder, and what does hooks.py do?
```

- Watch the cyan `→ tool(...)` lines: the model chooses `list_dir`, then `read_file`, then answers.
- Open `agentlab.log`. Every tool call was recorded by the `after_tool` hook.
- Type `/system` to see the exact system prompt the model received.

**Questions:** How many model calls did that take? Why didn't the model just guess?

---

## 2. Agent instructions

**Concept:** the system prompt is most of the behavior.

```bash
agentlab new agent strict-reviewer
```

Edit `agents/strict-reviewer.md` so it is a harsh, nitpicky code reviewer. Then compare:

```bash
agentlab run "Review tools/example_tools.py"
agentlab run -a strict-reviewer "Review tools/example_tools.py"
```

**Try:** make a `pirate` agent, or one that must always answer in exactly 3 bullet points.
Does the model follow the rule every time? What phrasing makes it more reliable?

---

## 3. Write a tool

**Concept:** tools are just Python functions; their docstrings are prompts.

```bash
agentlab new tool dice
```

Replace the body of `tools/dice.py` with a dice roller:

```python
import random

from agentlab import tool


@tool
def roll_dice(sides: int, count: int = 1) -> str:
    """Roll dice and return each result and the total.

    Args:
        sides: number of sides on each die, e.g. 20
        count: how many dice to roll
    """
    rolls = [random.randint(1, sides) for _ in range(count)]
    return f"rolls={rolls} total={sum(rolls)}"
```

```bash
agentlab list                       # roll_dice should appear
agentlab run "Roll 3d20 and tell me the total"
```

**Break it on purpose:** change the docstring to `"""Does stuff."""` and remove the `Args:` section.
Ask again. Does the model still call it correctly? This is why tool descriptions matter.

---

## 4. Write a skill

**Concept:** skills are instructions loaded on demand (only the description is always visible).

Create a notes file to work on, e.g. `lecture3.txt`, and paste a page of your own class notes into it.

```bash
agentlab new skill study-notes
```

Edit `skills/study-notes/SKILL.md`:

```markdown
---
name: study-notes
description: Use when the user asks for flashcards, a quiz, or study notes from a file.
---
# Study notes

1. Read the file the user names with read_file.
2. Write 5 flashcards in "Q: ... / A: ..." format covering the most important ideas.
3. Save them to notes/<original-file-name>.md with write_file.
4. Reply with the path and the hardest flashcard.
```

```bash
agentlab chat
you> Make flashcards from lecture3.txt
```

**Check:** did the agent call `load_skill` *before* reading the file? If not, improve the
`description`. It's the only part the model sees until it loads the skill.

---

## 5. Harness limits

**Concept:** the harness, not the model, decides how far the agent can go.

Try each change in `agentlab.yaml` (or in an agent's frontmatter), then run the same task:

```bash
agentlab run "Make flashcards from lecture3.txt"
```

| Change | What to observe |
|---|---|
| `max_turns: 2` | The agent stops halfway. Why does this limit exist? |
| `tools: [read_file, list_dir, load_skill]` | It can't save the file. What does it do instead? |
| `confirm: []` | No more approval prompts. When is this OK, and when is it dangerous? |
| Answer `a` (always) at an approval prompt | Only that tool stops asking, and only for this session. |

---

## 6. Hooks as guardrails

**Concept:** code-level rules the model can't talk its way around.

```bash
agentlab chat
you> Run the shell command: sudo ls
```

The `before_tool` hook in `hooks.py` blocks it before you're even asked. Now:

1. Add `"curl "` to the `BLOCKED` list and test it.
2. Fill in `on_message` to count model calls and print the count after each reply:

   ```python
   def on_message(message, agent):
       agent.calls = getattr(agent, "calls", 0) + 1
       if not message["tool_calls"]:
           print(f"[{agent.calls} model calls]")
   ```

**Question:** why is a hook safer than writing "never run sudo" in the agent instructions?

---

## 7. Compare models

**Concept:** the same harness behaves very differently with different models.

Give every model the same task, starting from a fresh folder each time:

```bash
agentlab run -y -m gemini:gemini-2.5-flash  "Write fizzbuzz.py and test_fizzbuzz.py (plain asserts, no pytest), run the tests with python, and fix the code until they pass"
agentlab run -y -m groq:openai/gpt-oss-20b  "...same task..."
agentlab run -y -m ollama:qwen2.5           "...same task..."
```

> `-y` auto-approves tools. Only use it in a throwaway folder.

Fill in a table with your classmates:

| Model | Finished? | Model calls | Where did it get stuck? |
|---|---|---|---|
| | | | |

---

## 8. Mini-project (pick one)

Build it, then show it to someone else in the class.

- **Repo explainer:** a read-only agent (`tools: [read_file, list_dir, load_skill]`) with the
  `explain-code` skill. Point `workdir` at one of your course projects and have it explain the architecture.
- **Study buddy:** an agent that quizzes you from the flashcards made in exercise 4. Add a custom
  tool `record_score(topic: str, correct: bool)` that saves results to `scores.json`, and have the
  agent focus on the topics you get wrong.
- **Bug fixer:** write a small script with 3 planted bugs plus a test that fails. Give the agent only
  the task "make the tests pass" and see whether it loops `run_shell` → `read_file` → `write_file` to the end.
  Then tighten it: a skill telling it to fix one bug at a time, and a hook that blocks editing the test file.

**Stretch goals:** add a new provider in `providers.py`, add a `web_fetch` tool, or make a
"planner" agent that writes a plan to `plan.md` before doing anything.
