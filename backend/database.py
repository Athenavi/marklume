# backend/database.py

import glob
import logging
import os
from datetime import datetime
from datetime import timedelta

from .models import Article

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = []  # 文章数据库
next_id = 1  # 下一个文章ID
CACHE_EXPIRY = timedelta(minutes=30)  # 缓存过期时间（30分钟）
ARCHIVE_DIR = "archive"  # 存档目录


def init_archive():
    """启动时扫描archive目录并初始化文章"""
    global db, next_id

    # 确保archive目录存在
    if not os.path.exists(ARCHIVE_DIR):
        os.makedirs(ARCHIVE_DIR)
        logger.info(f"Created archive directory: {ARCHIVE_DIR}")
        return

    # 扫描所有.md文件
    md_files = glob.glob(os.path.join(ARCHIVE_DIR, "*.md"))
    logger.info(f"Found {len(md_files)} markdown files in archive")

    # 添加文件到数据库（不加载内容）
    for file_path in md_files:
        filename = os.path.basename(file_path)
        title = os.path.splitext(filename)[0]

        # 获取文件元数据
        try:
            created_at = datetime.fromtimestamp(os.path.getctime(file_path))
            updated_at = datetime.fromtimestamp(os.path.getmtime(file_path))
        except OSError:
            created_at = updated_at = datetime.now()

        article = Article(
            id=next_id,
            title=title,
            content="",  # 内容留空，按需加载
            created_at=created_at,
            updated_at=updated_at,
            file_path=file_path,
            last_accessed=datetime.now()
        )
        db.append(article)
        logger.info(f"Added archived article: {title} (ID: {next_id})")
        next_id += 1


def get_articles():
    """获取所有文章（基本元数据）"""
    return [{
        "id": a.id,
        "title": a.title,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "is_archived": bool(a.file_path)
    } for a in db]


def create_new_article(title: str, content: str):
    """创建新文章并保存到文件"""
    global next_id

    # 创建文件名（移除特殊字符）
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    filename = f"{safe_title}.md"

    # 检查文件是否已存在，如果存在则添加日期戳
    now = datetime.now()
    date_suffix = now.strftime("%d%m%y")  # 生成日期后缀，格式为：日月年
    original_file_path = os.path.join(ARCHIVE_DIR, filename)
    file_path = original_file_path

    counter = 1
    while os.path.exists(file_path):
        # 如果文件已存在，则在文件名后添加日期戳，并尝试增加一个计数器，以防止同一日期创建多个文件时发生冲突
        filename = f"{safe_title}_{date_suffix}_{counter}.md"
        file_path = os.path.join(ARCHIVE_DIR, filename)
        counter += 1

    # 写入文件
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except OSError as e:
        logger.error(f"Failed to create article file: {e}")
        raise RuntimeError("Failed to save article")

    article = Article(
        id=next_id,
        title=title,
        content=content,
        created_at=now,
        updated_at=now,
        file_path=file_path,
        last_accessed=now
    )
    db.append(article)
    logger.info(f"Created new article: {title} (ID: {next_id})")
    next_id += 1
    return article



def update_article_db(article_id: int, title: str, content: str):
    """更新文章并保存到文件"""
    for article in db:
        if article.id == article_id:
            article.title = title
            article.content = content
            article.updated_at = datetime.now()
            article.last_accessed = datetime.now()

            # 更新文件
            if article.file_path:
                try:
                    with open(article.file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                except OSError as e:
                    logger.error(f"Failed to update article file: {e}")
                    raise RuntimeError("Failed to update article")

            logger.info(f"Updated article {article_id}: {title}")
            return article
    return None


def delete_article_db(article_id: int):
    """删除文章及其文件"""
    global db

    for article in db[:]:
        if article.id == article_id:
            # 删除文件
            if article.file_path and os.path.exists(article.file_path):
                try:
                    os.remove(article.file_path)
                    logger.info(f"Deleted article file: {article.file_path}")
                except OSError as e:
                    logger.error(f"Failed to delete article file: {e}")

            # 从数据库中移除
            db.remove(article)
            logger.info(f"Deleted article {article_id}")
            return

    logger.warning(f"Article {article_id} not found for deletion")


def cleanup_cache():
    """清理过期的文章缓存"""
    now = datetime.now()
    cleaned = 0

    for article in db:
        # 只清理来自文件的文章内容
        if article.file_path and article.content:
            # 如果超过30分钟未访问且内容已加载
            if now - article.last_accessed > CACHE_EXPIRY:
                article.content = ""  # 清除内容
                cleaned += 1
                logger.debug(f"Cleaned cache for article {article.id}")

    if cleaned:
        logger.info(f"Cleaned {cleaned} article caches")


def get_article(article_id: int):
    """获取文章详情（按需加载内容）"""
    for article in db:
        if article.id == article_id:
            # 按需加载内容
            if article.file_path and not article.content:
                try:
                    with open(article.file_path, 'r', encoding='utf-8') as f:
                        article.content = f.read()
                    logger.info(f"Loaded content for article {article_id} from {article.file_path}")
                except FileNotFoundError:
                    logger.warning(f"Article file missing: {article.file_path}")
                    article.content = "⚠️ 文章文件丢失，请联系管理员"
                except OSError as e:
                    logger.error(f"Error loading content for article {article_id}: {str(e)}")
                    article.content = "⚠️ 文章加载失败，请稍后再试"

            # 更新访问时间
            article.last_accessed = datetime.now()
            return article
    return None
