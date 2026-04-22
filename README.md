# exam-agent

FastAPI + LangGraph + Markdown Skill 的出题 Agent 后端，支持**多轮对话**和 **Harness 治理**。

## 技术栈

- **FastAPI**: HTTP 接口
- **LangGraph**: Agent 编排
- **Markdown Skill**: 业务规则层（教研可改）
- **SessionMemory**: 多轮对话上下文管理
- **Harness**: 执行日志 + 异常重试 + 熔断保护
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
│   ├── logger.py             # Harness: 执行日志
│   ├── harness.py            # Harness: 重试 + 熔断
│   └── tools/
│       └── llm.py            # LLM 调用封装
├── skills/                     # Markdown Skill 文件
│   ├── question-generator.md   # 出题 Skill
│   └── question-adaptor.md    # 改编 Skill
├── sessions/                   # 会话存储（自动创建）
├── logs/                       # 执行日志（自动创建）
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

### 第一轮

```bash
curl -X POST http://localhost:8000/api/exam/generate \
  -H "Content-Type: application/json" \
  -d '{"user_input": "帮我出一份数学试卷", "subject": "数学"}'
```

响应（需要补充信息）：
```json
{
  "code": 1,
  "session_id": "a1b2c3d4-...",
  "data": {
    "clarification_message": "还需要确认以下信息：年级、章节",
    "missing_fields": ["grade", "chapters"]
  }
}
```

### 第二轮：传入 session_id

```bash
curl -X POST http://localhost:8000/api/exam/generate \
  -H "Content-Type: application/json" \
  -d '{"session_id": "a1b2c3d4-...", "user_input": "高一的", "subject": "数学"}'
```

## API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `GET /` | 健康检查 | 返回 Skills + 模型 + 熔断状态 |
| `POST /api/exam/generate` | 生成试卷 | 支持多轮对话 |
| `POST /api/exam/generate/stream` | 流式生成 | 流式返回推理过程 |
| `POST /api/exam/clarify` | 追问 | 分析用户输入 |
| `GET /api/sessions` | 列出会话 | 返回所有会话 |
| `GET /api/sessions/{id}` | 获取会话 | 返回指定会话 |
| `DELETE /api/sessions/{id}` | 删除会话 | 清除指定会话 |
| `GET /api/health` | 健康检查 | 熔断器状态 |
| `POST /api/circuit-breaker/reset` | 重置熔断器 | 手动恢复 |
| `GET /api/skills` | 列出 Skills | 返回所有 Skill |
| `POST /api/skills/reload` | 热更新 | 重新加载 Skills |

## Harness 特性

### 1. 执行日志

每个请求都会记录到 `logs/agent_YYYYMMDD.log`：

```
14:30:01 | INFO | [a1b2c3d4] 📥 REQUEST | session=xxx | skill=question-generator | input=帮我出一份...
14:30:01 | INFO | [a1b2c3d4] ▶️  NODE START | clarify
14:30:01 | INFO | [a1b2c3d4] ✅ NODE END | clarify | 50ms | status=ok
14:30:02 | INFO | [a1b2c3d4] ▶️  NODE START | analyze
14:30:02 | INFO | [a1b2c3d4] 🤖 LLM CALL | model=kimi-k2.5 | tokens=200+150 | 800ms
14:30:03 | INFO | [a1b2c3d4] ✅ NODE END | analyze | 1000ms | status=ok
14:30:03 | INFO | [a1b2c3d4] ✅ RESULT | questions=15 | total=2000ms
```

### 2. 异常重试

LLM 调用失败时自动重试，最多 3 次，指数退避（1s → 2s → 4s）。

### 3. 熔断保护

当 LLM 连续失败 5 次，自动熔断（不再调用），60 秒后自动恢复。

手动重置：
```bash
curl -X POST http://localhost:8000/api/circuit-breaker/reset
```

## 对接前端

```typescript
let sessionId = null

async function sendMessage(input, params) {
  const response = await fetch('http://localhost:8000/api/exam/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, user_input: input, ...params })
  })

  const result = await response.json()

  // 保存 session_id
  if (result.session_id) {
    sessionId = result.session_id
  }

  return result
}
```

## GitHub

https://github.com/bduckhu-wq/exam-agent
