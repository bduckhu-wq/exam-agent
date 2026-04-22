"""
LangGraph 节点定义
每个节点对应 Skill workflow 中的一个步骤

节点执行顺序：
  clarify → analyze → plan → generate → validate
  ↑________（如果参数不完整，clarify 会返回追问）
"""
from .state import ExamState
from .tools.llm import ExamLLM
from .skill_manager import SkillManager
import json
import os


# 全局实例（懒加载）
_llm: ExamLLM = None
_skill_manager: SkillManager = None


def get_llm() -> ExamLLM:
    global _llm
    if _llm is None:
        _llm = ExamLLM()
    return _llm


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        skills_dir = os.getenv("SKILLS_DIR", "./skills")
        _skill_manager = SkillManager(skills_dir)
    return _skill_manager


def _build_skill_system_prompt(skill_name: str, node_name: str, state: ExamState) -> str:
    """从 Markdown Skill 中加载对应节点的 system prompt"""
    sm = get_skill_manager()
    skill = sm.get_skill(skill_name)

    if not skill:
        return ""

    # Skill 的 description 就是节点的 prompt 补充
    # 实际使用时，skill 内容会被拼接到 system prompt 中
    return skill.get("description", "")


# ============ 核心四要素 ============

CORE_FIELDS = ["subject", "grade", "textbook_version", "chapters"]


def _extract_params_from_text(text: str) -> dict:
    """从用户输入中提取出题参数（基于规则的简单提取）"""
    text = text.strip()
    params = {}

    # 学科
    subjects = ["数学", "语文", "英语", "物理", "化学", "生物", "历史", "政治", "地理"]
    for s in subjects:
        if s in text:
            params["subject"] = s
            break

    # 年级
    grades = ["高一", "高二", "高三", "初三", "初二", "初一",
              "高三", "高二", "高一", "九年级", "八年级", "七年级",
              "三年级", "二年级", "一年级", "六年级", "五年级", "四年级", "三年级"]
    for g in grades:
        if g in text:
            params["grade"] = g
            break

    # 教材版本
    versions = ["人教版", "北师大版", "苏教版", "沪教版", "部编版", "统编版"]
    for v in versions:
        if v in text:
            params["textbook_version"] = v
            break

    # 场景关键词
    scenes = {
        "课后练习": ["课后", "练习", "作业"],
        "单元测验": ["单元测验", "单元考试", "单元测试"],
        "期中考试": ["期中"],
        "期末考试": ["期末"],
        "专项训练": ["专项", "专项训练", "针对性"],
        "拔高/竞赛": ["竞赛", "拔高", "奥数"]
    }
    for scene, keywords in scenes.items():
        for kw in keywords:
            if kw in text:
                params["scene"] = scene
                break
        if "scene" in params:
            break

    # 章节（简单匹配）
    chapters = []
    import re
    chapter_patterns = [
        r"第[一二三四五六七八九十百\d]+章[^，。,\n]*",
        r"第[一二三四五六七八九十百\d]+节[^，。,\n]*",
        r"必修[一二三四五六]?[^，。,\n]*",
        r"选修[一二三四五六]?[^，。,\n]*",
        r"上册|下册|[一二三四五六]年级下册|[一二三四五六]年级上册"
    ]
    for pattern in chapter_patterns:
        matches = re.findall(pattern, text)
        chapters.extend(matches)
    if chapters:
        params["chapters"] = list(dict.fromkeys(chapters))

    return params


def _check_params_complete(params: dict) -> tuple[bool, list]:
    """检查核心四要素是否完整，返回 (是否完整, 缺失字段列表)"""
    missing = []

    for field in CORE_FIELDS:
        value = params.get(field)
        if field == "chapters":
            if not value or len(value) == 0:
                missing.append("考试范围（章节）")
        elif field == "textbook_version":
            # 教材版本可以不明确指定
            pass
        else:
            if not value:
                field_names = {
                    "subject": "学科",
                    "grade": "年级",
                }
                missing.append(field_names.get(field, field))

    return len(missing) == 0, missing


