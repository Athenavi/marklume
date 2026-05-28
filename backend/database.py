# backend/database.py

import glob
import logging
import os
import re
import threading
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from typing import Dict, List, Optional

from .models import Article

logger = logging.getLogger(__name__)

# 数据库全局状态（需加锁保护）
_lock = threading.Lock()
_db: List[Article] = []
_next_id: int = 1

CACHE_EXPIRY = timedelta(minutes=30)
ARCHIVE_DIR = "archive"


def _safe_filename(title: str) -> str:
    """将标题转换为安全文件名（仅保留字母数字、空格、连字符、下划线）"""
    return re.sub(r'[^\w\s-]', '_', title).strip()


def _load_content(file_path: str) -> str:
    """读取文件内容，异常时返回错误提示"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Article file missing: {file_path}")
        return "⚠️ 文章文件丢失，请联系管理员"
    except OSError as e:
        logger.error(f"Error loading content for {file_path}: {e}")
        return "⚠️ 文章加载失败，请稍后再试"


def _extract_category(file_path: str) -> str:
    """
    从文件路径中提取分类名称。
    archive/tech/article.md -> "tech"
    archive/article.md -> "" (无分类)
    archive/tech/python/article.md -> "tech" (取第一级子目录)
    """
    rel_path = os.path.relpath(file_path, ARCHIVE_DIR)
    parts = rel_path.replace("\\", "/").split("/")
    if len(parts) > 1:
        return parts[0]
    return ""


def init_archive() -> None:
    """启动时扫描archive目录并初始化文章（支持子目录分类）"""
    global _db, _next_id

    if not os.path.exists(ARCHIVE_DIR):
        os.makedirs(ARCHIVE_DIR)
        logger.info(f"Created archive directory: {ARCHIVE_DIR}")
        return

    # 递归扫描所有 .md 文件（包括子目录）
    md_files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "**", "*.md"), recursive=True))
    logger.info(f"Found {len(md_files)} markdown files in archive")

    with _lock:
        for file_path in md_files:
            filename = os.path.basename(file_path)
            title = os.path.splitext(filename)[0]
            category = _extract_category(file_path)

            try:
                created_at = datetime.fromtimestamp(os.path.getctime(file_path))
                updated_at = datetime.fromtimestamp(os.path.getmtime(file_path))
            except OSError:
                created_at = updated_at = datetime.now()

            article = Article(
                id=_next_id,
                title=title,
                content="",
                created_at=created_at,
                updated_at=updated_at,
                file_path=file_path,
                last_accessed=datetime.now(),
                category=category
            )
            _db.append(article)
            logger.info(f"Added archived article: {title} (ID: {_next_id}, Category: '{category or '无'}')")
            _next_id += 1


def get_articles() -> List[Article]:
    """返回所有文章列表（浅拷贝，避免外部直接修改）"""
    with _lock:
        return list(_db)


def get_categories() -> OrderedDict:
    """
    返回按分类分组的文章字典。
    键为分类名称（空字符串表示无分类），值为该分类下的文章列表。
    保持首次出现的顺序。
    """
    with _lock:
        categories = OrderedDict()
        for article in _db:
            cat = article.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(article)
        return categories


def get_article(article_id: int) -> Optional[Article]:
    """获取单篇文章（按需加载内容）"""
    with _lock:
        for article in _db:
            if article.id == article_id:
                # 按需加载内容
                if article.file_path and not article.content:
                    article.content = _load_content(article.file_path)
                article.last_accessed = datetime.now()
                return article
    return None


def create_new_article(title: str, content: str, category: str = "") -> Article:
    """创建新文章并持久化到文件"""
    global _next_id

    safe_title = _safe_filename(title)
    now = datetime.now()

    # 确定目标目录
    if category:
        target_dir = os.path.join(ARCHIVE_DIR, category)
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = ARCHIVE_DIR

    # 生成不冲突的文件名
    file_path = os.path.join(target_dir, f"{safe_title}.md")
    counter = 1
    with _lock:
        while os.path.exists(file_path):
            filename = f"{safe_title}_{counter}.md"
            file_path = os.path.join(target_dir, filename)
            counter += 1

        # 写入文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except OSError as e:
            logger.error(f"Failed to create article file: {e}")
            raise IOError("无法保存文章文件") from e

        article = Article(
            id=_next_id,
            title=title,
            content=content,
            created_at=now,
            updated_at=now,
            file_path=file_path,
            last_accessed=now,
            category=category
        )
        _db.append(article)
        logger.info(f"Created new article: {title} (ID: {_next_id}, Category: '{category or '无'}')")
        _next_id += 1
        return article


def update_article_db(article_id: int, title: str, content: str) -> Optional[Article]:
    """更新文章标题与内容"""
    with _lock:
        for article in _db:
            if article.id == article_id:
                article.title = title
                article.content = content
                article.updated_at = datetime.now()
                article.last_accessed = datetime.now()

                # 更新对应文件
                if article.file_path:
                    try:
                        with open(article.file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except OSError as e:
                        logger.error(f"Failed to update article file: {e}")
                        raise IOError("无法更新文章文件") from e

                logger.info(f"Updated article {article_id}: {title}")
                return article
    return None


def delete_article_db(article_id: int) -> None:
    """删除文章及其对应文件"""
    with _lock:
        for article in _db[:]:  # 拷贝一份以便安全删除
            if article.id == article_id:
                if article.file_path and os.path.exists(article.file_path):
                    try:
                        os.remove(article.file_path)
                        logger.info(f"Deleted article file: {article.file_path}")
                    except OSError as e:
                        logger.error(f"Failed to delete article file: {e}")
                _db.remove(article)
                logger.info(f"Deleted article {article_id}")
                return
    logger.warning(f"Article {article_id} not found for deletion")


def cleanup_cache() -> None:
    """清理过期的文章内容缓存（仅针对已加载的存档文章）"""
    now = datetime.now()
    with _lock:
        cleaned = 0
        for article in _db:
            if article.file_path and article.content:
                if now - article.last_accessed > CACHE_EXPIRY:
                    article.content = ""
                    cleaned += 1
        if cleaned:
            logger.info(f"Cleaned {cleaned} article caches")