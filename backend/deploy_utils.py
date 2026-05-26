import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import markdown
import requests
import urllib3
from git import Repo, GitCommandError
from jinja2 import Environment, FileSystemLoader

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY = False  # 是否验证 SSL （提高推送的成功率）
BRANCH_TARGET = 'main'  # 目标分支(若您不放心初次提交，可以修改此处创建别的分支进行测试)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
ARCHIVE_DIR = BASE_DIR / "archive"
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"


def get_github_username(token: str) -> str:
    """通过 GitHub token 获取用户名"""
    headers = {"Authorization": f"token {token}"}
    resp = requests.get("https://api.github.com/user", headers=headers, verify=VERIFY)
    if resp.status_code != 200:
        raise RuntimeError("无法获取 GitHub 用户信息，请检查 Token 是否有效。")
    return resp.json()["login"]


def generate_static_site(site_title: str, site_link: str, backup_dir: Path = None) -> Path:
    """生成静态站点到临时目录"""
    output_dir = Path(tempfile.mkdtemp(prefix="marklume_site_"))

    # 复制静态资源
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, output_dir / "static", dirs_exist_ok=True)

    # 加载文章
    articles = []
    if ARCHIVE_DIR.exists():
        for idx, md_file in enumerate(sorted(ARCHIVE_DIR.glob("*.md")), start=1):
            title = md_file.stem
            raw_content = md_file.read_text(encoding="utf-8")
            html_content = markdown.markdown(raw_content, extensions=['fenced_code', 'tables'])
            stat = md_file.stat()
            articles.append({
                "id": idx,
                "title": title,
                "content": html_content,
                "created_at": datetime.fromtimestamp(stat.st_ctime),
                "updated_at": datetime.fromtimestamp(stat.st_mtime),
            })

    # 模板引擎
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    env.globals["site_title"] = site_title
    env.globals["site_link"] = site_link

    # 构造一个假 request，避免模板中访问出错
    class FakeRequest:
        cookies = {}

    fake_request = FakeRequest()

    # 首页
    index_template = env.get_template("index.html")
    index_html = index_template.render(request=fake_request, articles=articles, is_admin=False)
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    # 文章页
    art_dir = output_dir / "articles"
    art_dir.mkdir(exist_ok=True)
    article_template = env.get_template("article.html")
    for art in articles:
        art_html = article_template.render(request=fake_request, article=art, is_admin=False)
        (art_dir / f"{art['id']}.html").write_text(art_html, encoding="utf-8")

    logger.info(f"静态站点已生成：{output_dir}")
    if backup_dir:
        shutil.copytree(output_dir, backup_dir)
        logger.info(f"已备份静态站点：{backup_dir}")
    return output_dir


def push_to_github(site_dir: Path, github_token: str, branch: str = BRANCH_TARGET):
    """
    自动部署到 {用户名}.github.io 仓库。
    - 从 token 获取用户名
    - 仓库名固定为 {username}.github.io
    - 不存在则自动创建（公开仓库）
    """
    # 1. 获取用户名
    username = get_github_username(github_token)
    repo_full_name = f"{username}/{username}.github.io"
    logger.info(f"目标仓库：{repo_full_name}")

    # 2. 检查仓库是否存在，不存在则创建
    if not _repo_exists(github_token, repo_full_name):
        logger.info(f"仓库 {repo_full_name} 不存在，正在创建...")
        _create_repo(github_token, username)  # 仓库名固定为 username.github.io

    # 3. 推送站点
    repo_url = f"https://{github_token}@github.com/{repo_full_name}.git"
    repo = Repo.init(site_dir)
    repo.config_writer().set_value("user", "name", "MarkLume Deployer").release()
    repo.config_writer().set_value("user", "email", "deployer@marklume.local").release()

    repo.git.add(A=True)
    try:
        repo.git.commit(m="Deploy MarkLume site", allow_empty=True)
    except GitCommandError:
        logger.warning("没有变更可提交")

    try:
        repo.git.push(repo_url, f"HEAD:{branch}", force=True)
        logger.info(f"推送成功到 {repo_full_name} 的 {branch} 分支")
    except GitCommandError as e:
        logger.error(f"推送失败：{e}")
        raise RuntimeError("推送到 GitHub 失败，请检查 Token 权限或网络。")

    # 4. 尝试开启 GitHub Pages
    _enable_pages(github_token, repo_full_name, branch)


def _repo_exists(token: str, full_name: str) -> bool:
    headers = {"Authorization": f"token {token}"}
    url = f"https://api.github.com/repos/{full_name}"
    resp = requests.get(url, headers=headers, verify=VERIFY)
    return resp.status_code == 200


def _create_repo(token: str, username: str):
    """创建名为 username.github.io 的公开仓库"""
    headers = {"Authorization": f"token {token}"}
    data = {
        "name": f"{username}.github.io",
        "auto_init": False,
        "private": False,
        "description": "个人博客，由 MarkLume 自动生成"
    }
    resp = requests.post("https://api.github.com/user/repos", json=data, headers=headers, verify=VERIFY)
    if resp.status_code == 201:
        logger.info(f"仓库 {username}/{username}.github.io 创建成功")
    else:
        error = resp.json().get("message", "未知错误")
        raise RuntimeError(f"创建仓库失败：{error}")


def _enable_pages(token: str, full_name: str, branch: str):
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{full_name}/pages"
    # 检查是否已启用
    if requests.get(url, headers=headers, verify=VERIFY).status_code == 200:
        return
    # 启用 Pages，源为指定分支
    data = {"source": {"branch": branch, "path": "/"}}
    resp = requests.post(url, json=data, headers=headers, verify=VERIFY)
    if resp.status_code == 201:
        logger.info(f"已为 {full_name} 开启 Pages，分支 {branch}")
    else:
        logger.warning(f"自动开启 Pages 失败，请手动在仓库设置中选择 {branch} 分支")
