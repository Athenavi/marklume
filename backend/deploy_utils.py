import logging
import os
import re
import shutil
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Optional

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
PAGES_DIR = BASE_DIR / "pages"
TEMPLATES_DIR = BASE_DIR / "frontend" / "templates"
STATIC_DIR = BASE_DIR / "frontend" / "static"
CLONE_CACHE_DIR = BASE_DIR / ".cache" / "clone"


def get_github_username(token: str) -> str:
    """通过 GitHub token 获取用户名"""
    headers = {"Authorization": f"token {token}"}
    resp = requests.get("https://api.github.com/user", headers=headers, verify=VERIFY)
    if resp.status_code != 200:
        raise RuntimeError("无法获取 GitHub 用户信息，请检查 Token 是否有效。")
    return resp.json()["login"]


def _extract_html_title(html_path: Path) -> str:
    """
    从 HTML 文件中提取 <title> 标签内容
    
    Args:
        html_path: HTML 文件路径
    
    Returns:
        title 内容，提取失败时返回文件名（不含扩展名）
    """
    try:
        content = html_path.read_text(encoding="utf-8")
        match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    except Exception as e:
        logger.warning(f"读取 HTML 文件失败 {html_path}: {e}")
    return html_path.stem


def _load_pages() -> list[dict]:
    """
    扫描 pages 目录，加载所有 HTML 页面信息
    
    Returns:
        页面信息列表，每项包含 filename 和 title
    """
    pages = []
    if not PAGES_DIR.exists():
        return pages
    
    for html_file in sorted(PAGES_DIR.glob("*.html")):
        title = _extract_html_title(html_file)
        pages.append({
            "filename": html_file.name,
            "title": title,
        })
        logger.debug(f"发现页面: {html_file.name} -> {title}")
    
    logger.info(f"加载了 {len(pages)} 个自定义页面")
    return pages