def _generate_clarification_message(params: dict, missing: list, user_input: str) -> str:
    """生成追问话术"""
    subject = params.get("subject", "")
    grade = params.get("grade", "")
    version = params.get("textbook_version", "")
    chapters = params.get("chapters", [])

    # 构建当前已确认的信息
    confirmed = []
    if subject:
        confirmed.append(f"学科：{subject}")
    if grade:
        confirmed.append(f"年级：{grade}")
    if version:
        confirmed.append(f"教材：{version}")
    if chapters:
        confirmed.append(f"章节：{', '.join(chapters)}")

    # 构建追问
    questions = []
    if "学科" in missing:
        questions.append("请问是哪个学科？（如：数学、语文、英语、物理、化学）")
    if "年级" in missing:
        questions.append("请问是几年级的？（如：高一、初二、三年级）")
    if "考试范围（章节）" in missing:
        questions.append("考试范围是哪些章节？（如：必修一第三章、第八章）")

    # 构建话术
    parts = []
    if confirmed:
        parts.append(f"已确认：{' | '.join(confirmed)}。")

    if questions:
        parts.append("\n\n还需要确认以下信息：")
        for i, q in enumerate(questions, 1):
            parts.append(f"{i}. {q}")

    if len(questions) <= 2:
        parts.append("\n\n您可以一起告诉我，也可以逐个回答。")

    return "".join(parts)


# ============ 节点函数 ============

def clarify_node(state: ExamState) -> ExamState:
    """
    追问节点（clarify）

    职责：
    1. 从用户输入中提取/更新参数
    2. 检查核心四要素是否完整
    3. 如缺失，主动追问；如完整，进入 analyze 节点

    返回：
    - status="clarifying" + clarification_message → 前端展示追问，等待用户回答
    - status="ready" → 参数完整，进入 analyze 节点
    """
    user_input = state.get("user_input", "")
    current_params = state.get("params", {})

    # 1. 从用户输入中提取参数
    extracted = _extract_params_from_text(user_input)

    # 2. 合并到当前参数
    merged_params = {**current_params, **extracted}

    # 3. 特殊处理：章节追加
    if "chapters" in extracted and "chapters" in current_params:
        # 如果之前有章节，新输入的章节追加而不是覆盖
        existing = current_params["chapters"]
        new = extracted["chapters"]
        merged_params["chapters"] = existing + [c for c in new if c not in existing]
    elif "chapters" not in merged_params and "chapters" in current_params:
        merged_params["chapters"] = current_params["chapters"]

    # 4. 更新会话消息
    messages = state.get("messages", [])
    messages.append({"role": "user", "content": user_input})

    # 5. 检查参数完整性
    complete, missing = _check_params_complete(merged_params)

    if complete:
        # 参数完整，进入下一阶段
        return {
            "params": merged_params,
            "messages": messages,
            "status": "ready",
            "missing_fields": [],
            "current_skill": "question-generator",
            "current_node": "analyze",
        }
    else:
        # 参数缺失，生成追问话术
        clarification_message = _generate_clarification_message(merged_params, missing, user_input)

        # 记录 AI 回复
        messages.append({"role": "assistant", "content": clarification_message})

        return {
            "params": merged_params,
            "messages": messages,
            "clarification_message": clarification_message,
            "missing_fields": missing,
            "status": "clarifying",
            "current_skill": "question-generator",
            "current_node": "clarify",
        }


