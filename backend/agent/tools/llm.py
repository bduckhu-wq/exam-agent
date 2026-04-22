"""
LLM 调用封装
支持 Kimi / DeepSeek / OpenAI 兼容接口
"""
import os
import json
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_moonshot import ChatMoonshot


def create_llm(
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
):
    """创建 LLM 实例"""
    return ChatMoonshot(
        api_key=api_key or os.getenv("MOONSHOT_API_KEY"),
        model=model or os.getenv("MODEL_NAME", "kimi-k2.5"),
        base_url=base_url or os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
    )


def create_deepseek_llm(api_key: Optional[str] = None, model: str = "deepseek-chat"):
    """创建 DeepSeek LLM"""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        api_key=api_key or os.getenv("DEEPSEEK_API_KEY"),
        model=model,
        base_url=os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    )


class ExamLLM:
    """出题 Agent 专用的 LLM 封装"""

    def __init__(self, provider: str = "moonshot"):
        if provider == "deepseek":
            self.llm = create_deepseek_llm()
        else:
            self.llm = create_llm()

    async def ainvoke(self, prompt: str, system_prompt: Optional[str] = None, **kwargs):
        """异步调用 LLM"""
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        return await self.llm.ainvoke(messages, **kwargs)

    def invoke(self, prompt: str, system_prompt: Optional[str] = None, **kwargs):
        """同步调用 LLM"""
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))
        return self.llm.invoke(messages, **kwargs)

    def generate_questions(self, system_prompt: str, params: dict) -> dict:
        """
        生成题目
        params 包含: subject, grade, chapters, question_types, difficulty_ratio, total_questions, additional_notes
        """
        prompt = f"""请根据以下参数生成试卷题目：

学科: {params.get('subject', '未知')}
年级: {params.get('grade', '未知')}
章节: {', '.join(params.get('chapters', []))}
题型: {', '.join(params.get('question_types', ['选择题', '填空题', '解答题']))}
难度比例: {params.get('difficulty_ratio', '3:5:2')}
题量: {params.get('total_questions', 15)}
补充要求: {params.get('additional_notes', '无')}

请严格按照以下 JSON 格式输出，不要输出任何其他内容：
{{
  "title": "试卷标题",
  "total_score": 100,
  "duration": 45,
  "knowledge_points": ["知识点1", "知识点2"],
  "difficulty_ratio": "3:5:2",
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

        response = self.invoke(prompt, system_prompt=system_prompt)
        content = response.content.strip()

        # 尝试解析 JSON
        try:
            # 去掉可能的 markdown 代码块
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "title": params.get("subject", "试卷"),
                "total_score": 0,
                "duration": 45,
                "knowledge_points": [],
                "difficulty_ratio": params.get("difficulty_ratio", "3:5:2"),
                "questions": [],
                "_error": "JSON 解析失败"
            }
