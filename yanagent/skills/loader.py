"""Skill discovery and prompt injection -- deliberately not implemented."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    instructions: str
    root: Path


class SkillLoader:
    def discover(self, roots: list[Path]) -> list[Skill]:
        raise NotImplementedError("Parse SKILL.md files with deterministic precedence")

    def render_for_prompt(self, skills: list[Skill]) -> str:
        raise NotImplementedError("Inject only relevant skill metadata/instructions")

    def install(self, archive: Path, destination: Path) -> Skill:
        raise NotImplementedError("Implement path-safe extraction and validation")
