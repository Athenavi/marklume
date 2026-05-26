"""
Manifest 模块 - 用于增量部署的文件变更跟踪

功能：
1. 计算文件的 SHA256 哈希值
2. 生成站点的 manifest.json（记录所有文件的路径和哈希）
3. 对比本地与远程 manifest，计算变更文件列表
4. 从 GitHub 获取远程已部署的 manifest
"""

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".marklume-manifest.json"
MANIFEST_VERSION = "1.0"


class ChangeType(str, Enum):
    """文件变更类型"""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    UNCHANGED = "unchanged"


@dataclass
class FileEntry:
    """文件条目"""
    path: str
    hash: str
    size: int
    mtime: float


@dataclass
class FileChange:
    """文件变更记录"""
    path: str
    change_type: ChangeType
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None


@dataclass
class DiffResult:
    """差异对比结果"""
    added: list[FileChange]
    modified: list[FileChange]
    deleted: list[FileChange]
    unchanged: list[str]
    
    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)
    
    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)
    
    def to_dict(self) -> dict:
        return {
            "added": [asdict(f) for f in self.added],
            "modified": [asdict(f) for f in self.modified],
            "deleted": [asdict(f) for f in self.deleted],
            "unchanged_count": len(self.unchanged),
            "has_changes": self.has_changes,
            "total_changes": self.total_changes,
        }


def compute_file_hash(file_path: Path) -> str:
    """计算文件的 SHA256 哈希值"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def generate_manifest(site_dir: Path) -> dict:
    """
    为站点目录生成 manifest
    
    返回格式：
    {
        "version": "1.0",
        "generated_at": "2025-01-01T12:00:00",
        "files": {
            "index.html": {"hash": "abc123...", "size": 1234, "mtime": 1234567890.0},
            "articles/1.html": {"hash": "def456...", "size": 5678, "mtime": 1234567890.0},
            ...
        }
    }
    """
    manifest = {
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now().isoformat(),
        "files": {}
    }
    
    site_path = Path(site_dir)
    
    for file_path in site_path.rglob("*"):
        if file_path.is_file():
            # 跳过 manifest 文件本身
            if file_path.name == MANIFEST_FILENAME:
                continue
            
            relative_path = file_path.relative_to(site_path).as_posix()
            stat = file_path.stat()
            
            manifest["files"][relative_path] = {
                "hash": compute_file_hash(file_path),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
    
    logger.info(f"生成 manifest: {len(manifest['files'])} 个文件")
    return manifest


def save_manifest(manifest: dict, site_dir: Path) -> Path:
    """将 manifest 保存到站点目录"""
    manifest_path = Path(site_dir) / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    logger.info(f"Manifest 已保存: {manifest_path}")
    return manifest_path


def load_manifest(manifest_path: Path) -> Optional[dict]:
    """从文件加载 manifest"""
    if not manifest_path.exists():
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_remote_manifest(
    github_token: str,
    repo_full_name: str,
    branch: str = "main",
    verify_ssl: bool = False
) -> Optional[dict]:
    """
    从 GitHub 仓库获取远程 manifest
    
    使用 GitHub API 获取文件内容，而非克隆整个仓库
    """
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.raw"
    }
    
    # 尝试获取 manifest 文件
    url = f"https://api.github.com/repos/{repo_full_name}/contents/{MANIFEST_FILENAME}?ref={branch}"
    
    try:
        resp = requests.get(url, headers=headers, verify=verify_ssl, timeout=10)
        
        if resp.status_code == 404:
            logger.info(f"远程仓库中不存在 manifest 文件，将执行全量部署")
            return None
        
        if resp.status_code != 200:
            logger.warning(f"获取远程 manifest 失败: {resp.status_code}")
            return None
        
        manifest = json.loads(resp.text)
        logger.info(f"成功获取远程 manifest: {len(manifest.get('files', {}))} 个文件")
        return manifest
        
    except requests.RequestException as e:
        logger.warning(f"获取远程 manifest 时发生网络错误: {e}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"解析远程 manifest 失败: {e}")
        return None


def compute_diff(local_manifest: dict, remote_manifest: Optional[dict]) -> DiffResult:
    """
    对比本地和远程 manifest，计算文件变更
    
    返回 DiffResult 包含：
    - added: 新增的文件
    - modified: 修改的文件
    - deleted: 删除的文件
    - unchanged: 未变化的文件路径列表
    """
    added = []
    modified = []
    deleted = []
    unchanged = []
    
    local_files = local_manifest.get("files", {})
    remote_files = remote_manifest.get("files", {}) if remote_manifest else {}
    
    # 检查本地文件（新增或修改）
    for path, local_info in local_files.items():
        if path not in remote_files:
            # 新增文件
            added.append(FileChange(
                path=path,
                change_type=ChangeType.ADDED,
                new_hash=local_info["hash"]
            ))
        elif local_info["hash"] != remote_files[path]["hash"]:
            # 文件已修改
            modified.append(FileChange(
                path=path,
                change_type=ChangeType.MODIFIED,
                old_hash=remote_files[path]["hash"],
                new_hash=local_info["hash"]
            ))
        else:
            # 文件未变化
            unchanged.append(path)
    
    # 检查远程文件（删除）
    for path in remote_files:
        if path not in local_files:
            deleted.append(FileChange(
                path=path,
                change_type=ChangeType.DELETED,
                old_hash=remote_files[path]["hash"]
            ))
    
    result = DiffResult(
        added=added,
        modified=modified,
        deleted=deleted,
        unchanged=unchanged
    )
    
    logger.info(
        f"差异计算完成: +{len(added)} ~{len(modified)} -{len(deleted)} "
        f"(未变化: {len(unchanged)})"
    )
    
    return result


def get_github_username(token: str, verify_ssl: bool = False) -> str:
    """通过 GitHub token 获取用户名"""
    headers = {"Authorization": f"token {token}"}
    resp = requests.get("https://api.github.com/user", headers=headers, verify=verify_ssl)
    if resp.status_code != 200:
        raise RuntimeError("无法获取 GitHub 用户信息，请检查 Token 是否有效。")
    return resp.json()["login"]