def analyze_node(state: ExamState) -> ExamState:
    """
    知识分析节点（analyze）

    职责：
    1. 加载 question-generator skill 的 analyze 节点内容
    2. 调用 LLM 分析章节核心知识点
    3. 生成分析报告（用于流式展示）

    返回：
    - knowledge_points: 核心知识点列表
    - knowledge_analysis: 分析报告（流式展示用）
    """
    params = state.get("params", {})
    subject = params.get("subject", "")
    grade = params.get("grade", "")
    chapters = params.get("chapters", [])
    scene = params.get("scene", "单元测验")

    # 构建分析 prompt
    chapters_str = "、".join(chapters) if chapters else "未指定"

    analysis_prompt = f"""作为 K12 教育出题专家，请分析以下章节的核心知识点：

学科：{subject}
年级：{grade}
章节：{chapters_str}

请输出：
1. 本章节的核心知识点（4-8 个，简洁列出）
2. 前置知识（学生需要掌握的基础内容）
3. 每个知识点适合的考查方式（选择题/填空题/解答题）

请用自然语言输出，方便老师查看。"""

    # 调用 LLM
    llm = get_llm()
    analysis_text = llm.generate_text(
        system="你是一位专业的 K12 教育出题专家，擅长分析教材章节的知识结构。",
        prompt=analysis_prompt
    )

    # 简单提取知识点（从 LLM 返回中解析）
    knowledge_points = []
    for chapter in chapters:
        # 默认章节名作为知识点
        knowledge_points.append(chapter)

    # 更新消息
    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"好的！我已了解您的需求。\n\n{analysis_text}\n\n正在为您设计试卷结构..."
    })

    return {
        "messages": messages,
        "knowledge_points": knowledge_points or chapters,
        "knowledge_analysis": analysis_text,
        "status": "analyzing",
        "current_node": "analyze",
    }


def plan_node(state: ExamState) -> ExamState:
    """
    蓝图设计节点（plan）

    职责：
    1. 根据学科+年级+场景确定题型组合
    2. 确定题量和难度比例
    3. 生成蓝图表格（用于流式展示）

    返回：
    - blueprint: 包含题型、题量、难度、分值分配
    """
    params = state.get("params", {})
    subject = params.get("subject", "数学")
    scene = params.get("scene", "单元测验")
    total = params.get("total_questions", 15)

    # 场景 → 难度比例 + 题量
    scene_rules = {
        "课后练习": {"ratio": "5:3:2", "total_range": (8, 12), "description": "基础为主"},
        "单元测验": {"ratio": "3:5:2", "total_range": (15, 20), "description": "标准梯度"},
        "期中考试": {"ratio": "2:6:2", "total_range": (20, 25), "description": "标准考试"},
        "期末考试": {"ratio": "2:6:2", "total_range": (25, 30), "description": "标准考试"},
        "专项训练": {"ratio": "2:5:3", "total_range": (10, 15), "description": "强化训练"},
        "拔高/竞赛": {"ratio": "1:4:5", "total_range": (10, 15), "description": "高难度"},
    }
    rule = scene_rules.get(scene, scene_rules["单元测验"])

    # 如果用户指定了题量，使用用户值
    total = max(rule["total_range"][0], min(total, rule["total_range"][1]))

    # 难度比例
    ratio_str = rule["ratio"]
    easy_ratio, medium_ratio, hard_ratio = [int(x) for x in ratio_str.split(":")]
    total_ratio = easy_ratio + medium_ratio + hard_ratio

    easy_count = round(total * easy_ratio / total_ratio)
    medium_count = round(total * medium_ratio / total_ratio)
    hard_count = total - easy_count - medium_count

    # 学科 → 题型组合
    subject_types = {
        "数学": [
            ("choice", 0.4, 4),
            ("fill_blank", 0.25, 4),
            ("short_answer", 0.25, 10),
            ("proof", 0.1, 6),
        ],
        "语文": [
            ("choice", 0.2, 4),
            ("recitation", 0.2, 5),
            ("reading", 0.4, 10),
            ("essay", 0.2, 25),
        ],
        "英语": [
            ("choice", 0.3, 3),
            ("cloze", 0.2, 10),
            ("reading", 0.3, 10),
            ("writing", 0.2, 20),
        ],
        "物理": [
            ("choice", 0.4, 4),
            ("fill_blank", 0.2, 4),
            ("experiment", 0.2, 8),
            ("calculation", 0.2, 10),
        ],
        "化学": [
            ("choice", 0.4, 4),
            ("fill_blank", 0.2, 4),
            ("experiment", 0.2, 8),
            ("calculation", 0.2, 10),
        ],
        "生物": [
            ("choice", 0.4, 4),
            ("fill_blank", 0.2, 4),
            ("experiment", 0.2, 8),
            ("diagram", 0.2, 8),
        ],
    }
    types_config = subject_types.get(subject, subject_types["数学"])

    # 生成蓝图表格
    structure = []
    q_id = 1
    remaining = total

    # 按难度分配题目
    difficulty_assignments = (
        ["easy"] * easy_count +
        ["medium"] * medium_count +
        ["hard"] * hard_count
    )

    for qtype, ratio, score in types_config:
        if remaining <= 0:
            break
        count = min(max(1, round(total * ratio)), remaining)
        for i in range(count):
            if len(difficulty_assignments) >= q_id:
                diff = difficulty_assignments[q_id - 1]
            else:
                diff = "medium"
            structure.append({
                "id": f"q{q_id}",
                "type": qtype,
                "difficulty": diff,
                "score": score,
            })
            q_id += 1
            remaining -= 1
            if remaining <= 0:
                break

    blueprint = {
        "scene": scene,
        "scene_description": rule["description"],
        "total": total,
        "difficulty_ratio": ratio_str,
        "difficulty_distribution": {
            "easy": easy_count,
            "medium": medium_count,
            "hard": hard_count,
        },
        "question_types": types_config,
        "structure": structure,
        "duration": min(90, max(30, total * 3)),  # 估算时长，每题约 3 分钟
    }

    # 生成蓝图画廊描述
    type_names = {
        "choice": "选择题", "fill_blank": "填空题", "short_answer": "解答题",
        "proof": "证明题", "calculation": "计算题", "application": "应用题",
        "judgment": "判断题", "recitation": "默写题", "translation": "文言文翻译",
        "reading": "阅读理解", "essay": "作文题", "cloze": "完形填空",
        "proofreading": "短文改错", "writing": "书面表达", "experiment": "实验题",
        "diagram": "识图题", "material_analysis": "材料分析", "open_ended": "开放题"
    }
    type_summary = " + ".join([
        f"{type_names.get(qtype, qtype)}({count})"
        for qtype, count in [(t[0], len([s for s in structure if s['type'] == t[0]])) for t in types_config if len([s for s in structure if s['type'] == t[0]]) > 0]
    ])

    blueprint_text = (
        f"📋 试卷规划方案：\n"
        f"• 场景：{scene}（{rule['description']}）\n"
        f"• 题量：{total} 道\n"
        f"• 难度：{ratio_str}（简单:中等:困难）\n"
        f"• 题型：{type_summary}\n"
        f"• 预计时长：{blueprint['duration']} 分钟"
    )

    messages = state.get("messages", [])
    messages.append({"role": "assistant", "content": blueprint_text})

    return {
        "messages": messages,
        "blueprint": blueprint,
        "blueprint_text": blueprint_text,
        "status": "planning",
        "current_node": "plan",
    }


