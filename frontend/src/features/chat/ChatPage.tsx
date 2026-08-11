import { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext, useParams, useSearchParams } from "react-router-dom";
import { BookOpen, X } from "lucide-react";
import { useApi } from "../../api/ApiProvider";
import type { ChatMessage, Course, PlanStep } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { InlineError } from "../../components/ui/InlineError";
import { LoadingDots } from "../../components/ui/Loading";
import { CourseHeader } from "../../layout/CourseHeader";
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
  const [historyError, setHistoryError] = useState(false);
  const [sendError, setSendError] = useState("");
  const [retryText, setRetryText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  // 课程 / 会话加载
  useEffect(() => {
    setMessages([]);
    setCourseError(false);
    setHistoryError(false);
    if (courseId) {
      api.getCourse(courseId).then(setCourse).catch(() => setCourseError(true));
      api
        .getChat(courseId, conversationParam)
        .then((conv) => setMessages(conv.messages))
        .catch(() => setHistoryError(true));
    } else {
      setCourse(null);
      api
        .getChat(null, conversationParam)
        .then((conv) => setMessages(conv.messages))
        .catch(() => setHistoryError(true));
    }
  }, [courseId, conversationParam]);

  // ?step= 加载计划步骤
  useEffect(() => {
    setStep(null);
    setStepError("");
    if (courseId && stepParam) {
      api
        .getStep(courseId, stepParam)
        .then(setStep)
        .catch(() => {
          setStep(null);
          setStepError("计划步骤不存在或不属于当前课程");
        });
    }
  }, [courseId, stepParam]);

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

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return;
      const userMsg: ChatMessage = {
        message_id: `local-${Date.now()}`,
        role: "user",
        content: text,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);
      setSendError("");
      stickToBottom.current = true;
      try {
        const reply = await api.chat({
          message: text,
          course_id: courseId ?? null,
          conversation_id: conversationParam ?? null,
          plan_step_id: step?.step_id ?? null,
        });
        const aiMsg: ChatMessage = {
          message_id: reply.message_id,
          role: "assistant",
          content: reply.content,
          created_at: reply.created_at,
        };
        setMessages((prev) => [...prev, aiMsg]);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "发送失败，请重试";
        setSendError(msg);
        setRetryText(text);
      } finally {
        setLoading(false);
      }
    },
    [courseId, loading, step, conversationParam]
  );

  const retryHistory = useCallback(() => {
    setHistoryError(false);
    if (courseId) {
      api.getChat(courseId, conversationParam).then((conv) => setMessages(conv.messages)).catch(() => setHistoryError(true));
    } else {
      api.getChat(null, conversationParam).then((conv) => setMessages(conv.messages)).catch(() => setHistoryError(true));
    }
  }, [courseId, conversationParam]);

  const placeholder = step
    ? `继续问关于 ${step.title} 的问题…`
    : course
      ? `继续问关于 ${course.display_name} 的问题…`
      : "有什么我可以帮你的？";

  return (
    <>
      <CourseHeader course={course} activeView={courseId ? "chat" : "general"} onOpenMobileSidebar={openMobileSidebar} />

      <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
        <div className="chat-content">
          {step && (
            <div className="step-chip">
              <span className="step-chip-icon">
                <BookOpen size={13} aria-hidden />
              </span>
              <span>学习计划 · {step.title}</span>
              <button type="button" className="step-chip-x" onClick={removeStep} aria-label="移除计划上下文">
                <X size={14} aria-hidden />
              </button>
            </div>
          )}
          {stepError && <div className="step-chip step-chip-error">{stepError}</div>}

          {historyError && messages.length === 0 && (
            <InlineError message="无法加载历史消息" onRetry={retryHistory} />
          )}
          {courseError && (
            <InlineError message="无法加载课程" onRetry={() => window.location.reload()} />
          )}

          {messages.length === 0 && !loading && !historyError ? (
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
          {sendError && (
            <InlineError message={sendError} onRetry={retryText ? () => send(retryText) : undefined} />
          )}
        </div>
      </div>

      <div className="composer-wrap">
        <ChatComposer placeholder={placeholder} disabled={loading} onSend={send} />
      </div>
    </>
  );
}
