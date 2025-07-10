# backend/models.py

from datetime import datetime


class Article:
    """文章模型"""

    def __init__(
            self,
            id: int,
            title: str,
            content: str,
            created_at: datetime,
            updated_at: datetime,
            file_path: str = None,
            last_accessed: datetime = None
    ):
        self.id = id
        self.title = title
        self.content = content
        self.created_at = created_at
        self.updated_at = updated_at
        self.file_path = file_path
        self.last_accessed = last_accessed or datetime.now()
