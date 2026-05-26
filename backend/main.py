import asyncio
import logging
import os.path
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
import sys
from pathlib import Path
from configparser import ConfigParser

from fastapi import FastAPI, Request, HTTPException, Form, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .database import (
    init_archive,
    cleanup_cache,
    get_articles,
    create_new_article,
    get_article,
    delete_article_db,
    update_article_db,
)

logger = logging.getLogger(__name__)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ---------- 配置 ----------
ADMIN_KEY_FILE = project_root / "admin_key.txt"
ADMIN_KEY_NAME = "marklume_admin_key"
ADMIN_KEY_EXPIRY = timedelta(days=365 * 10)

# 站点配置（默认值）
SITE_TITLE = "Marklume"
SITE_LINK = "https://github.com/Athenavi/MarkLume"
if os.path.exists("config.ini"):
    config = ConfigParser()
    config.read("config.ini")
    SITE_TITLE = config.get("site", "site_name", fallback=SITE_TITLE)
    SITE_LINK = config.get("site", "site_link", fallback=SITE_LINK)


# ---------- 管理员密钥持久化 ----------
def load_admin_key():
    if ADMIN_KEY_FILE.exists():
        return ADMIN_KEY_FILE.read_text().strip()
    new_key = secrets.token_urlsafe(32)
    ADMIN_KEY_FILE.write_text(new_key)
    logger.info(f"生成新管理员密钥并保存至 {ADMIN_KEY_FILE}")
    return new_key


def save_admin_key(key: str):
    ADMIN_KEY_FILE.write_text(key)


ADMIN_KEY = load_admin_key()
logger.info(f"当前管理员密钥已加载")

# ---------- 密钥验证依赖 ----------
admin_key_scheme = APIKeyCookie(name=ADMIN_KEY_NAME, auto_error=False)


def validate_admin_key(admin_key: str = Depends(admin_key_scheme)):
    if admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的管理员密钥",
        )
    return admin_key


# ---------- 异步数据库包装（避免阻塞事件循环） ----------
async def fetch_articles():
    return await asyncio.to_thread(get_articles)


async def fetch_article(article_id: int):
    return await asyncio.to_thread(get_article, article_id)


async def create_article(title: str, content: str):
    return await asyncio.to_thread(create_new_article, title, content)


async def update_article(article_id: int, title: str, content: str):
    return await asyncio.to_thread(update_article_db, article_id, title, content)


async def remove_article(article_id: int):
    await asyncio.to_thread(delete_article_db, article_id)


# ---------- 应用工厂 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_archive()
    task = asyncio.create_task(periodic_cleanup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))

# 静态文件与模板
base_dir = Path(__file__).parent.parent
static_dir = base_dir / "frontend/static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory="frontend/templates")

# 将站点信息注入所有模板的全局上下文
templates.env.globals["site_title"] = SITE_TITLE
templates.env.globals["site_link"] = SITE_LINK


# ---------- 辅助函数：统一渲染模板，自动携带 request 和 is_admin ----------
def render_template(name: str, request: Request, **kwargs):
    return templates.TemplateResponse(name, {
        "request": request,
        "is_admin": request.cookies.get(ADMIN_KEY_NAME) == ADMIN_KEY,
        **kwargs,
    })


# ---------- 后台缓存清理 ----------
async def periodic_cleanup():
    while True:
        await asyncio.sleep(1800)
        await asyncio.to_thread(cleanup_cache)


# ---------- 解析表单 / JSON 数据的通用依赖 ----------
async def get_article_form_data(request: Request):
    """尝试从表单或 JSON 中提取 title 和 content"""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        title = body.get("title")
        content = body.get("content")
    else:
        form = await request.form()
        title = form.get("title")
        content = form.get("content")
    if not title or not content:
        raise HTTPException(status_code=422, detail="缺少标题或内容")
    return title, content


# ---------- 路由 ----------
@app.get("/")
@app.get("/articles")
async def list_articles(request: Request):
    articles = await fetch_articles()
    return render_template("index.html", request, articles=articles)


@app.get("/articles/new")
async def new_article_form(request: Request, _: str = Depends(validate_admin_key)):
    return render_template("form.html", request, action="/articles")


@app.get("/articles/{article_id}")
async def read_article(article_id: int, request: Request):
    article = await fetch_article(article_id)
    if not article:
        raise HTTPException(status_code=404)
    return render_template("article.html", request, article=article)


@app.get("/articles/{article_id}/edit")
async def edit_article_form(
        article_id: int, request: Request, _: str = Depends(validate_admin_key)
):
    article = await fetch_article(article_id)
    if not article:
        raise HTTPException(status_code=404)
    return render_template("form.html", request, article=article, action=f"/articles/{article_id}")


@app.post("/articles")
async def create_article_route(
        request: Request,
        form_data: tuple = Depends(get_article_form_data),
        _: str = Depends(validate_admin_key),
):
    title, content = form_data
    article = await create_article(title, content)
    return render_template("article.html", request, article=article)


@app.put("/articles/{article_id}")
async def update_article_route(
        article_id: int,
        request: Request,
        form_data: tuple = Depends(get_article_form_data),
        _: str = Depends(validate_admin_key),
):
    title, content = form_data
    article = await update_article(article_id, title, content)
    if not article:
        raise HTTPException(status_code=404)
    return render_template("article.html", request, article=article)


@app.delete("/articles/{article_id}")
async def remove_article_route(
        article_id: int, request: Request, _: str = Depends(validate_admin_key)
):
    await remove_article(article_id)
    articles = await fetch_articles()
    return render_template("partials/article_list.html", request, articles=articles)


# ---------- 管理员密钥页面 ----------
@app.get("/admin/key")
async def get_admin_key_page(request: Request):
    return render_template("admin_key.html", request, new_key=request.session.pop("new_key", None))


@app.post("/admin/login")
async def login_admin(request: Request, key: str = Form(...)):
    if key == ADMIN_KEY:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=ADMIN_KEY_NAME,
            value=key,
            max_age=int(ADMIN_KEY_EXPIRY.total_seconds()),
            httponly=True,
            samesite="Lax",
        )
        return response
    request.session["error"] = "无效的管理员密钥"
    return RedirectResponse(url="/admin/key", status_code=303)


@app.post("/admin/logout")
async def logout_admin():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(ADMIN_KEY_NAME)
    return response


@app.post("/admin/refresh-key")
async def refresh_admin_key(request: Request, _: str = Depends(validate_admin_key)):
    global ADMIN_KEY
    new_key = secrets.token_urlsafe(32)
    save_admin_key(new_key)
    ADMIN_KEY = new_key
    logger.info("管理员密钥已刷新")
    request.session["new_key"] = new_key
    response = RedirectResponse(url="/admin/key", status_code=303)
    response.delete_cookie(ADMIN_KEY_NAME)
    return response
