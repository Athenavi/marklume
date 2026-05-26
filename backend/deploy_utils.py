import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown
import requests
import urllib3
from git import Repo, GitCommandError
from jinja2 import Environment, FileSystemLoader

from .manifest import (
    generate_manifest,
    save_manifest,
    fetch_remote_manifest,
    compute_diff,
    DiffResult,
    MANIFEST_FILENAME,
)

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


def generate_static_site(
    site_title: str,
    site_link: str,
    backup_dir: Path = None,
    with_manifest: bool = True
) -> tuple[Path, Optional[dict]]:
    """
    生成静态站点到临时目录
    
    Args:
        site_title: 站点标题
        site_link: 站点链接
        backup_dir: 备份目录（可选）
        with_manifest: 是否生成 manifest 文件
    
    Returns:
        (站点目录路径, manifest 字典)
    """
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
    
    # 生成 manifest
    manifest = None
    if with_manifest:
        manifest = generate_manifest(output_dir)
        save_manifest(manifest, output_dir)
    
    if backup_dir:
        shutil.copytree(output_dir, backup_dir)
        logger.info(f"已备份静态站点：{backup_dir}")
    
    return output_dir, manifest


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


def prepare_incremental_deploy(
    github_token: str,
    local_manifest: dict,
    branch: str = BRANCH_TARGET
) -> tuple[str, DiffResult]:
    """
    准备增量部署：获取远程 manifest 并计算差异
    
    Args:
        github_token: GitHub Token
        local_manifest: 本地生成的 manifest
        branch: 目标分支
    
    Returns:
        (仓库全名, 差异结果)
    """
    username = get_github_username(github_token)
    repo_full_name = f"{username}/{username}.github.io"
    
    # 获取远程 manifest
    remote_manifest = fetch_remote_manifest(
        github_token,
        repo_full_name,
        branch,
        verify_ssl=VERIFY
    )
    
    # 计算差异
    diff = compute_diff(local_manifest, remote_manifest)
    
    return repo_full_name, diff


def push_to_github_incremental(
    site_dir: Path,
    github_token: str,
    diff: DiffResult,
    branch: str = BRANCH_TARGET
) -> dict:
    """
    增量部署到 GitHub
    
    根据 diff 结果，仅提交变化的文件：
    - 新增/修改的文件：git add
    - 删除的文件：git rm（如果存在于远程）
    
    Args:
        site_dir: 站点目录
        github_token: GitHub Token
        diff: 差异结果
        branch: 目标分支
    
    Returns:
        部署结果摘要
    """
    username = get_github_username(github_token)
    repo_full_name = f"{username}/{username}.github.io"
    
    # 检查仓库是否存在
    if not _repo_exists(github_token, repo_full_name):
        logger.info(f"仓库 {repo_full_name} 不存在，正在创建...")
        _create_repo(github_token, username)
    
    # 如果没有变化，直接返回
    if not diff.has_changes:
        logger.info("没有文件变更，跳过部署")
        return {
            "status": "skipped",
            "message": "没有文件变更",
            "changes": diff.to_dict()
        }
    
    # 初始化 Git 仓库
    repo_url = f"https://{github_token}@github.com/{repo_full_name}.git"
    repo = Repo.init(site_dir)
    repo.config_writer().set_value("user", "name", "MarkLume Deployer").release()
    repo.config_writer().set_value("user", "email", "deployer@marklume.local").release()
    
    # 尝试拉取远程分支（如果存在）
    try:
        repo.git.fetch(repo_url, branch)
        repo.git.checkout(f"FETCH_HEAD", b=branch)
        logger.info(f"已检出远程分支 {branch}")
    except GitCommandError:
        # 远程分支不存在，创建新分支
        logger.info(f"远程分支 {branch} 不存在，将创建新分支")
    
    # 添加变更文件
    changed_files = []
    
    # 添加新增和修改的文件
    for change in diff.added + diff.modified:
        file_path = Path(site_dir) / change.path
        if file_path.exists():
            repo.git.add(change.path)
            changed_files.append(f"A {change.path}" if change.change_type.value == "added" else f"M {change.path}")
    
    # 始终添加 manifest 文件
    manifest_path = Path(site_dir) / MANIFEST_FILENAME
    if manifest_path.exists():
        repo.git.add(MANIFEST_FILENAME)
    
    # 处理删除的文件（仅记录，实际删除由下次 force push 处理）
    for change in diff.deleted:
        changed_files.append(f"D {change.path}")
    
    # 生成提交消息
    commit_msg = _generate_commit_message(diff)
    
    # 提交
    try:
        repo.git.add(A=True)  # 确保所有文件都被添加
        repo.git.commit(m=commit_msg, allow_empty=False)
        logger.info(f"已提交变更: {len(changed_files)} 个文件")
    except GitCommandError as e:
        if "nothing to commit" in str(e):
            logger.info("没有新的变更需要提交")
            return {
                "status": "skipped",
                "message": "没有新的变更需要提交",
                "changes": diff.to_dict()
            }
        raise
    
    # 推送
    try:
        repo.git.push(repo_url, f"HEAD:{branch}", force=True)
        logger.info(f"增量推送成功到 {repo_full_name} 的 {branch} 分支")
    except GitCommandError as e:
        logger.error(f"推送失败：{e}")
        raise RuntimeError("推送到 GitHub 失败，请检查 Token 权限或网络。")
    
    # 开启 Pages
    _enable_pages(github_token, repo_full_name, branch)
    
    return {
        "status": "success",
        "message": f"增量部署成功，共 {diff.total_changes} 个文件变更",
        "repo": repo_full_name,
        "branch": branch,
        "changes": diff.to_dict()
    }


