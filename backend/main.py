import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
import sys
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Form, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .database import init_archive, cleanup_cache, get_articles, create_new_article, get_article, \
    delete_article_db, update_article_db

logger = logging.getLogger(__name__)
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# ---------- 管理员密钥持久化 ----------
ADMIN_KEY_FILE = project_root / "admin_key.txt"
ADMIN_KEY_NAME = "marklume_admin_key"
# Cookie 有效期设为 10 年（永不过期）
ADMIN_KEY_EXPIRY = timedelta(days=365 * 10)


def load_admin_key():
    """从文件加载密钥，若不存在则生成并保存"""
    if ADMIN_KEY_FILE.exists():
        return ADMIN_KEY_FILE.read_text().strip()
    else:
        new_key = secrets.token_urlsafe(32)
        ADMIN_KEY_FILE.write_text(new_key)
        print(f"已生成新的管理员密钥并保存到 {ADMIN_KEY_FILE}：{new_key}")
        return new_key


def save_admin_key(key: str):
    """将密钥写入文件"""
    ADMIN_KEY_FILE.write_text(key)


# 全局管理员密钥（运行时变量）
ADMIN_KEY = load_admin_key()
print(f"当前管理员密钥已加载（持久化存储）: {ADMIN_KEY}")

# ---------- 密钥验证 ----------
admin_key_scheme = APIKeyCookie(name=ADMIN_KEY_NAME, auto_error=False)


def validate_admin_key(admin_key: str = Depends(admin_key_scheme)):
    """验证管理员密钥（与全局变量比较）"""
    if admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的管理员密钥",
        )
    return admin_key


# ---------- 应用生命周期 ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化数据库
    init_archive()
    # 后台定期清理缓存
    task = asyncio.create_task(periodic_cleanup())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))
base_dir = Path(__file__).parent.parent
static_dir = base_dir / "frontend/static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory="frontend/templates")


async def periodic_cleanup():
    while True:
        await asyncio.sleep(1800)
        cleanup_cache()


# ---------- 文章路由（保持不变） ----------
@app.get("/")
@app.get("/articles")
async def list_articles(request: Request):
    articles = get_articles()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "articles": articles,
        "is_admin": request.cookies.get(ADMIN_KEY_NAME) == ADMIN_KEY
    })


@app.get("/articles/new")
async def new_article_form(
        request: Request,
        _: str = Depends(validate_admin_key)
):
    return templates.TemplateResponse("form.html", {
        "request": request,
        "action": "/articles",
        "is_admin": True
    })


@app.get("/articles/{article_id}")
async def read_article(article_id: int, request: Request):
    article = get_article(article_id)
    if not article:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("article.html", {
        "request": request,
        "article": article,
        "is_admin": request.cookies.get(ADMIN_KEY_NAME) == ADMIN_KEY
    })


@app.get("/articles/{article_id}/edit")
async def edit_article_form(
        article_id: int,
        request: Request,
        _: str = Depends(validate_admin_key)
):
    article = get_article(article_id)
    if not article:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("form.html", {
        "request": request,
        "article": article,
        "action": f"/articles/{article_id}",
        "is_admin": True
    })


@app.post("/articles")
async def create_article(
        request: Request,
        title: str = Form(...),
        content: str = Form(...),
        _: str = Depends(validate_admin_key)
):
    try:
        article = create_new_article(title, content)
        return templates.TemplateResponse("article.html", {
            "request": request,
            "article": article,
            "is_admin": True
        })
    except Exception as e:
        logger.error(f"Article creation failed: {e}")
        raise HTTPException(status_code=500, detail="无法创建文章，请稍后再试")


@app.put("/articles/{article_id}")
async def update_article(
        article_id: int,
        request: Request,
        title: str = Form(...),
        content: str = Form(...),
        _: str = Depends(validate_admin_key)
):
    article = update_article_db(article_id, title, content)
    if not article:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("article.html", {
        "request": request,
        "article": article,
        "is_admin": True
    })


@app.delete("/articles/{article_id}")
async def remove_article(
        article_id: int,
        request: Request,
        _: str = Depends(validate_admin_key)
):
    delete_article_db(article_id)
    articles = get_articles()
    return templates.TemplateResponse("partials/article_list.html", {
        "request": request,
        "articles": articles,
        "is_admin": True
    })


# ---------- 管理员密钥页面（增强） ----------
@app.get("/admin/key")
async def get_admin_key_page(request: Request):
    """显示管理员密钥管理页面（登录后可刷新密钥）"""
    is_admin = request.cookies.get(ADMIN_KEY_NAME) == ADMIN_KEY
    return templates.TemplateResponse("admin_key.html", {
        "request": request,
        "is_admin": is_admin,
        # 新密钥仅在刷新成功后的重定向中临时显示（通过 session）
        "new_key": request.session.pop("new_key", None)
    })


@app.post("/admin/login")
async def login_admin(
        request: Request,
        key: str = Form(...)
):
    """管理员登录，设置长期 Cookie"""
    response = RedirectResponse(url="/", status_code=303)
    if key == ADMIN_KEY:
        expiry = int(ADMIN_KEY_EXPIRY.total_seconds())
        response.set_cookie(
            key=ADMIN_KEY_NAME,
            value=key,
            max_age=expiry,
            httponly=True,
            samesite="Lax"
        )
    else:
        request.session["error"] = "无效的管理员密钥"
        response = RedirectResponse(url="/admin/key", status_code=303)
    return response


@app.post("/admin/logout")
async def logout_admin():
    """退出登录，清除 Cookie"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(ADMIN_KEY_NAME)
    return response


@app.post("/admin/refresh-key")
async def refresh_admin_key(
        request: Request,
        _: str = Depends(validate_admin_key)  # 需要当前有效密钥
):
    """刷新管理员密钥（生成新密钥，更新文件与全局变量）"""
    global ADMIN_KEY
    # 生成新密钥
    new_key = secrets.token_urlsafe(32)
    # 更新文件
    save_admin_key(new_key)
    # 更新运行时变量
    ADMIN_KEY = new_key
    print(f"管理员密钥已刷新：{new_key}")

    # 将新密钥存入 session，以便页面展示（仅一次）
    request.session["new_key"] = new_key
    # 重定向到密钥管理页面，同时清除旧 Cookie（强制重新登录）
    response = RedirectResponse(url="/admin/key", status_code=303)
    response.delete_cookie(ADMIN_KEY_NAME)
    return response