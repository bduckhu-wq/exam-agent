"""
Exam Agent State Definition
"""
from typing import TypedDict, Optional
from langgraph.graph import add_messages


class ExamState(TypedDict, total=False):
    """出题 Agent 的状态定义"""

    # 用户输入（每轮对话的原始输入）
    user_input: Optional[str]             # 用户原始输入

    # 对话历史
    messages: list                         # [{role: "user"/"assistant", content: "..."}]

    # 参数（合并后的出题参数）
    params: Optional[dict]                 # 合并后的完整参数（包含所有字段）

    # 出题参数（单个字段，方便读取）
    subject: Optional[str]               # 学科：数学、语文、英语...
    grade: Optional[str]                 # 年级：高一、初二...
    textbook_version: Optional[str]      # 教材版本：人教版、北师大版...
    chapters: Optional[list[str]]         # 章节列表
    scene: Optional[str]                  # 出题场景：课后练习、单元测验...
    question_types: Optional[list[str]]   # 题型组合
    difficulty_ratio: Optional[str]      # 难度比例，如 "3:5:2"
    total_questions: Optional[int]       # 总题量
    additional_notes: Optional[str]       # 补充说明

    # 中间结果
    missing_fields: Optional[list[str]]   # 缺失参数列表
    clarification_message: Optional[str]  # 追问话术
    knowledge_points: Optional[list[str]] # 知识点列表
    knowledge_analysis: Optional[str]    # 知识分析报告（流式展示用）
    blueprint: Optional[dict]             # 题目蓝图
    blueprint_text: Optional[str]        # 蓝图画廊描述
    questions: Optional[list[dict]]       # 生成的题目列表
    validation_text: Optional[str]       # 验证报告

    # 状态
    # clarifying=需追问, ready=参数完整等待分析, analyzing=分析中
    # planning=蓝图设计中, generating=生成中, completed=完成
    # error=异常, validation_failed=验证失败
    status: Optional[str]
    current_skill: Optional[str]         # 当前使用的 Skill 名称
    current_node: Optional[str]           # 当前节点名称
    system_prompt: Optional[str]         # 当前 Skill 的 System Prompt

    # 会话
    session_id: Optional[str]             # 会话 ID

    # 结果
    exam_result: Optional[dict]          # 最终试卷结果

    # 改编题
    original_question: Optional[dict]    # 原题目（改编题用）
    adapted_question: Optional[dict]     # 改编后的题目
