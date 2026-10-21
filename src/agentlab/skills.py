"""Skills: folders with a SKILL.md (frontmatter `name` + `description`, body = instructions).

Only the name and description go in the system prompt. The model calls the
`load_skill` tool to read the full instructions when it decides a skill is
relevant ("progressive disclosure"), so you can have many skills cheaply.
The format matches Anthropic's Agent Skills, so skills are portable.
"""

from pathlib import Path

from .config import parse_frontmatter


class Skill:
    def __init__(self, path):
        self.path = Path(path)
        meta, self.body = parse_frontmatter(self.path.read_text())
        self.name = meta.get("name", self.path.parent.name)
        self.description = meta.get("description", "")

    def full_text(self):
        extras = [p.name for p in self.path.parent.iterdir() if p.name != "SKILL.md"]
        text = self.body
        if extras:
            text += f"\n\n(Supporting files in {self.path.parent}: {', '.join(sorted(extras))})"
        return text


def load_skills(skills_dir, only=None):
    """Load skills from skills/*/SKILL.md. `only` is an optional list of names."""
    skills = {}
    for p in sorted(Path(skills_dir).glob("*/SKILL.md")):
        s = Skill(p)
        if only in (None, "*") or s.name in only:
            skills[s.name] = s
    return skills
