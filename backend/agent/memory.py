"""
会话记忆管理
支持多轮对话的上下文保持
"""
import json
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime


class SessionMemory:
    """
    基于文件的会话记忆

    用法：
    memory = SessionMemory("./sessions")
    session_id = "user_001_conv_001"

    # 保存
    memory.save(session_id, {"messages": [...], "subject": "数学"})

    # 加载
    state = memory.load(session_id)

    # 清除
    memory.clear(session_id)
    """

    def __init__(self, storage_dir: str = "./sessions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, session_id: str) -> Path:
        """获取会话文件路径"""
        # session_id 可能包含特殊字符，转成安全文件名
        safe_name = session_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self.storage_dir / f"{safe_name}.json"

    def save(self, session_id: str, state: dict, metadata: dict = None):
        """
        保存会话状态

        Args:
            session_id: 会话唯一标识
            state: 要保存的状态字典
            metadata: 附加元数据（创建时间、更新时间等）
        """
        path = self._get_path(session_id)

        # 合并元数据
        data = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "state": state,
            "metadata": metadata or {}
        }

        # 如果已存在，合并而不是覆盖
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                # 保留原有的 created_at
                if "metadata" in existing and "created_at" in existing["metadata"]:
                    data["metadata"]["created_at"] = existing["metadata"]["created_at"]
            except Exception:
                pass
        else:
            data["metadata"]["created_at"] = datetime.now().isoformat()

        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> Optional[dict]:
        """
        加载会话状态

        Args:
            session_id: 会话唯一标识

        Returns:
            状态字典，如果会话不存在返回 None
        """
        path = self._get_path(session_id)

        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("state")
        except (json.JSONDecodeError, IOError):
            return None

    def load_with_metadata(self, session_id: str) -> Optional[dict]:
        """
        加载会话状态和元数据

        Returns:
            {"state": {...}, "metadata": {...}}，不存在返回 None
        """
        path = self._get_path(session_id)

        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return None

    def clear(self, session_id: str):
        """清除会话"""
        path = self._get_path(session_id)
        if path.exists():
            path.unlink()

    def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        return self._get_path(session_id).exists()

    def list_sessions(self) -> list[dict]:
        """
        列出所有会话（按更新时间倒序）

        Returns:
            [{"session_id": "...", "updated_at": "...", "preview": {...}}, ...]
        """
        sessions = []

        for path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state = data.get("state", {})
                preview = {
                    "subject": state.get("subject"),
                    "grade": state.get("grade"),
                    "scene": state.get("scene"),
                    "status": state.get("status"),
                }
                sessions.append({
                    "session_id": data.get("session_id"),
                    "updated_at": data.get("updated_at"),
                    "preview": preview,
                    "metadata": data.get("metadata", {})
                })
            except Exception:
                continue

        # 按更新时间倒序
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions

    def generate_id(self) -> str:
        """生成一个新的会话 ID"""
        return str(uuid.uuid4())

    def cleanup(self, max_age_hours: int = 24):
        """
        清理过期会话

        Args:
            max_age_hours: 超过多少小时未更新的会话将被删除
        """
        import time
        now = datetime.now()
        cutoff = now.timestamp() - (max_age_hours * 3600)

        for path in self.storage_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if mtime < cutoff:
                    path.unlink()
            except Exception:
                continue
