# Exam Agent

FastAPI + LangGraph + Markdown Skill 的出题 Agent 后端，支持**多轮对话**。

## 技术栈

- **FastAPI**: HTTP 接口
- **LangGraph**: Agent 编排
- **Markdown Skill**: 业务规则层（教研可改）
- **SessionMemory**: 多轮对话上下文管理
- **LLM**: Kimi / DeepSeek（可切换）

## 目录结构

```
backend/
├── main.py                    # FastAPI 入口
├── agent/
│   ├── lead.py               # Lead Agent（主调度）
│   ├── graph.py              # LangGraph 构建
│   ├── nodes.py              # 图节点定义
│   ├── state.py              # 状态定义
│   ├── skill_manager.py       # Markdown Skill 加载器
│   ├── memory.py             # 多轮会话记忆
│   └── tools/
│       └── llm.py            # LLM 调用封装
├── skills/                     # Markdown Skill 文件
│   ├── question-generator.md   # 出题 Skill
│   └── question-adaptor.md    # 改编 Skill
├── sessions/                   # 会话存储（自动创建）
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 API Key
```

```env
MOONSHOT_API_KEY=sk-xxxxx
MOONSHOT_API_BASE=https://api.moonshot.cn/v1
MODEL_NAME=kimi-k2.5
```

### 3. 启动服务

```bash
python main.py
# 或
uvicorn main:app --reload --port 8000
```

## 多轮对话示例

### 第一轮：用户发起请求

```bash
curl -X POST http://localhost:8000/api/exam/generate \
  -H "Content-Type: application/json" \
  -d '{
    "user_input": "帮我出一份数学试卷",
    "subject": "数学"
  }'
```

响应：
```json
{
  "code": 1,
  "message": "需要补充信息",
  "session_id": "a1b2c3d4-...",   # ← 前端保存这个
  "data": {
    "clarification_message": "还需要确认以下信息：年级、章节。\n请告诉我几年级\n请告诉我要考哪些章节",
    "missing_fields": ["grade", "chapters"]
  }
}
```

### 第二轮：用户补充年级

```bash
curl -X POST http://localhost:8000/api/exam/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "a1b2c3d4-...",   # ← 传入上一轮的 session_id
    "user_input": "高一的",
    "subject": "数学"
  }'
```

响应：
```json
{
  "code": 1,
  "session_id": "a1b2c3d4-...",
  "data": {
    "clarification_message": "还需要确认以下信息：章节。\n请告诉我要考哪些章节",
    "missing_fields": ["chapters"]
  }
}
```

### 第三轮：用户补充章节

```bash
curl -X POST http://localhost:8000/api/exam/generate \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "a1b2c3d4-...",
    "user_input": "第三章函数",
    "subject": "数学",
    "grade": "高一"
  }'
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "session_id": "a1b2c3d4-...",
  "data": {
    "title": "高一数学函数练习",
    "total_score": 100,
    "questions": [...]
  }
}
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /` | 健康检查 | 返回已加载的 Skills |
| `POST /api/exam/generate` | 生成试卷 | 支持多轮对话（传 session_id） |
| `POST /api/exam/generate/stream` | 流式生成 | 流式返回推理过程 |
| `POST /api/exam/clarify` | 追问 | 分析用户输入提取参数 |
| `POST /api/exam/adapt` | 改编题目 | 对单题进行改编 |
| `GET /api/sessions` | 列出会话 | 返回所有会话 |
| `GET /api/sessions/{id}` | 获取会话 | 返回指定会话状态 |
| `DELETE /api/sessions/{id}` | 删除会话 | 清除指定会话 |
| `GET /api/skills` | 列出 Skills | 返回所有可用的 Skill |
| `POST /api/skills/reload` | 热更新 | 重新加载 Skills |

## Markdown Skill

在 `skills/` 目录下添加 `.md` 文件即可扩展能力：

```markdown
---
name: my-skill
description: 技能描述
triggerHint: 关键词1,关键词2
tools:
  - tool_name
workflow:
  nodes:
    - id: step1
      name: 步骤1
  edges:
    - from: step1
      to: step2
---

# System Prompt
你的指令...
```

## 对接前端

```typescript
// Vue 项目中 - 多轮对话版本
const API_BASE = 'http://localhost:8000'

// 保存 session_id
let sessionId = null

async function sendMessage(input, params) {
  const response = await fetch(`${API_BASE}/api/exam/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,    // 后续请求传入
      user_input: input,
      ...params
    })
  })

  const result = await response.json()

  // 保存 session_id
  if (result.session_id) {
    sessionId = result.session_id
  }

  return result
}

// 第一轮
await sendMessage('帮我出一份数学试卷', { subject: '数学' })
// 第二轮
await sendMessage('高一的', { subject: '数学' })
// 第三轮
await sendMessage('第三章函数', { subject: '数学', grade: '高一' })
```

## 多轮对话原理

```
┌─────────────────────────────────────────────────────┐
│                    Session Memory                    │
│                                                      │
│  session_001.json                                   │
│  {                                                  │
│    "session_id": "a1b2c3d4-...",                    │
│    "state": {                                       │
│      "messages": [                                  │
│        {"role": "user", "content": "出份数学卷"},  │
│        {"role": "user", "content": "高一的"},      │
│        {"role": "assistant", "content": "还缺章节"} │
│      ],                                             │
│      "subject": "数学",                            │
│      "grade": "高一",                               │
│      "chapters": null                               │
│    }                                                │
│  }                                                  │
└─────────────────────────────────────────────────────┘
```

每次请求传入 `session_id`，Agent 会自动恢复之前的上下文，继续对话。
