"""
Exam Agent - FastAPI 主入口
支持多轮对话 + 流式推理 + Markdown Skill + Harness（日志+重试+熔断）
"""
import os
import json
import time
import uuid
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

from agent.lead import LeadAgent
from agent.logger import get_logger
from agent.harness import (
    AgentError, LLMError, SkillNotFoundError,
    CircuitBreaker, get_circuit_breaker
)


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


# ============ 全局实例 ============

_agent: Optional[LeadAgent] = None
_logger = None


def get_agent() -> LeadAgent:
    global _agent
    if _agent is None:
        skills_dir = os.getenv("SKILLS_DIR", "./skills")
        sessions_dir = os.getenv("SESSIONS_DIR", "./sessions")
        _agent = LeadAgent(skills_dir=skills_dir, sessions_dir=sessions_dir)
    return _agent


def get_logger_instance():
    global _logger
    if _logger is None:
        log_dir = os.getenv("LOG_DIR", "./logs")
        _logger = get_logger(log_dir)
    return _logger


# ============ FastAPI 应用 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger = get_logger_instance()
    agent = get_agent()

    logger.logger.info("=" * 50)
    logger.logger.info("✅ Exam Agent 启动")
    logger.logger.info(f"   Skills: {agent.list_skills()}")
    logger.logger.info(f"   Model: {os.getenv('MODEL_NAME', 'kimi-k2.5')}")
    logger.logger.info(f"   Sessions: {os.getenv('SESSIONS_DIR', './sessions')}")
    logger.logger.info(f"   Logs: {os.getenv('LOG_DIR', './logs')}")
    logger.logger.info("=" * 50)

    # 启动时清理过期会话
    try:
        agent.memory.cleanup(max_age_hours=24)
        logger.logger.info(f"🧹 清理了过期会话")
    except Exception as e:
        logger.logger.warning(f"⚠️  清理会话失败: {e}")

    yield

    logger.logger.info("👋 Exam Agent 关闭")


app = FastAPI(
    title="Exam Agent API",
    description="出题 Agent 后端 - FastAPI + LangGraph + Markdown Skill + 多轮对话 + Harness",
    version="1.2.0",
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


# ============ 请求拦截：生成 request_id ============

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """给每个请求分配唯一 ID，便于追踪"""
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id

    start_time = time.time()
    logger = get_logger_instance()

    try:
        response = await call_next(request)
        duration_ms = (time.time() - start_time) * 1000
        logger.logger.info(
            f"[{request_id}] {request.method} {request.url.path} | {response.status_code} | {duration_ms:.0f}ms"
        )
        response.headers["X-Request-ID"] = request_id
        return response

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.logger.error(
            f"[{request_id}] {request.method} {request.url.path} | ERROR | {duration_ms:.0f}ms | {e}"
        )
        raise


# ============ API 接口 ============

@app.get("/")
async def root():
    """健康检查 + 系统状态"""
    agent = get_agent()
    circuit = get_circuit_breaker()

    return {
        "status": "ok",
        "version": "1.2.0",
        "skills": agent.list_skills(),
        "model": os.getenv("MODEL_NAME", "kimi-k2.5"),
        "features": ["multi-turn", "streaming", "markdown-skill", "harness"],
        "harness": {
            "circuit_breaker": circuit.get_state(),
        }
    }


@app.post("/api/exam/generate")
async def generate_exam(req: GenerateExamRequest, request: Request):
    """
    生成试卷

    支持多轮对话：
    - 首次调用时不传 session_id，会自动生成一个
    - 后续调用传入 session_id，Agent 会记住之前的上下文

    Harness 特性：
    - 请求追踪（request_id）
    - 节点执行日志
    - LLM 异常重试
    - 熔断保护
    """
    request_id = request.state.request_id
    logger = get_logger_instance()
    circuit = get_circuit_breaker()

    # 检查熔断器
    if not circuit.can_execute():
        logger.logger.warning(f"[{request_id}] ⚠️  Circuit breaker OPEN，跳过 LLM 调用")
        return {
            "code": 503,
            "message": "服务暂时不可用（LLM 熔断保护），请稍后重试",
            "request_id": request_id,
        }

    agent = get_agent()

    # 确定 session_id
    session_id = req.session_id or agent.memory.generate_id()

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

    # 记录请求
    skill = agent.skill_manager.route(req.user_input + " " + " ".join(str(v) for v in params.values() if v))
    logger.log_request(request_id, session_id, req.user_input, skill.name)
    logger.log_session(session_id, "CREATE" if not req.session_id else "RESUME", "")

    try:
        start_time = time.time()
        result = await agent.arun(req.user_input, params, session_id=session_id)
        total_ms = (time.time() - start_time) * 1000

        exam_result = result.get("exam_result", {})
        questions = exam_result.get("questions", result.get("questions", []))
        status = result.get("status")

        circuit.record_success()

        if status == "clarifying":
            logger.log_result(request_id, "clarifying", 0, total_ms)
            return {
                "code": 1,
                "message": "需要补充信息",
                "request_id": request_id,
                "session_id": result.get("session_id"),
                "data": {
                    "clarification_message": result.get("clarification_message"),
                    "missing_fields": result.get("missing_fields", []),
                }
            }

        logger.log_result(request_id, "success", len(questions), total_ms)

        return {
            "code": 0,
            "message": "success",
            "request_id": request_id,
            "session_id": result.get("session_id"),
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

    except Exception as e:
        circuit.record_failure()
        logger.log_result(request_id, "error", error=str(e))

        return {
            "code": 500,
            "message": f"生成失败: {str(e)}",
            "request_id": request_id,
            "session_id": session_id,
        }


@app.post("/api/exam/generate/stream")
async def generate_exam_stream(req: GenerateExamRequest, request: Request):
    """
    流式生成试卷，返回推理过程
    """
    request_id = request.state.request_id
    logger = get_logger_instance()
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

        try:
            async for event in agent.stream_run(req.user_input, params, session_id=session_id):
                if first:
                    first = False
                    event["is_first"] = True
                event["request_id"] = request_id
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'error': str(e), 'request_id': request_id}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'event': 'done', 'request_id': request_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-ID": request_id,
        }
    )