def generate_static_site(
    site_title: str,
    site_link: str,
    backup_dir: Path = None,
    with_manifest: bool = True,
    giscus_config: Optional[dict] = None
) -> tuple[Path, Optional[dict]]:
    """
    生成静态站点到临时目录
    
    Args:
        site_title: 站点标题
        site_link: 站点链接
        backup_dir: 备份目录（可选）
        with_manifest: 是否生成 manifest 文件
        giscus_config: Giscus 评论配置（可选，为 None 或 enabled=False 时不启用）
    
    Returns:
        (站点目录路径, manifest 字典)
    """
    output_dir = Path(tempfile.mkdtemp(prefix="marklume_site_"))

    # 复制静态资源
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, output_dir / "static", dirs_exist_ok=True)

    # 加载文章（递归扫描子目录，支持分类）
    articles = []
    categories = OrderedDict()
    if ARCHIVE_DIR.exists():
        for idx, md_file in enumerate(sorted(ARCHIVE_DIR.glob("**/*.md")), start=1):
            title = md_file.stem
            raw_content = md_file.read_text(encoding="utf-8")
            stat = md_file.stat()
            
            # 提取分类：从 archive 的相对路径中获取第一级子目录名
            rel_path = md_file.relative_to(ARCHIVE_DIR)
            parts = list(rel_path.parts)
            category = parts[0] if len(parts) > 1 else ""
            
            # 分类 URL
            if category:
                category_url = f"/cate/{category}/{idx}"
            else:
                category_url = f"/articles/{idx}"
            
            art = {
                "id": idx,
                "title": title,
                "content": raw_content,
                "created_at": datetime.fromtimestamp(stat.st_ctime),
                "updated_at": datetime.fromtimestamp(stat.st_mtime),
                "category": category,
                "category_url": category_url,
            }
            articles.append(art)
            
            # 按分类分组
            if category not in categories:
                categories[category] = []
            categories[category].append(art)

    # 加载自定义页面
    pages = _load_pages()
    
    # 复制 pages 目录下的 HTML 文件到输出目录
    if pages:
        pages_out_dir = output_dir / "pages"
        pages_out_dir.mkdir(exist_ok=True)
        for page in pages:
            src = PAGES_DIR / page["filename"]
            shutil.copy2(src, pages_out_dir / page["filename"])
        logger.info(f"已复制 {len(pages)} 个自定义页面到站点")

    # 模板引擎
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    env.globals["site_title"] = site_title
    env.globals["site_link"] = site_link
    # 将 giscus 配置注入模板全局上下文
    env.globals["giscus"] = giscus_config if (giscus_config and giscus_config.get("enabled")) else None

    # 构造一个假 request，避免模板中访问出错
    class FakeRequest:
        cookies = {}

    fake_request = FakeRequest()

    # 首页（传入分类分组数据）
    index_template = env.get_template("index.html")
    index_html = index_template.render(
        request=fake_request, articles=articles, categories=categories, pages=pages, is_admin=False
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    # 文章页（按分类生成目录结构）
    article_template = env.get_template("article.html")
    for art in articles:
        art_html = article_template.render(request=fake_request, article=art, is_admin=False)
        if art["category"]:
            # 有分类：cate/{catename}/{id}.html
            art_out_dir = output_dir / "cate" / art["category"]
        else:
            # 无分类：articles/{id}.html（保持兼容）
            art_out_dir = output_dir / "articles"
        art_out_dir.mkdir(parents=True, exist_ok=True)
        (art_out_dir / f"{art['id']}.html").write_text(art_html, encoding="utf-8")

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


def _generate_readme_content(site_link: str, diff: 'DiffResult' = None, mode: str = "full") -> str:
    """
    生成仓库 README.md 内容
    
    Args:
        site_link: 站点访问地址
        diff: 差异结果（增量部署时提供，用于展示变更详情）
        mode: 部署模式 ("full" | "incremental")
    
    Returns:
        README.md 的 Markdown 内容
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    mode_label = "全量部署" if mode == "full" else "增量部署"
    
    lines = [
        f"# {site_link.split('//')[1]}",
        "",
        f"> 🚀 由 **[MarkLume](https://github.com/Athenavi/MarkLume)** 自动生成并部署",
        "",
        "---",
        "",
        "## 🌐 站点访问地址",
        "",
        f"[{site_link}]({site_link})",
        "",
        "## 📅 部署信息",
        "",
        "| 项目 | 详情 |",
        "|------|------|",
        f"| 最近部署时间 | `{now}` |",
        f"| 部署模式 | {mode_label} |",
        "",
    ]
    
    # 变更内容
    if diff and diff.has_changes:
        lines.append("## 📝 更新内容")
        lines.append("")
        
        if diff.added:
            lines.append(f"### ➕ 新增 ({len(diff.added)} 个文件)")
            lines.append("")
            for change in diff.added:
                lines.append(f"- `{change.path}`")
            lines.append("")
        
        if diff.modified:
            lines.append(f"### ✏️ 修改 ({len(diff.modified)} 个文件)")
            lines.append("")
            for change in diff.modified:
                lines.append(f"- `{change.path}`")
            lines.append("")
        
        if diff.deleted:
            lines.append(f"### ❌ 删除 ({len(diff.deleted)} 个文件)")
            lines.append("")
            for change in diff.deleted:
                lines.append(f"- `{change.path}`")
            lines.append("")
    elif mode == "full":
        lines.append("## 📝 更新内容")
        lines.append("")
        lines.append("全量部署 — 所有站点文件已重新生成并推送。")
        lines.append("")
    
    lines.extend([
        "---",
        "",
        "*本 README 由 [MarkLume](https://github.com/Athenavi/MarkLume) 自动生成和维护*",
    ])
    
    return "\n".join(lines)


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
    site_link = f"https://{username}.github.io"
    logger.info(f"目标仓库：{repo_full_name}")

    # 2. 检查仓库是否存在，不存在则创建
    if not _repo_exists(github_token, repo_full_name):
        logger.info(f"仓库 {repo_full_name} 不存在，正在创建...")
        _create_repo(github_token, username)  # 仓库名固定为 username.github.io

    # 3. 生成 README.md 并写入站点目录
    readme_content = _generate_readme_content(site_link, mode="full")
    readme_path = site_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("已生成 README.md")

    # 4. 推送站点
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

    # 5. 尝试开启 GitHub Pages
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


def _get_or_create_clone_dir(github_token: str, repo_full_name: str, branch: str) -> tuple[Repo, Path]:
    """
    获取或创建本地克隆缓存目录
    
    如果缓存目录已存在，则执行 git pull 拉取最新代码；
    否则克隆远程仓库。
    
    Args:
        github_token: GitHub Token
        repo_full_name: 仓库全名 (user/repo)
        branch: 目标分支
    
    Returns:
        (Repo 对象, 克隆目录路径)
    """
    repo_url = f"https://{github_token}@github.com/{repo_full_name}.git"
    clone_dir = CLONE_CACHE_DIR / repo_full_name.replace("/", "_")
    
    if clone_dir.exists() and (clone_dir / ".git").exists():
        # 缓存目录已存在，pull 最新代码
        repo = Repo(clone_dir)
        try:
            # 确保 remote URL 包含最新的 token
            repo.git.remote("set-url", "origin", repo_url)
            repo.git.fetch("origin", branch)
            repo.git.checkout(branch)
            repo.git.pull("origin", branch)
            logger.info(f"已从远程拉取最新代码到缓存目录")
        except GitCommandError as e:
            logger.warning(f"拉取远程代码失败，尝试继续使用本地缓存: {e}")
            try:
                repo.git.checkout(branch)
            except GitCommandError:
                pass
    else:
        # 克隆远程仓库
        clone_dir.mkdir(parents=True, exist_ok=True)
        try:
            repo = Repo.clone_from(repo_url, clone_dir, branch=branch)
            logger.info(f"已克隆远程仓库 {repo_full_name} 的 {branch} 分支到缓存目录")
        except GitCommandError:
            # 仓库为空（刚创建），本地初始化并关联远程
            logger.info(f"远程仓库为空，本地初始化缓存目录")
            repo = Repo.init(clone_dir)
            repo.create_remote("origin", repo_url)
    
    repo.config_writer().set_value("user", "name", "MarkLume Deployer").release()
    repo.config_writer().set_value("user", "email", "deployer@marklume.local").release()
    
    return repo, clone_dir


def push_to_github_incremental(
    site_dir: Path,
    github_token: str,
    diff: DiffResult,
    branch: str = BRANCH_TARGET,
    site_link: str = None
) -> dict:
    """
    增量部署到 GitHub
    
    根据 diff 结果，仅提交变化的文件：
    - 使用本地缓存的克隆目录（如果存在则 pull，否则 clone）
    - 新增/修改的文件：复制到克隆目录后 git add
    - 删除的文件：git rm
    
    Args:
        site_dir: 生成好的站点目录（含全部文件）
        github_token: GitHub Token
        diff: 差异结果
        branch: 目标分支
        site_link: 站点访问地址（可选，用于生成 README）
    
    Returns:
        部署结果摘要
    """
    username = get_github_username(github_token)
    repo_full_name = f"{username}/{username}.github.io"
    if not site_link:
        site_link = f"https://{username}.github.io"
    
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
    
    # 获取或创建本地克隆缓存（pull 最新代码而非重新 clone）
    repo, clone_dir = _get_or_create_clone_dir(github_token, repo_full_name, branch)
    
    changed_files = []
    
    # 复制新增和修改的文件到克隆目录，然后 git add
    for change in diff.added + diff.modified:
        src_file = site_dir / change.path
        dst_file = clone_dir / change.path
        if src_file.exists():
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            repo.git.add(change.path)
            changed_files.append(
                f"+{change.path}" if change.change_type.value == "added" else f"~{change.path}"
            )
    
    # 复制并添加 manifest 文件
    manifest_src = site_dir / MANIFEST_FILENAME
    manifest_dst = clone_dir / MANIFEST_FILENAME
    if manifest_src.exists():
        shutil.copy2(manifest_src, manifest_dst)
        repo.git.add(MANIFEST_FILENAME)
    
    # 处理删除的文件：从克隆目录中删除并 git rm
    for change in diff.deleted:
        dst_file = clone_dir / change.path
        if dst_file.exists():
            repo.git.rm(change.path)
            changed_files.append(f"-{change.path}")
    
    # 生成 README.md 并写入克隆目录
    readme_content = _generate_readme_content(site_link, diff=diff, mode="incremental")
    readme_path = clone_dir / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    repo.git.add("README.md")
    logger.info("已更新 README.md")

    # 生成提交消息
    commit_msg = _generate_commit_message(diff)
    
    # 提交（仅提交变更文件，不使用 add -A）
    try:
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
    
    # 推送（不使用 force，保留远程历史）
    try:
        repo.git.push("origin", f"HEAD:{branch}")
        logger.info(f"增量推送成功到 {repo_full_name} 的 {branch} 分支")
    except GitCommandError as e:
        logger.error(f"推送失败：{e}")
        raise RuntimeError("推送到 GitHub 失败，请检查 Token 权限或网络。")
    
    # 开启 Pages
    _enable_pages(github_token, repo_full_name, branch)
    
    return {
        "status": "success",
        "message": f"增量部署成功，共 {len(changed_files)} 个文件变更",
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
    backup_dir: Path = None,
    giscus_config: Optional[dict] = None
) -> dict:
    """
    全量部署（兼容旧逻辑）
    """
    site_dir, manifest = generate_static_site(site_title, site_link, backup_dir, giscus_config=giscus_config)
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
    backup_dir: Path = None,
    giscus_config: Optional[dict] = None
) -> dict:
    """
    智能增量部署
    
    1. 生成站点和 manifest
    2. 获取远程 manifest 并对比
    3. 根据差异执行增量或全量部署
    """
    # 生成站点
    site_dir, local_manifest = generate_static_site(site_title, site_link, backup_dir, giscus_config=giscus_config)
    
    try:
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
        result = push_to_github_incremental(site_dir, github_token, diff, branch, site_link=site_link)
        result["mode"] = "incremental" if diff.has_changes else "skipped"
        
        return result
    finally:
        # 清理生成的临时站点目录
        shutil.rmtree(site_dir, ignore_errors=True)
        logger.info(f"已清理临时站点目录: {site_dir}")
