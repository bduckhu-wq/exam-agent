"""
Lead Agent - 主调度器
支持多轮对话的 Skill 路由和图执行
"""
import json
from typing import Optional, AsyncIterator
from pathlib import Path

from .skill_manager import SkillManager, MarkdownSkill
from .graph import get_question_generator_graph, get_adaptor_graph
from .state import ExamState
from .memory import SessionMemory


class LeadAgent:
    """
    主调度 Agent

    支持：
    1. Skill 路由和 Markdown Skill 动态加载
    2. 多轮对话（基于 SessionMemory）
    3. 流式执行（展示推理过程）
    """

    def __init__(
        self,
        skills_dir: str = "./skills",
        sessions_dir: str = "./sessions",
        prebuilt: bool = True
    ):
        # Skill 管理
        self.skill_manager = SkillManager(skills_dir)

        # 会话记忆
        self.memory = SessionMemory(sessions_dir)

        # 预编译图
        if prebuilt:
            self.graphs = {
                "question-generator": get_question_generator_graph(),
                "question-adaptor": get_adaptor_graph(),
            }
        else:
            self.graphs = {}

    def route(self, query: str, params: dict) -> tuple[MarkdownSkill, str]:
        """
        路由到合适的 Skill

        Returns:
            (skill, intent)
        """
        combined = query + " " + " ".join(str(v) for v in params.values() if v)
        skill = self.skill_manager.route(combined)
        intent = "question" if "question" in skill.name else "adapt"
        return skill, intent

    def _build_initial_state(
        self,
        query: str,
        params: dict,
        session_id: str = None,
        skill: MarkdownSkill = None
    ) -> ExamState:
        """
        构建初始状态

        如果有 session_id，会从内存中恢复之前的上下文
        """
        # 默认状态
        state: ExamState = {
            "messages": [],
            "user_input": query,
            "subject": params.get("subject"),
            "grade": params.get("grade"),
            "textbook_version": params.get("textbook_version"),
            "chapters": params.get("chapters", []),
            "scene": params.get("scene"),
            "question_types": params.get("question_types"),
            "difficulty_ratio": params.get("difficulty_ratio"),
            "total_questions": params.get("total_questions"),
            "additional_notes": params.get("additional_notes"),
            "status": None,
            "current_skill": skill.name if skill else None,
            "system_prompt": skill.system_prompt if skill else None,
            "original_question": params.get("original_question"),
        }

        # 如果有 session_id，恢复上下文
        if session_id and self.memory.exists(session_id):
            prev_state = self.memory.load(session_id)
            if prev_state:
                # 恢复之前的参数（但不覆盖新传入的参数）
                for key in ["subject", "grade", "textbook_version", "chapters",
                            "scene", "question_types", "difficulty_ratio",
                            "total_questions", "additional_notes"]:
                    if key not in params or params[key] is None:
                        if key in prev_state and prev_state[key]:
                            params[key] = prev_state[key]
                            state[key] = prev_state[key]

                # 恢复对话历史
                if "messages" in prev_state:
                    state["messages"] = prev_state["messages"]

                # 恢复中间结果
                for key in ["knowledge_points", "blueprint", "questions", "exam_result"]:
                    if key in prev_state:
                        state[key] = prev_state[key]

                # 恢复当前 Skill
                if "current_skill" in prev_state:
                    state["current_skill"] = prev_state["current_skill"]

        # 追加用户消息
        state["messages"].append({"role": "user", "content": query})

        return state

    def run(self, query: str, params: dict, session_id: str = None) -> dict:
        """
        同步执行 Agent
        """
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.arun(query, params, session_id)
        )

    async def arun(
        self,
        query: str,
        params: dict,
        session_id: str = None,
        save_session: bool = True
    ) -> dict:
        """
        异步执行 Agent

        Args:
            query: 用户输入
            params: 参数字典
            session_id: 会话 ID（有则支持多轮对话）
            save_session: 是否保存会话状态

        Returns:
            执行结果字典
        """
        # 如果没有 session_id，生成一个新 ID
        if session_id is None:
            session_id = self.memory.generate_id()

        # Step 1: 路由
        skill, _ = self.route(query, params)

        # Step 2: 构建状态（包含上下文恢复）
        state = self._build_initial_state(query, params, session_id, skill)

        # Step 3: 获取对应的图
        graph = self.graphs.get(skill.name)
        if graph is None:
            from .graph import build_from_workflow, build_question_generator_graph
            if skill.workflow:
                graph = build_from_workflow(skill.workflow)
            else:
                graph = build_question_generator_graph()

        # Step 4: 执行图
        result = await graph.ainvoke(state)

        # Step 5: 保存会话状态
        if save_session and session_id:
            result["messages"].append({
                "role": "assistant",
                "content": self._extract_response_text(result)
            })
            self.memory.save(session_id, dict(result))

        # 带上 session_id 返回，方便前端追踪
        result["session_id"] = session_id

        return result

    async def stream_run(
        self,
        query: str,
        params: dict,
        session_id: str = None
    ) -> AsyncIterator[dict]:
        """
        流式执行，返回每步中间状态

        用于前端展示推理过程
        """
        if session_id is None:
            session_id = self.memory.generate_id()

        skill, _ = self.route(query, params)
        state = self._build_initial_state(query, params, session_id, skill)

        graph = self.graphs.get(skill.name)
        if graph is None:
            from .graph import build_question_generator_graph
            graph = build_question_generator_graph()

        # 流式返回每个节点的输出
        async for event in graph.astream_events(state):
            node_name = event.get("name", "")
            data = event.get("data", {})

            yield {
                "node": node_name,
                "session_id": session_id,
                "status": data.get("status"),
                "questions": data.get("questions"),
                "blueprint": data.get("blueprint"),
                "knowledge_points": data.get("knowledge_points"),
                "clarification_message": data.get("clarification_message"),
                "missing_fields": data.get("missing_fields"),
            }

            # 每步都保存状态
            if session_id:
                self.memory.save(session_id, dict(data))

    def _extract_response_text(self, result: dict) -> str:
        """从结果中提取文本回复"""
        if result.get("clarification_message"):
            return result["clarification_message"]

        exam_result = result.get("exam_result", {})
        questions = exam_result.get("questions", [])

        if questions:
            return f"试卷生成完成，共 {len(questions)} 道题"

        return "处理完成"

    # ============ 会话管理方法 ============

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        return self.memory.list_sessions()

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取指定会话的状态"""
        return self.memory.load_with_metadata(session_id)

    def clear_session(self, session_id: str):
        """清除指定会话"""
        self.memory.clear(session_id)

    def reload_skills(self):
        """热更新 Skill"""
        self.skill_manager.reload()

    def list_skills(self) -> list[str]:
        """列出所有可用的 Skill"""
        return self.skill_manager.list_skills()