@app.post("/api/exam/clarify")
async def clarify(req: ClarifyRequest, request: Request):
    """单轮追问"""
    request_id = request.state.request_id
    agent = get_agent()

    try:
        result = await agent.arun(
            req.user_input,
            req.current_params or {},
            session_id=req.session_id
        )

        if result.get("status") == "clarifying":
            return {
                "code": 1,
                "message": result.get("clarification_message"),
                "request_id": request_id,
                "session_id": result.get("session_id"),
                "missing_fields": result.get("missing_fields", []),
            }

        return {
            "code": 0,
            "message": "参数已完整",
            "request_id": request_id,
            "session_id": result.get("session_id"),
            "extracted_params": {
                "subject": result.get("subject"),
                "grade": result.get("grade"),
                "chapters": result.get("chapters"),
                "scene": result.get("scene"),
            }
        }

    except Exception as e:
        return {
            "code": 500,
            "message": f"追问失败: {str(e)}",
            "request_id": request_id,
        }


@app.post("/api/exam/adapt")
async def adapt_question(req: AdaptQuestionRequest, request: Request):
    """
    改编题目

    接收一道原题目，调用 question-adaptor skill 进行改编，
    保持知识点不变，改变数值/情境/难度等。
    """
    request_id = request.state.request_id
    logger = get_logger_instance()
    agent = get_agent()

    params = {"original_question": req.original_question}

    try:
        start_time = time.time()
        result = await agent.arun(
            "改编题目", params, session_id=req.session_id
        )
        total_ms = (time.time() - start_time) * 1000

        adapted = result.get("adapted_question", {})

        logger.log_result(request_id, "success", 1, total_ms)

        return {
            "code": 0,
            "message": "改编完成",
            "request_id": request_id,
            "session_id": result.get("session_id"),
            "data": {
                "original_question": req.original_question,
                "adapted_question": adapted,
            },
        }

    except Exception as e:
        logger.log_result(request_id, "error", error=str(e))
        return {
            "code": 500,
            "message": f"改编失败: {str(e)}",
            "request_id": request_id,
        }


# ============ 会话管理接口 ============

@app.get("/api/sessions")
async def list_sessions():
    """列出所有会话"""
    agent = get_agent()
    sessions = agent.list_sessions()
    return {"code": 0, "data": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话"""
    agent = get_agent()
    session = agent.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"code": 0, "data": session}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    agent = get_agent()
    agent.clear_session(session_id)
    return {"code": 0, "message": "会话已删除"}


# ============ 系统接口 ============

@app.get("/api/health")
async def health_check():
    """详细健康检查"""
    circuit = get_circuit_breaker()
    return {
        "status": "ok",
        "circuit_breaker": circuit.get_state(),
    }


@app.post("/api/circuit-breaker/reset")
async def reset_circuit_breaker():
    """手动重置熔断器"""
    circuit = get_circuit_breaker()
    circuit.failures = 0
    circuit.state = "closed"
    return {"code": 0, "message": "熔断器已重置", "state": circuit.get_state()}


@app.get("/api/skills")
async def list_skills():
    """列出所有 Skill"""
    agent = get_agent()
    return {"code": 0, "data": agent.list_skills()}


@app.post("/api/skills/reload")
async def reload_skills():
    """热更新 Skill"""
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
        reload=False
    )
