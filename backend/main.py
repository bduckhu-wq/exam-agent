"""
Exam Agent - FastAPI 主入口
支持多轮对话 + 流式推理 + Markdown Skill
"""
import os
import json
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

from agent.lead import LeadAgent


# ============ 请求/响应模型 ============

class GenerateExamRequest(BaseModel):
    """生成试卷请求"""
    session_id: Optional[str] = Field(default=None, description="会话 ID，用于多轮对话")
    user_input: str = Field(description="用户的自然语言输入")
    subject: Optional[str] = Field(default=None, description="学科")
    grade: Optional[str] = Field(default=None, description="年级")
    textbook_version: Optional[str] = Field(default=None, description="教材版本")
    chapters: Optional[list[str]] = Field(default_factory=list, description="章节列表")
    scene: Optional[str] = Field(default=None, description="出题场景")
    question_types: Optional[list[str]] = Field(default=None, description="题型")
    difficulty_ratio: Optional[str] = Field(default=None, description="难度比例，如 3:5:2")
    total_questions: Optional[int] = Field(default=15, description="总题量")
    additional_notes: Optional[str] = Field(default="", description="补充说明")


class ClarifyRequest(BaseModel):
    """追问请求"""
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    user_input: str = Field(description="用户的自然语言输入")
    current_params: Optional[dict] = Field(default_factory=dict, description="当前已收集的参数")


class AdaptQuestionRequest(BaseModel):
    """改编题目请求"""
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    original_question: dict = Field(description="原题目")
    adapt_direction: str = Field(description="改编方向")


# ============ 全局 Agent 实例 ============

_agent: Optional[LeadAgent] = None


def get_agent() -> LeadAgent:
    global _agent
    if _agent is None:
        skills_dir = os.getenv("SKILLS_DIR", "./skills")
        sessions_dir = os.getenv("SESSIONS_DIR", "./sessions")
        _agent = LeadAgent(skills_dir=skills_dir, sessions_dir=sessions_dir)
    return _agent


# ============ FastAPI 应用 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    # 启动时
    agent = get_agent()
    print(f"✅ Exam Agent 启动")
    print(f"   Skills: {agent.list_skills()}")
    print(f"   Model: {os.getenv('MODEL_NAME', 'kimi-k2.5')}")
    print(f"   Sessions: {os.getenv('SESSIONS_DIR', './sessions')}")
    yield
    # 关闭时
    print("👋 Exam Agent 关闭")


app = FastAPI(
    title="Exam Agent API",
    description="出题 Agent 后端 - FastAPI + LangGraph + Markdown Skill + 多轮对话",
    version="1.1.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ API 接口 ============

@app.get("/")
async def root():
    """健康检查"""
    agent = get_agent()
    return {
        "status": "ok",
        "version": "1.1.0",
        "skills": agent.list_skills(),
        "model": os.getenv("MODEL_NAME", "kimi-k2.5"),
        "features": ["multi-turn", "streaming", "markdown-skill"]
    }


@app.post("/api/exam/generate")
async def generate_exam(req: GenerateExamRequest):
    """
    生成试卷

    支持多轮对话：
    - 首次调用时不传 session_id，会自动生成一个
    - 后续调用传入 session_id，Agent 会记住之前的上下文
    """
    agent = get_agent()

    params = {
        "subject": req.subject,
        "grade": req.grade,
        "textbook_version": req.textbook_version,
        "chapters": req.chapters,
        "scene": req.scene,
        "question_types": req.question_types,
        "difficulty_ratio": req.difficulty_ratio,
        "total_questions": req.total_questions,
        "additional_notes": req.additional_notes,
    }

    result = await agent.arun(req.user_input, params, session_id=req.session_id)

    # 提取结果
    exam_result = result.get("exam_result", {})
    questions = exam_result.get("questions", result.get("questions", []))
    status = result.get("status")

    # 如果是追问状态
    if status == "clarifying":
        return {
            "code": 1,
            "message": "需要补充信息",
            "session_id": result.get("session_id"),  # 前端需要保存这个
            "data": {
                "clarification_message": result.get("clarification_message"),
                "missing_fields": result.get("missing_fields", []),
            }
        }

    # 正常返回
    return {
        "code": 0,
        "message": "success",
        "session_id": result.get("session_id"),  # 返回 session_id 给前端
        "data": {
            "title": exam_result.get("title", f"{params.get('grade', '')}{params.get('subject', '')}练习"),
            "total_score": exam_result.get("total_score", 0),
            "duration": exam_result.get("duration", 45),
            "knowledge_points": exam_result.get("knowledge_points", result.get("knowledge_points", [])),
            "difficulty_ratio": exam_result.get("difficulty_ratio", params.get("difficulty_ratio", "3:5:2")),
            "questions": questions,
            "stats": exam_result.get("stats", {}),
        },
        "skill_used": result.get("current_skill"),
    }


@app.post("/api/exam/generate/stream")
async def generate_exam_stream(req: GenerateExamRequest):
    """
    流式生成试卷，返回推理过程

    用于前端展示思考步骤（如 DeerFlow 那样的推理步骤展示）
    每步都会返回当前节点的状态
    """
    agent = get_agent()

    params = {
        "subject": req.subject,
        "grade": req.grade,
        "chapters": req.chapters,
        "scene": req.scene,
        "question_types": req.question_types,
        "difficulty_ratio": req.difficulty_ratio,
        "total_questions": req.total_questions,
        "additional_notes": req.additional_notes,
    }

    async def event_generator():
        session_id = req.session_id
        first = True

        async for event in agent.stream_run(req.user_input, params, session_id=session_id):
            # 第一次返回 session_id
            if first:
                first = False
                event["is_first"] = True

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # 结束信号
        yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/api/exam/clarify")
async def clarify(req: ClarifyRequest):
    """
    单轮追问（不保存上下文）

    适合快速分析用户输入
    """
    agent = get_agent()

    result = await agent.arun(
        req.user_input,
        req.current_params or {},
        session_id=req.session_id
    )

    if result.get("status") == "clarifying":
        return {
            "code": 1,
            "message": result.get("clarification_message"),
            "session_id": result.get("session_id"),
            "missing_fields": result.get("missing_fields", []),
        }

    return {
        "code": 0,
        "message": "参数已完整",
        "session_id": result.get("session_id"),
        "extracted_params": {
            "subject": result.get("subject"),
            "grade": result.get("grade"),
            "chapters": result.get("chapters"),
            "scene": result.get("scene"),
        }
    }


@app.post("/api/exam/adapt")
async def adapt_question(req: AdaptQuestionRequest):
    """
    改编单题
    """
    return {
        "code": 0,
        "message": "功能开发中",
        "data": req.original_question
    }


# ============ 会话管理接口 ============

@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    agent = get_agent()
    sessions = agent.list_sessions()
    return {
        "code": 0,
        "data": sessions
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话的完整状态"""
    agent = get_agent()
    session = agent.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {
        "code": 0,
        "data": session
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    agent = get_agent()
    agent.clear_session(session_id)
    return {
        "code": 0,
        "message": "会话已删除"
    }


@app.get("/api/skills")
async def list_skills():
    """列出所有可用的 Skill"""
    agent = get_agent()
    return {
        "code": 0,
        "data": agent.list_skills()
    }


@app.post("/api/skills/reload")
async def reload_skills():
    """热更新 Skill（修改 Markdown 文件后调用）"""
    agent = get_agent()
    agent.reload_skills()
    return {
        "code": 0,
        "message": "Skills 已重新加载",
        "skills": agent.list_skills()
    }


# ============ 启动入口 ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True
    )
