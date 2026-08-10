"""GitHub 仓库导入器：给定仓库地址，拉取文档内容供知识库建立索引。

用法：
    from edu_agent.tools.github_importer import import_github_repo
    docs = import_github_repo("https://github.com/owner/repo")
    # docs = { "README.md": "...", "docs/guide.md": "..." }

安全设计：
- 仅接受 https://github.com/owner/repo 格式（白名单正则，拒绝任意命令注入）
- 用 subprocess 列表参数调 git（不做 shell），天然防注入
- 临时目录用完即清理；文件数量与单文件大小设上限，防拖垮内存
- 只收集文档类文件（.md/.txt/.rst），默认不导入代码（可按需打开）
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict

_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
_DOC_SUFFIXES = {".md", ".txt", ".rst", ".markdown", ".ipynb"}

DEFAULT_MAX_FILES = 50
DEFAULT_MAX_BYTES = 500 * 1024  # 单文件 500KB
DEFAULT_TIMEOUT_SECONDS = 120


class GitHubImportError(ValueError):
    """GitHub 导入失败（URL 非法 / 拉取失败 / 内容为空）。"""


def _parse_repo_url(url: str) -> tuple[str, str]:
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise GitHubImportError(
            "仅支持 https://github.com/owner/repo 格式的仓库地址。"
        )
    return match.group(1), match.group(2)


def import_github_repo(
    url: str,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, str]:
    """浅克隆仓库到临时目录，读取文档类文件内容，返回 {相对路径: 文本}。"""
    owner, repo = _parse_repo_url(url)
    clone_url = f"https://github.com/{owner}/{repo}.git"

    work_dir = tempfile.mkdtemp(prefix="eduagents_gh_")
    try:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, work_dir],
                check=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "ignore")[-200:]
            raise GitHubImportError(f"git clone 失败：{detail or exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitHubImportError(f"git clone 超时（>{timeout}s）。") from exc

        docs: Dict[str, str] = {}
        root = Path(work_dir)
        for path in sorted(root.rglob("*")):
            if len(docs) >= max_files:
                break
            if not path.is_file():
                continue
            if path.suffix.lower() not in _DOC_SUFFIXES:
                continue
            try:
                if path.stat().st_size > max_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if text.strip():
                rel = str(path.relative_to(root)).replace("\\", "/")
                docs[rel] = text

        if not docs:
            raise GitHubImportError(
                f"仓库 {owner}/{repo} 中未找到可导入的文档文件"
                f"（{', '.join(sorted(_DOC_SUFFIXES))}）。"
            )
        return docs
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
