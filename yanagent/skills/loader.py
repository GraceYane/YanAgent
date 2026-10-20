"""Skill 发现与提示词注入——当前有意保留为空实现。"""

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
        raise NotImplementedError("请按照确定的优先级解析 SKILL.md 文件")

    def render_for_prompt(self, skills: list[Skill]) -> str:
        raise NotImplementedError("请只注入与当前任务相关的 Skill 元数据和指令")

    def install(self, archive: Path, destination: Path) -> Skill:
        raise NotImplementedError("请实现路径安全的压缩包解压与内容校验")
