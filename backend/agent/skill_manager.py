"""
Markdown Skill 加载和管理器
从 skills/ 目录加载所有 .md 文件，解析 frontmatter 和内容
"""
from pathlib import Path
from typing import Optional
import frontmatter


class MarkdownSkill:
    """解析后的 Skill 对象"""

    def __init__(
        self,
        name: str,
        description: str,
        trigger_hint: str,
        system_prompt: str,
        tools: list,
        workflow: dict,
        file_path: Path
    ):
        self.name = name
        self.description = description
        self.trigger_hint = trigger_hint
        self.system_prompt = system_prompt
        self.tools = tools
        self.workflow = workflow
        self.file_path = file_path

    def match_score(self, query: str) -> int:
        """
        计算 query 与此 Skill 的匹配分数
        返回 0 表示不匹配
        """
        query_lower = query.lower()
        hint_lower = self.trigger_hint.lower()

        # 直接包含关键词
        keywords = [k.strip() for k in hint_lower.replace("，", ",").split(",") if k.strip()]
        score = 0

        for keyword in keywords:
            if keyword in query_lower:
                score += len(keyword)  # 关键词越长分数越高

        return score

    def __repr__(self):
        return f"<MarkdownSkill: {self.name}>"


class SkillManager:
    """Skill 加载和管理器"""

    def __init__(self, skills_dir: str = "./skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: dict[str, MarkdownSkill] = {}
        self._load_all()

    def _load_all(self):
        """加载所有 Skill"""
        if not self.skills_dir.exists():
            return

        for md_file in self.skills_dir.glob("*.md"):
            # 忽略 README 和隐藏文件
            if md_file.name.startswith(".") or md_file.name.upper().startswith("README"):
                continue

            try:
                skill = self._parse_skill(md_file)
                if skill:
                    self.skills[skill.name] = skill
            except Exception as e:
                print(f"Warning: failed to load skill {md_file}: {e}")

    def _parse_skill(self, path: Path) -> Optional[MarkdownSkill]:
        """解析单个 Skill 文件"""
        post = frontmatter.loads(path.read_text(encoding="utf-8"))

        name = post.metadata.get("name")
        if not name:
            return None

        return MarkdownSkill(
            name=name,
            description=post.metadata.get("description", ""),
            trigger_hint=post.metadata.get("triggerHint", ""),
            system_prompt=post.content,
            tools=post.metadata.get("tools", []),
            workflow=post.metadata.get("workflow", {}),
            file_path=path
        )

    def route(self, query: str) -> MarkdownSkill:
        """
        根据用户 query 路由到最合适的 Skill
        使用关键词匹配，匹配度最高的胜出
        """
        best_skill = None
        best_score = 0

        for skill in self.skills.values():
            score = skill.match_score(query)
            if score > best_score:
                best_score = score
                best_skill = skill

        # 如果没有匹配，返回 general 技能或第一个技能
        if not best_skill:
            if "general" in self.skills:
                return self.skills["general"]
            elif self.skills:
                return list(self.skills.values())[0]

        return best_skill

    def get(self, name: str) -> Optional[MarkdownSkill]:
        """按名称获取 Skill"""
        return self.skills.get(name)

    def list_skills(self) -> list[str]:
        """列出所有 Skill 名称"""
        return list(self.skills.keys())

    def reload(self):
        """重新加载所有 Skill（用于热更新）"""
        self.skills.clear()
        self._load_all()