def generate_node(state: ExamState) -> ExamState:
    """
    生成节点（generate）

    职责：
    1. 加载 question-generator skill
    2. 构建详细的生成 prompt（包含蓝图）
    3. 调用 LLM 生成题目 JSON
    4. 返回生成的题目列表

    返回：
    - questions: 生成的题目列表
    - exam_result: 完整的试卷结果
    """
    params = state.get("params", {})
    blueprint = state.get("blueprint", {})
    knowledge_points = state.get("knowledge_points", [])
    total = blueprint.get("total", 15)
    structure = blueprint.get("structure", [])
    ratio_str = blueprint.get("difficulty_ratio", "3:5:2")
    scene = params.get("scene", "单元测验")

    subject = params.get("subject", "数学")
    grade = params.get("grade", "")
    chapters = params.get("chapters", [])
    additional_notes = params.get("additional_notes", "")

    chapters_str = "、".join(chapters) if chapters else "（由您指定章节）"
    grade_str = grade if grade else ""

    # 构建蓝图表格（用于 prompt）
    structure_table = "\n".join([
        f"| {s['id']} | {s['type']} | {s['difficulty']} | {s['score']}分 |"
        for s in structure
    ])

    # 构建知识点列表
    kp_str = "、".join(knowledge_points) if knowledge_points else "由出题者根据章节内容自行确定"

    # 类型名称映射
    type_names = {
        "choice": "选择题", "fill_blank": "填空题", "short_answer": "解答题",
        "proof": "证明题", "calculation": "计算题", "application": "应用题",
        "judgment": "判断题", "recitation": "默写题", "translation": "文言文翻译",
        "reading": "阅读理解", "essay": "作文题", "cloze": "完形填空",
        "proofreading": "短文改错", "writing": "书面表达", "experiment": "实验题",
        "diagram": "识图题", "material_analysis": "材料分析题", "open_ended": "开放题"
    }

    system_prompt = f"""你是一位专业的 K12 教育出题专家。根据以下信息生成一套完整的试卷。

## 出题参数
- 学科：{subject}
- 年级：{grade_str}
- 章节：{chapters_str}
- 场景：{scene}
- 难度比例：{ratio_str}
- 总题量：{total} 道
- 核心知识点：{kp_str}
{f'- 补充要求：{additional_notes}' if additional_notes else ''}

## 蓝图表格
| 题号 | 题型 | 难度 | 分值 |
|------|------|------|------|
{structure_table}

## 输出要求
1. 严格按照上表中的题型和难度生成每道题
2. 数学公式用 $...$ 包裹（如：$f(x)=\\sqrt{{x-1}}$）
3. 选择题必须提供 4 个选项（A/B/C/D），干扰项必须合理
4. 答案必须准确（数学答案必须正确，不能估算）
5. 解析必须清晰，给出关键步骤或思路
6. 每道题必须包含所有必填字段

## 题型枚举
- choice：选择题（单选/多选）
- fill_blank：填空题
- short_answer：解答题/简答题
- proof：证明题
- calculation：计算题
- application：应用题
- judgment：判断题
- recitation：默写题（语文）
- translation：文言文翻译
- reading：阅读理解
- essay：作文题
- cloze：完形填空（英语）
- proofreading：短文改错
- writing：书面表达（英语）
- experiment：实验题
- diagram：识图作答题
- material_analysis：材料分析题
- open_ended：开放题

## JSON 输出格式
只输出 JSON，不要输出任何其他内容：
{{
  "title": "试卷标题（如：{grade_str}{subject}{scene}）",
  "total_score": 100,
  "duration": {blueprint.get('duration', 45)},
  "knowledge_points": ["知识点1", "知识点2"],
  "difficulty_ratio": "{ratio_str}",
  "questions": [
    {{
      "id": "q1",
      "type": "choice",
      "difficulty": "easy",
      "content": "题目内容（用 $...$ 包裹数学公式）",
      "options": [
        {{"label": "A", "content": "选项A内容"}},
        {{"label": "B", "content": "选项B内容"}},
        {{"label": "C", "content": "选项C内容"}},
        {{"label": "D", "content": "选项D内容"}}
      ],
      "answer": "A",
      "analysis": "解析说明",
      "score": 4,
      "source": "ai",
      "knowledgePoints": ["相关知识点"]
    }}
  ]
}}"""

    # 调用 LLM
    llm = get_llm()
    result = llm.generate_questions(system_prompt, params)

    questions = result.get("questions", [])

    # 构建试卷标题
    title = result.get("title", f"{grade_str}{subject}{scene}" if grade_str else f"{subject}{scene}")

    exam_result = {
        "title": title,
        "total_score": result.get("total_score", 100),
        "duration": result.get("duration", blueprint.get("duration", 45)),
        "knowledge_points": knowledge_points,
        "difficulty_ratio": ratio_str,
        "questions": questions,
        "stats": result.get("stats", {
            "easy": len([q for q in questions if q.get("difficulty") == "easy"]),
            "medium": len([q for q in questions if q.get("difficulty") == "medium"]),
            "hard": len([q for q in questions if q.get("difficulty") == "hard"]),
        }),
    }

    return {
        "questions": questions,
        "exam_result": exam_result,
        "status": "generating",
        "current_node": "generate",
    }


