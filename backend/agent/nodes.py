"""
LangGraph 节点定义
每个节点对应 Skill workflow 中的一个步骤
"""
from .state import ExamState
from .tools.llm import ExamLLM
from typing import Literal
import json


# 全局 LLM 实例（懒加载）
_llm: ExamLLM = None


def get_llm() -> ExamLLM:
    global _llm
    if _llm is None:
        _llm = ExamLLM()
    return _llm


def _build_generate_prompt(state: ExamState) -> str:
    """构建生成题目的 prompt"""
    subject = state.get("subject") or "未知"
    grade = state.get("grade") or "未知"
    chapters = state.get("chapters") or []
    question_types = state.get("question_types") or ["选择题", "填空题", "解答题"]
    difficulty_ratio = state.get("difficulty_ratio") or "3:5:2"
    total = state.get("total_questions") or 15
    notes = state.get("additional_notes") or "无"

    # 根据场景确定默认题型和难度
    scene = state.get("scene") or ""
    if "课后" in scene or "练习" in scene:
        difficulty_ratio = "5:3:2"
        total = min(total, 12)
    elif "期中" in scene or "期末" in scene:
        difficulty_ratio = "2:6:2"
        total = max(total, 20)
    elif "专项" in scene:
        difficulty_ratio = "2:5:3"

    return f"""请根据以下参数生成试卷：

学科: {subject}
年级: {grade}
章节: {', '.join(chapters)}
题型: {', '.join(question_types)}
难度比例: {difficulty_ratio}
题量: {total} 道
补充要求: {notes}

请严格按照以下 JSON 格式输出，不要输出任何其他内容：
{{
  "title": "{grade}{subject}{scene if scene else '练习'}",
  "total_score": 100,
  "duration": 45,
  "knowledge_points": ["知识点列表"],
  "difficulty_ratio": "{difficulty_ratio}",
  "questions": [
    {{
      "id": "q1",
      "type": "choice",
      "difficulty": "easy",
      "content": "题目内容",
      "options": [
        {{"label": "A", "content": "选项A"}},
        {{"label": "B", "content": "选项B"}},
        {{"label": "C", "content": "选项C"}},
        {{"label": "D", "content": "选项D"}}
      ],
      "answer": "A",
      "analysis": "解析说明",
      "score": 5,
      "source": "ai",
      "knowledgePoints": ["知识点"]
    }}
  ]
}}"""


# ============ 节点函数 ============

def clarify_node(state: ExamState) -> ExamState:
    """
    追问节点：当参数不完整时生成追问话术
    """
    user_input = state.get("user_input", "")

    # 简单规则判断缺失参数
    required = []
    hints = []

    if not state.get("subject"):
        required.append("学科")
        hints.append("请告诉我是什么学科（如：数学、语文、英语）")
    if not state.get("grade"):
        required.append("年级")
        hints.append("请告诉我年级（如：高一、初二）")
    if not state.get("chapters"):
        required.append("章节")
        hints.append("请告诉我要考哪些章节")

    if not required:
        return {"status": "ready", "missing_fields": []}

    message = f"还需要确认以下信息：{', '.join(required)}。\n\n"
    message += "\n".join(hints)

    return {
        "clarification_message": message,
        "missing_fields": required,
        "status": "clarifying"
    }


def analyze_node(state: ExamState) -> ExamState:
    """
    知识分析节点：分析章节核心知识点
    """
    subject = state.get("subject") or ""
    grade = state.get("grade") or ""
    chapters = state.get("chapters") or []

    # 基于规则的简单知识分析
    knowledge_map = {
        "数学": {
            "函数": ["函数定义", "定义域", "值域", "单调性", "奇偶性", "最值", "指数函数", "对数函数"],
            "几何": ["三角形", "圆", "立体几何", "向量"],
            "代数": ["方程", "不等式", "数列", "排列组合"]
        },
        "物理": {
            "力学": ["运动学", "力的平衡", "牛顿定律", "动量", "机械能"],
            "电磁学": ["电场", "电路", "磁场", "电磁感应"]
        }
    }

    knowledge_points = []
    for chapter in chapters:
        for key, points in knowledge_map.get(subject, {}).items():
            if key in chapter:
                knowledge_points.extend(points)
                break
        else:
            knowledge_points.append(chapter)

    # 去重
    knowledge_points = list(dict.fromkeys(knowledge_points))

    return {
        "knowledge_points": knowledge_points,
        "status": "analyzing"
    }


