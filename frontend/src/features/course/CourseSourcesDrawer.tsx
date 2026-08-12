import { useEffect, useRef, useState } from "react";
import { Github, Globe, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useApi } from "../../api/ApiProvider";
import type { CourseSource, SourceSearchResult } from "../../api/types";
import { subscribeCourseSourcesOpen } from "./courseSourcesEvents";
import "./course-sources.css";

/** CourseSourcesDrawer：课程资料的临时抽屉（Web / GitHub / Internet Search）。
 * - 同一抽屉被两个入口打开（Sidebar 课程工作区「课程资料」、CourseHeader「···」）；
 * - Esc / 关闭按钮 / 背景点击均可关闭；
 * - 添加链接（自动判 web/github）；搜索互联网（多选导入）；已添加列表（删除 / failed 重试）；
 * - 每个资料状态独立（importing / ready / failed）。 */
export function CourseSourcesDrawer() {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [sources, setSources] = useState<CourseSource[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [urlInput, setUrlInput] = useState("");
  const [addingUrl, setAddingUrl] = useState(false);
  const [urlError, setUrlError] = useState("");

  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [results, setResults] = useState<SourceSearchResult[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [importing, setImporting] = useState(false);

  const closeRef = useRef<HTMLButtonElement>(null);

  const resetTransient = () => {
    setUrlInput("");
    setQuery("");
    setResults([]);
    setSelected(new Set());
    setError("");
    setUrlError("");
    setSearchError("");
  };

  const close = () => {
    setOpen(false);
    setCourseId(null);
    resetTransient();
  };

  const loadSources = (cid: string) => {
    setLoading(true);
    setError("");
    api
      .listCourseSources(cid)
      .then((list) => {
        setSources(list);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "加载失败");
        setLoading(false);
      });
  };

  // 订阅 open 事件（两个入口共用）
  useEffect(
    () =>
      subscribeCourseSourcesOpen((cid) => {
        setCourseId(cid);
        setOpen(true);
        resetTransient();
        loadSources(cid);
        setTimeout(() => closeRef.current?.focus(), 0);
      }),
    [api],
  );

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open || !courseId) return null;

  const addUrl = async () => {
    const url = urlInput.trim();
    if (!url) {
      setUrlError("请输入链接");
      return;
    }
    setAddingUrl(true);
    setUrlError("");
    try {
      await api.addCourseSource(courseId, { url });
      setUrlInput("");
      loadSources(courseId);
    } catch (e) {
      setUrlError(e instanceof Error ? e.message : "添加失败");
    } finally {
      setAddingUrl(false);
    }
  };

  const removeSource = async (sourceId: string) => {
    try {
      await api.deleteCourseSource(courseId, sourceId);
      loadSources(courseId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  };

  const retrySource = async (url: string) => {
    try {
      await api.addCourseSource(courseId, { url });
      loadSources(courseId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重试失败");
    }
  };

  const runSearch = async () => {
    const q = query.trim();
    if (!q) {
      setSearchError("请输入搜索关键词");
      return;
    }
    setSearching(true);
    setSearchError("");
    setResults([]);
    setSelected(new Set());
    try {
      const list = await api.searchCourseSources(courseId, q, 5);
      setResults(list);
      setSelected(new Set(list.map((r) => r.url)));
    } catch (e) {
      setSearchError(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setSearching(false);
    }
  };

  const importSelected = async () => {
    const chosen = results.filter((r) => selected.has(r.url));
    if (chosen.length === 0) return;
    setImporting(true);
    try {
      for (const r of chosen) {
        await api.addCourseSource(courseId, { url: r.url, title: r.title });
      }
      setQuery("");
      setResults([]);
      setSelected(new Set());
      loadSources(courseId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const toggleSelect = (url: string) => {
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(url)) n.delete(url);
      else n.add(url);
      return n;
    });
  };

  return (
    <div className="cs-drawer-backdrop" onClick={close}>
      <div
        className="cs-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="课程资料"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cs-drawer-header">
          <h2 className="cs-drawer-title">课程资料</h2>
          <button ref={closeRef} type="button" className="cs-close" onClick={close} aria-label="关闭">
            <X size={18} aria-hidden />
          </button>
        </div>

        <div className="cs-drawer-body">
          {/* 添加链接 */}
          <div className="cs-block">
            <div className="cs-block-title">添加链接</div>
            <div className="cs-url-row">
              <input
                className="cs-input"
                placeholder="https://… （网页或 GitHub 仓库）"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addUrl();
                }}
              />
              <button
                type="button"
                className="cs-btn primary"
                onClick={addUrl}
                disabled={addingUrl}
              >
                <Plus size={15} aria-hidden /> {addingUrl ? "添加中…" : "添加"}
              </button>
            </div>
            {urlError && <div className="cs-error">{urlError}</div>}
          </div>

          {/* 搜索互联网 */}
          <div className="cs-block">
            <div className="cs-block-title">搜索互联网（可选导入）</div>
            <div className="cs-url-row">
              <input
                className="cs-input"
                placeholder="搜索关键词…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch();
                }}
              />
              <button
                type="button"
                className="cs-btn"
                onClick={runSearch}
                disabled={searching}
              >
                <Search size={15} aria-hidden /> {searching ? "搜索中…" : "搜索"}
              </button>
            </div>
            {searchError && <div className="cs-error">{searchError}</div>}
            {results.length > 0 && (
              <div className="cs-results">
                {results.map((r) => (
                  <label key={r.url} className="cs-result">
                    <input
                      type="checkbox"
                      checked={selected.has(r.url)}
                      onChange={() => toggleSelect(r.url)}
                    />
                    <span className="cs-result-text">
                      <span className="cs-result-title">{r.title}</span>
                      <span className="cs-result-snippet">{r.snippet}</span>
                      <span className="cs-result-url">{r.url}</span>
                    </span>
                  </label>
                ))}
                <button
                  type="button"
                  className="cs-btn primary"
                  onClick={importSelected}
                  disabled={importing || selected.size === 0}
                >
                  {importing ? "导入中…" : `导入选中（${selected.size}）`}
                </button>
              </div>
            )}
          </div>

          {/* 已添加 */}
          <div className="cs-block">
            <div className="cs-block-title">已添加资料</div>
            {loading && <div className="cs-hint">加载中…</div>}
            {error && !loading && <div className="cs-error">{error}</div>}
            {!loading && !error && sources.length === 0 && <div className="cs-hint">还没有资料</div>}
            <ul className="cs-source-list">
              {sources.map((s) => (
                <li key={s.source_id} className={`cs-source cs-source-${s.status}`}>
                  <span className="cs-source-icon" aria-hidden>
                    {s.source_type === "github" ? <Github size={15} /> : <Globe size={15} />}
                  </span>
                  <span className="cs-source-main">
                    <span className="cs-source-title">{s.title}</span>
                    <span className="cs-source-url">{s.source_url}</span>
                    <span className={`cs-badge cs-badge-${s.status}`}>
                      {s.status === "importing"
                        ? "导入中"
                        : s.status === "ready"
                          ? `已就绪（${s.chunk_count} 块）`
                          : "失败"}
                    </span>
                    {s.status === "failed" && s.error_message && (
                      <span className="cs-source-err">{s.error_message}</span>
                    )}
                  </span>
                  <span className="cs-source-actions">
                    {s.status === "failed" && (
                      <button
                        type="button"
                        className="cs-icon-btn"
                        title="重试"
                        aria-label="重试"
                        onClick={() => retrySource(s.source_url)}
                      >
                        <RefreshCw size={15} aria-hidden />
                      </button>
                    )}
                    <button
                      type="button"
                      className="cs-icon-btn danger"
                      title="删除"
                      aria-label="删除"
                      onClick={() => removeSource(s.source_id)}
                    >
                      <Trash2 size={15} aria-hidden />
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
