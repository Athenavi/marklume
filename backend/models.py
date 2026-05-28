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
        last_accessed: datetime = None,
        category: str = ""
    ):
        self.id = id
        self.title = title
        self.content = content
        self.created_at = created_at
        self.updated_at = updated_at
        self.file_path = file_path
        self.last_accessed = last_accessed or datetime.now()
        self.category = category

    @property
    def category_url(self) -> str:
        """返回分类路由路径，无分类时返回文章路由"""
        if self.category:
            return f"/cate/{self.category}/{self.id}"
        return f"/articles/{self.id}"

    def __repr__(self):
        return f"<Article id={self.id} title='{self.title}'>"