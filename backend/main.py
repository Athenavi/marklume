import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request, HTTPException, Form, Depends, status
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyCookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.database import init_archive, cleanup_cache, get_articles, get_article, create_new_article, \
    update_article_db, delete_article_db

logger = logging.getLogger(__name__)

# 管理员密钥管理
ADMIN_KEY = secrets.token_urlsafe(32)
ADMIN_KEY_NAME = "marklume_admin_key"
ADMIN_KEY_EXPIRY = timedelta(hours=72)

print(f"管理员密钥已生成（本次会话有效）: {ADMIN_KEY}")

# API密钥验证方案
admin_key_scheme = APIKeyCookie(name=ADMIN_KEY_NAME, auto_error=False)


def validate_admin_key(admin_key: str = Depends(admin_key_scheme)):
    """验证管理员密钥"""
    if admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的管理员密钥",
        )
    return admin_key


# 生命周期事件处理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    init_archive()

    # 创建后台清理任务
    task = asyncio.create_task(periodic_cleanup())

    yield  # 应用运行中

    # 关闭时取消任务
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")


async def periodic_cleanup():
    """定期清理缓存"""
    while True:
        await asyncio.sleep(1800)  # 每30分钟清理一次
        cleanup_cache()


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
        raise HTTPException(
            status_code=500,
            detail="无法创建文章，请稍后再试"
        )


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


# 管理员密钥管理路由
@app.get("/admin/key")
async def get_admin_key_page(request: Request):
    """显示管理员密钥页面"""
    return templates.TemplateResponse("admin_key.html", {
        "request": request,
        # "key": ADMIN_KEY,
        "is_admin": request.cookies.get(ADMIN_KEY_NAME) == ADMIN_KEY
    })


@app.post("/admin/login")
async def login_admin(
        request: Request,
        key: str = Form(...)
):
    """设置管理员密钥cookie"""
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
    """清除管理员密钥cookie"""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(ADMIN_KEY_NAME)
    return response