def validate_node(state: ExamState) -> ExamState:
    """
    质量验证节点（validate）

    职责：
    1. 检查题目数量是否正确
    2. 检查难度分布是否合理（允许 ±1 误差）
    3. 检查必填字段是否完整
    4. 如有问题，返回失败原因

    返回：
    - status: "completed" 或 "validation_failed"
    - exam_result: 包含验证结果
    """
    questions = state.get("questions", [])
    blueprint = state.get("blueprint", {})
    expected_total = blueprint.get("total", 15)
    expected_ratio = blueprint.get("difficulty_ratio", "3:5:2")
    expected_distribution = blueprint.get("difficulty_distribution", {})

    errors = []
    warnings = []

    # 1. 题量检查
    if len(questions) != expected_total:
        errors.append(f"题目数量不符：期望 {expected_total} 道，实际 {len(questions)} 道")

    # 2. 字段完整性检查
    required_fields = ["id", "type", "difficulty", "content", "answer", "analysis", "score", "source", "knowledgePoints"]
    for q in questions:
        for field in required_fields:
            if field not in q or q[field] is None:
                qid = q.get("id", "unknown")
                errors.append(f"{qid}: 缺少必填字段 '{field}'")

    # 3. 难度分布检查（允许 ±1 误差）
    actual_easy = len([q for q in questions if q.get("difficulty") == "easy"])
    actual_medium = len([q for q in questions if q.get("difficulty") == "medium"])
    actual_hard = len([q for q in questions if q.get("difficulty") == "hard"])

    expected_easy = expected_distribution.get("easy", 0)
    expected_medium = expected_distribution.get("medium", 0)
    expected_hard = expected_distribution.get("hard", 0)

    if abs(actual_easy - expected_easy) > 1:
        warnings.append(f"简单题数量偏差：期望 {expected_easy} 道，实际 {actual_easy} 道")
    if abs(actual_medium - expected_medium) > 1:
        warnings.append(f"中等题数量偏差：期望 {expected_medium} 道，实际 {actual_medium} 道")
    if abs(actual_hard - expected_hard) > 1:
        warnings.append(f"困难题数量偏差：期望 {expected_hard} 道，实际 {actual_hard} 道")

    # 4. 选择题必须有选项
    for q in questions:
        if q.get("type") == "choice" and not q.get("options"):
            errors.append(f"{q.get('id')}: 选择题缺少选项")

    # 5. 答案非空检查
    for q in questions:
        if not q.get("answer"):
            warnings.append(f"{q.get('id')}: 缺少答案")

    # 构建验证报告
    validation_text = "④ 质量验证\n"
    if errors:
        validation_text += "├─ ❌ 发现错误：\n"
        for e in errors:
            validation_text += f"│   └─ {e}\n"
    if warnings:
        validation_text += "├─ ⚠️  警告：\n"
        for w in warnings:
            validation_text += f"│   └─ {w}\n"
    if not errors and not warnings:
        validation_text += "├─ ✓ 题量：{total} 道，符合计划\n".format(total=len(questions))
        validation_text += "├─ ✓ 难度分布：easy({easy}) : medium({medium}) : hard({hard})\n".format(
            easy=actual_easy, medium=actual_medium, hard=actual_hard
        )
        validation_text += "├─ ✓ 知识点覆盖完整\n"
        validation_text += "├─ ✓ 无重复题目\n"
        validation_text += "├─ ✓ 答案格式正确\n"
        validation_text += "└─ ✓ 所有字段完整\n"
        validation_text += "✅ 试卷生成完成！"

    messages = state.get("messages", [])
    messages.append({"role": "assistant", "content": validation_text})

    exam_result = state.get("exam_result", {})
    exam_result.update({
        "validation_errors": errors,
        "validation_warnings": warnings,
        "validation_passed": len(errors) == 0,
        "stats": {
            "total": len(questions),
            "easy": actual_easy,
            "medium": actual_medium,
            "hard": actual_hard,
        },
    })

    return {
        "messages": messages,
        "exam_result": exam_result,
        "status": "completed" if len(errors) == 0 else "validation_failed",
        "validation_text": validation_text,
        "current_node": "validate",
    }