def plan_node(state: ExamState) -> ExamState:
    """
    蓝图设计节点：设计题目结构
    """
    scene = state.get("scene") or "单元测验"
    total = state.get("total_questions") or 15
    subject = state.get("subject") or "数学"

    # 根据场景确定难度比例
    if "课后" in scene or "练习" in scene:
        easy, medium, hard = 5, 3, 2
    elif "期中" in scene or "期末" in scene:
        easy, medium, hard = 2, 6, 2
    elif "专项" in scene:
        easy, medium, hard = 2, 5, 3
    else:
        easy, medium, hard = 3, 5, 2

    # 根据学科确定题型
    if subject == "数学":
        types = [("choice", 0.4), ("fill_blank", 0.25), ("short_answer", 0.25), ("proof", 0.1)]
    elif subject == "语文":
        types = [("choice", 0.2), ("recitation", 0.2), ("reading", 0.4), ("writing", 0.2)]
    elif subject == "英语":
        types = [("choice", 0.3), ("cloze", 0.2), ("reading", 0.3), ("writing", 0.2)]
    else:
        types = [("choice", 0.4), ("fill_blank", 0.3), ("short_answer", 0.3)]

    blueprint = {
        "scene": scene,
        "total": total,
        "difficulty_ratio": f"{easy}:{medium}:{hard}",
        "question_types": types,
        "structure": []
    }

    # 生成题目结构
    q_id = 1
    difficulty_labels = ["easy"] * easy + ["medium"] * medium + ["hard"] * hard

    for qtype, ratio in types:
        count = max(1, int(total * ratio))
        for i in range(count):
            if q_id <= total and difficulty_labels:
                difficulty = difficulty_labels[q_id % len(difficulty_labels)]
                blueprint["structure"].append({
                    "id": f"q{q_id}",
                    "type": qtype,
                    "difficulty": difficulty,
                    "score": 5
                })
                q_id += 1

    return {
        "blueprint": blueprint,
        "status": "planning"
    }


def generate_node(state: ExamState) -> ExamState:
    """
    生成节点：调用 LLM 生成题目
    """
    llm = get_llm()
    system_prompt = state.get("system_prompt", "")
    params = {
        "subject": state.get("subject"),
        "grade": state.get("grade"),
        "chapters": state.get("chapters", []),
        "question_types": state.get("question_types"),
        "difficulty_ratio": state.get("difficulty_ratio") or state.get("blueprint", {}).get("difficulty_ratio", "3:5:2"),
        "total_questions": state.get("total_questions") or 15,
        "additional_notes": state.get("additional_notes", "")
    }

    # 如果没有蓝图中确定的题型，这里用默认
    if not params["question_types"]:
        params["question_types"] = ["选择题", "填空题", "解答题"]

    prompt = _build_generate_prompt(state)

    result = llm.generate_questions(system_prompt, params)

    return {
        "questions": result.get("questions", []),
        "exam_result": result,
        "status": "generating"
    }


def validate_node(state: ExamState) -> ExamState:
    """
    质量验证节点：检查生成结果
    """
    questions = state.get("questions", [])
    blueprint = state.get("blueprint", {})

    validated = []
    errors = []

    for q in questions:
        # 基本校验
        if not q.get("content"):
            errors.append(f"{q.get('id')}: 缺少题目内容")
            continue
        if not q.get("answer"):
            errors.append(f"{q.get('id')}: 缺少答案")
            continue
        validated.append(q)

    # 统计
    total = len(validated)
    easy = len([q for q in validated if q.get("difficulty") == "easy"])
    medium = len([q for q in validated if q.get("difficulty") == "medium"])
    hard = len([q for q in validated if q.get("difficulty") == "hard"])

    return {
        "questions": validated,
        "exam_result": {
            **state.get("exam_result", {}),
            "questions": validated,
            "stats": {
                "total": total,
                "easy": easy,
                "medium": medium,
                "hard": hard
            },
            "errors": errors
        },
        "status": "completed"
    }


def adapt_node(state: ExamState) -> ExamState:
    """
    改编节点：对单题进行改编
    """
    # 改编逻辑类似生成，但针对单题
    # 这里简化处理，实际可扩展
    llm = get_llm()
    system_prompt = state.get("system_prompt", "")

    params = state.get("adapt_params", {})

    return {
        "status": "completed"
    }