def _generate_commit_message(diff: DiffResult) -> str:
    """根据差异生成提交消息"""
    parts = []
    
    if diff.added:
        parts.append(f"+{len(diff.added)} 新增")
    if diff.modified:
        parts.append(f"~{len(diff.modified)} 修改")
    if diff.deleted:
        parts.append(f"-{len(diff.deleted)} 删除")
    
    summary = ", ".join(parts) if parts else "无变更"
    
    # 详细列出变更文件（最多10个）
    details = []
    all_changes = diff.added[:3] + diff.modified[:3] + diff.deleted[:3]
    for change in all_changes:
        prefix = {"added": "+", "modified": "~", "deleted": "-"}[change.change_type.value]
        details.append(f"  {prefix} {change.path}")
    
    if len(diff.added) + len(diff.modified) + len(diff.deleted) > 9:
        details.append(f"  ... 及其他 {diff.total_changes - len(all_changes)} 个文件")
    
    message = f"[MarkLume] 增量部署: {summary}\n\n"
    if details:
        message += "\n".join(details)
    
    return message


def full_deploy(
    site_title: str,
    site_link: str,
    github_token: str,
    branch: str = BRANCH_TARGET,
    backup_dir: Path = None
) -> dict:
    """
    全量部署（兼容旧逻辑）
    """
    site_dir, manifest = generate_static_site(site_title, site_link, backup_dir)
    push_to_github(site_dir, github_token, branch)
    
    return {
        "status": "success",
        "message": "全量部署成功",
        "site_dir": str(site_dir)
    }


def incremental_deploy(
    site_title: str,
    site_link: str,
    github_token: str,
    branch: str = BRANCH_TARGET,
    backup_dir: Path = None
) -> dict:
    """
    智能增量部署
    
    1. 生成站点和 manifest
    2. 获取远程 manifest 并对比
    3. 根据差异执行增量或全量部署
    """
    # 生成站点
    site_dir, local_manifest = generate_static_site(site_title, site_link, backup_dir)
    
    if not local_manifest:
        # 无法生成 manifest，回退到全量部署
        logger.warning("无法生成 manifest，执行全量部署")
        push_to_github(site_dir, github_token, branch)
        return {
            "status": "success",
            "mode": "full",
            "message": "全量部署成功（无 manifest）"
        }
    
    # 准备增量部署
    try:
        repo_full_name, diff = prepare_incremental_deploy(github_token, local_manifest, branch)
    except Exception as e:
        logger.warning(f"获取远程 manifest 失败，执行全量部署: {e}")
        push_to_github(site_dir, github_token, branch)
        return {
            "status": "success",
            "mode": "full",
            "message": f"全量部署成功（远程获取失败: {e}）"
        }
    
    # 执行增量部署
    result = push_to_github_incremental(site_dir, github_token, diff, branch)
    result["mode"] = "incremental" if diff.has_changes else "skipped"
    
    return result
