"""
Exam Agent State Definition
"""
from typing import TypedDict, Optional
from langgraph.graph import add_messages


class ExamState(TypedDict, total=False):
    """出题 Agent 的状态定义"""

    # 对话历史
    messages: list

    # 出题参数
    subject: Optional[str]               # 学科：数学、语文、英语...
    grade: Optional[str]                 # 年级：高一、初二...
    textbook_version: Optional[str]      # 教材版本：人教版、北师大版...
    chapters: Optional[list[str]]        # 章节列表
    scene: Optional[str]                 # 出题场景：课后练习、单元测验...
    question_types: Optional[list[str]]  # 题型组合
    difficulty_ratio: Optional[str]      # 难度比例，如 "3:5:2"
    total_questions: Optional[int]       # 总题量
    additional_notes: Optional[str]      # 补充说明

    # 中间结果
    missing_fields: Optional[list[str]]   # 缺失参数列表
    clarification_message: Optional[str]  # 追问话术
    knowledge_points: Optional[list[str]] # 知识点列表
    blueprint: Optional[dict]            # 题目蓝图
    questions: Optional[list[dict]]       # 生成的题目列表

    # 状态
    status: Optional[str]                # "clarifying" | "generating" | "completed" | "error"
    current_skill: Optional[str]         # 当前使用的 Skill 名称
    system_prompt: Optional[str]        # 当前 Skill 的 System Prompt

    # 结果
    exam_result: Optional[dict]         # 最终试卷结果
    user_input: Optional[str]            # 用户原始输入
