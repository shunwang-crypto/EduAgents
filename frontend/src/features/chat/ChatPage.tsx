import { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { BookOpen, X } from "lucide-react";
import { useApi, ApiError } from "../../api/ApiProvider";
import type { ChatMessage, Course, PlanStep } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { InlineError } from "../../components/ui/InlineError";
import { LoadingDots } from "../../components/ui/Loading";
import { CourseHeader } from "../../layout/CourseHeader";
import { useLearningNav } from "../../app/useLearningNav";
import { ChatComposer } from "./ChatComposer";
import { ChatEmptyState } from "./ChatEmptyState";
import "./chat.css";

interface OutletCtx {
  openMobileSidebar: () => void;
}

/** ChatPage：GPT 风格主聊天（无课程 / 有课程 / 有课程+计划步骤）。
 * 只负责页面内容（header 由 CourseHeader 提供，workspace 由 AppShell 提供）。 */
export function ChatPage() {
  const api = useApi();
  const nav = useLearningNav();
  const { courseId } = useParams<{ courseId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const stepParam = searchParams.get("step");
  const conversationParam = searchParams.get("conversation");
  const { openMobileSidebar = () => {} } = (useOutletContext<OutletCtx>() ?? {});

  const [course, setCourse] = useState<Course | null>(null);
  const [courseError, setCourseError] = useState(false);
  const [step, setStep] = useState<PlanStep | null>(null);
  const [stepError, setStepError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  // historyError 保存具体错误（ApiError 含 status / dev detail），不再吞掉 404/401/500/网络错误
  const [historyError, setHistoryError] = useState<ApiError | Error | null>(null);
  const [sendError, setSendError] = useState("");
  const [retryText, setRetryText] = useState("");
  const [retryMsgId, setRetryMsgId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  //  stale-async 保护：courseId / conversation 快速切换时，旧响应不许覆盖新页面
  const chatSeq = useRef(0);
  const stepSeq = useRef(0);
  //  scope 代际：仅随 courseId / user(api) 变化；不随 conversationParam 变化，
  //  否则 runChat 自己写回 URL 会误触发 stale 失效（破坏 lastWrittenConvRef 逻辑）。
  //  runChat 在 await 前后比对 scope，过期响应直接丢弃，避免串课污染。
  const scopeSeq = useRef(0);

  // scope 仅在课程/用户切换时自增（与 history 加载 effect 解耦，避免 conversation 写回误触发）
  useEffect(() => {
    scopeSeq.current++;
  }, [courseId, api]);
  // 本组件写回 URL 的 conversation_id：写回后消息已在本地 state，跳过重新加载，
  // 避免 setMessages([]) 清空当前对话（retry/首条消息成功后 user bubble 消失、骨架闪烁）。
  // 初始为 undefined（哨兵）：mount 时 conversationParam 为 null，若用 null 会误判为"自己写回"而跳过首次加载
  const lastWrittenConvRef = useRef<string | null | undefined>(undefined);

  // 课程 / 会话加载（historyLoading 区分加载中与空会话，不闪 Empty State）
  useEffect(() => {
    // conversation 变化由本组件写回 URL 引起：消息已在本地，消费标记并跳过重载
    if (lastWrittenConvRef.current === conversationParam) {
      lastWrittenConvRef.current = null;
      return;
    }
    const seq = ++chatSeq.current;
    setMessages([]);
    setCourseError(false);
    setHistoryError(null);
    setHistoryLoading(true);
    if (courseId) {
      api
        .getCourse(courseId)
        .then((c) => {
          if (seq === chatSeq.current) setCourse(c);
        })
        .catch(() => {
          if (seq === chatSeq.current) setCourseError(true);
        });
    } else {
      setCourse(null);
    }
    api
      .getChat(courseId ?? null, conversationParam)
      .then((conv) => {
        if (seq === chatSeq.current) setMessages(conv.messages);
      })
      .catch((e) => {
        if (seq !== chatSeq.current) return;
        if (import.meta.env.DEV) console.error("[chat] getChat failed", e);
        setHistoryError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (seq === chatSeq.current) setHistoryLoading(false);
      });
  }, [courseId, conversationParam, api]);

  // ?step= 加载计划步骤
  useEffect(() => {
    const seq = ++stepSeq.current;
    setStep(null);
    setStepError("");
    if (courseId && stepParam) {
      api
        .getStep(courseId, stepParam)
        .then((s) => {
          if (seq === stepSeq.current) setStep(s);
        })
        .catch(() => {
          if (seq !== stepSeq.current) return;
          setStep(null);
          setStepError("计划步骤不存在或不属于当前课程");
        });
    }
  }, [courseId, stepParam, api]);

  // 滚动：新消息时贴底；用户上滚查看历史时不强制拉回
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [messages, loading]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  const removeStep = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete("step");
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  // 核心发送（retry 复用：不再 append 新 user bubble）
  const runChat = useCallback(
    async (text: string, userMsgId: string) => {
      const reqScope = scopeSeq.current;
      setLoading(true);
      setSendError("");
      setRetryText("");
      setRetryMsgId(null);
      stickToBottom.current = true;
      try {
        const reply = await api.chat({
          message: text,
          course_id: courseId ?? null,
          conversation_id: conversationParam ?? null,
          plan_step_id: step?.step_id ?? null,
        });
        // 串课保护：发送期间切到别的课程/用户，旧回复不许写消息、改 URL、写错误
        if (reqScope !== scopeSeq.current) return;
        // conversation_id 写回 URL（replace），刷新后恢复同会话；
        // 记录写回值，effect 据此跳过重复加载历史
        if (reply.conversation_id && reply.conversation_id !== conversationParam) {
          lastWrittenConvRef.current = reply.conversation_id;
          const next = new URLSearchParams(searchParams);
          next.set("conversation", reply.conversation_id);
          setSearchParams(next, { replace: true });
        }
        const aiMsg: ChatMessage = {
          message_id: reply.message_id,
          role: "assistant",
          content: reply.content,
          created_at: reply.created_at,
        };
        setMessages((prev) => [...prev, aiMsg]);
      } catch (e) {
        // 串课保护：过期响应的错误也不许污染当前页面
        if (reqScope !== scopeSeq.current) return;
        const msg = e instanceof Error ? e.message : "发送失败，请重试";
        setSendError(msg);
        setRetryText(text);
        setRetryMsgId(userMsgId); // 原 user 消息保留，retry 不重复
      } finally {
        // 仅在仍属于当前 scope 时收尾 loading
        if (reqScope === scopeSeq.current) setLoading(false);
      }
    },
    [courseId, conversationParam, step, searchParams, setSearchParams, api]
  );

  // 首次发送：append user 消息一次
  const send = useCallback(
    (text: string) => {
      if (!text.trim() || loading) return;
      const userMsgId = `local-${Date.now()}`;
      const userMsg: ChatMessage = {
        message_id: userMsgId,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      runChat(text, userMsgId);
    },
    [loading, runChat]
  );

  // 重试：复用已保留的 user 消息，不 append
  const retrySend = useCallback(() => {
    if (!retryText || loading) return;
    runChat(retryText, retryMsgId ?? `local-retry-${Date.now()}`);
  }, [retryText, retryMsgId, loading, runChat]);

  const retryHistory = useCallback(() => {
    setHistoryError(null);
    setHistoryLoading(true);
    api
      .getChat(courseId ?? null, conversationParam)
      .then((conv) => setMessages(conv.messages))
      .catch((e) => {
        if (import.meta.env.DEV) console.error("[chat] getChat retry failed", e);
        setHistoryError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => setHistoryLoading(false));
  }, [courseId, conversationParam, api]);

  // 失效对话（404）：新建 General Chat 会话并离开当前（可能错配的）路由，避免无限 Retry 同一坏 conversation
  const startNewChat = useCallback(async () => {
    try {
      const conv = await api.createConversation(null);
      nav.openGeneralChat(conv.conversation_id, true);
    } catch {
      // 新建失败则保持现状
    }
  }, [api, nav]);

  const placeholder = step
    ? `继续问关于 ${step.title} 的问题…`
    : course
      ? `继续问关于 ${course.display_name} 的问题…`
      : "有什么我可以帮你的？";

  const composerDisabled = loading || courseError;

  return (
    <>
      <CourseHeader course={course} activeView={courseId ? "chat" : "general"} onOpenMobileSidebar={openMobileSidebar} />

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-content">
          {stepError && <div className="step-chip step-chip-error">{stepError}</div>}

          {historyError && messages.length === 0 && !historyLoading && (
            historyError instanceof ApiError && historyError.status === 404 ? (
              <InlineError
                message="该对话不存在或已失效"
                onRetry={startNewChat}
                retryLabel="开始新对话"
              />
            ) : (
              <InlineError message="无法加载历史消息" onRetry={retryHistory} />
            )
          )}
          {courseError && (
            <InlineError message="无法加载课程，请重试" onRetry={() => window.location.reload()} />
          )}

          {historyLoading ? (
            <div className="chat-history-loading" aria-busy="true">
              <div className="chat-loading-row" />
              <div className="chat-loading-row short" />
            </div>
          ) : messages.length === 0 && !loading && !historyError ? (
            <ChatEmptyState onPick={send} />
          ) : (
            messages.map((m) => (
              <div key={m.message_id} className={`chat-message ${m.role}`}>
                {m.role === "user" ? (
                  <div className="user-bubble">{m.content}</div>
                ) : (
                  <RichMarkdown content={m.content} />
                )}
              </div>
            ))
          )}

          {loading && (
            <div className="chat-message assistant">
              <LoadingDots />
            </div>
          )}
          {sendError && <InlineError message={sendError} onRetry={retrySend} />}
        </div>
      </div>

      {!courseError && (
        <div className="composer-wrap">
          {step && (
            <div className="step-chip composer-chip">
              <span className="step-chip-icon">
                <BookOpen size={13} aria-hidden />
              </span>
              <span>学习计划 · {step.title}</span>
              <button type="button" className="step-chip-x" onClick={removeStep} aria-label="移除计划上下文">
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
          <ChatComposer placeholder={placeholder} disabled={composerDisabled} onSend={send} />
        </div>
      )}
    </>
  );
}
