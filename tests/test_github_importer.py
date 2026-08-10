import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from edu_agent.tools.course_kb import CourseKnowledgeBase  # noqa: E402
from edu_agent.tools.github_importer import (  # noqa: E402
    GitHubImportError,
    _parse_repo_url,
    import_github_repo,
)


def test_parse_valid_github_urls():
    assert _parse_repo_url("https://github.com/owner/repo") == ("owner", "repo")
    assert _parse_repo_url("https://github.com/owner/repo.git") == ("owner", "repo")
    assert _parse_repo_url("  https://github.com/a-b/c_d/  ") == ("a-b", "c_d")


def test_parse_rejects_invalid_or_injection_urls():
    bad_urls = [
        "https://evil.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/extra",
        "https://github.com/owner/repo; rm -rf /tmp/x",
        "https://github.com/owner/repo?x=1",
        "git@github.com:owner/repo.git",
        "ftp://github.com/owner/repo",
        "",
        "not a url",
    ]
    for url in bad_urls:
        with pytest.raises(GitHubImportError):
            _parse_repo_url(url)


def test_import_github_repo_rejects_invalid_url_before_network(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("非法 URL 不应触发网络调用")

    monkeypatch.setattr("subprocess.run", _fail)
    with pytest.raises(GitHubImportError, match="仅支持"):
        import_github_repo("https://evil.com/a/b")


def test_load_github_repo_integrates_docs_into_kb(monkeypatch):
    fake_docs = {
        "README.md": "# 示例仓库\n\n## 快速开始\n\n先安装依赖，再运行。",
        "docs/guide.md": "# 使用指南\n\n## 常见问题\n\n遇到报错先看日志。",
    }

    def _fake_import(url, **kwargs):
        assert "github.com" in url
        return dict(fake_docs)

    monkeypatch.setattr(
        "edu_agent.tools.course_kb.import_github_repo", _fake_import
    )

    kb = CourseKnowledgeBase()
    added = kb.load_github_repo("https://github.com/owner/repo")

    assert added >= 2
    doc_titles = {chunk.doc_title for chunk in kb.chunks}
    assert "README.md" in doc_titles
    assert "docs/guide.md" in doc_titles
    # 导入后可直接检索
    hits = kb.search("怎么安装依赖")
    assert hits
    assert any("安装" in hit.heading_path or "安装" in hit.text for hit in hits)


def test_load_github_repo_propagates_import_error(monkeypatch):
    def _fail(url, **kwargs):
        raise GitHubImportError("git clone 失败")

    monkeypatch.setattr(
        "edu_agent.tools.course_kb.import_github_repo", _fail
    )
    kb = CourseKnowledgeBase()
    with pytest.raises(GitHubImportError, match="git clone"):
        kb.load_github_repo("https://github.com/owner/repo")
