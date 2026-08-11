import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ChatMessage, Course, PlanStep } from "../../api/types";
import RichMarkdown from "../../components/content/RichMarkdown";
import { ChatComposer } from "./ChatComposer";
import { ChatEmptyState } from "./ChatEmptyState";

const SUGGESTIONS = [
  "我想学习 Python",
  "我准备学习 Java 面向对象",
  "我想学习 Transformer",
];

/** ChatPage：GPT 风格主聊天。
 * 三种上下文：无课程（普通）/ 有课程 / 有课程+计划步骤（?step=）。
 * plan_step 仅作用于当前请求上下文，可随时移除，不永久绑定会话。
 */
export function ChatPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const stepParam = searchParams.get("step");
  const conversationParam = searchParams.get("conversation");

  const [course, setCourse] = useState<Course | null>(null);
  const [step, setStep] = useState<PlanStep | null>(null);
  const [stepError, setStepError] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  // 课程 / 会话加载（?conversation= 指定新对话；否则该课程主会话）
  useEffect(() => {
    setMessages([]);
    setError("");
    if (courseId) {
      api.getCourse(courseId).then(setCourse).catch(() => setCourse(null));
      api
        .getChat(courseId, conversationParam)
        .then((conv) => setMessages(conv.messages))
        .catch(() => undefined);
    } else {
      setCourse(null);
      api
        .getChat(null, conversationParam)
        .then((conv) => setMessages(conv.messages))
        .catch(() => undefined);
    }
  }, [courseId, conversationParam]);

  // ?step= 加载计划步骤（校验归属在 backend；无效则提示并忽略）
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

  useEffect(() => {
    const el = scrollRef.current;
    if (el && typeof el.scrollTo === "function") {
      el.scrollTo({ top: el.scrollHeight });
    }
  }, [messages, loading]);

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
      setError("");
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
        setError(e instanceof Error ? e.message : "发送失败");
      } finally {
        setLoading(false);
      }
    },
    [courseId, loading, step, conversationParam]
  );

  const placeholder = step
    ? `继续问关于 ${step.title} 的问题…`
    : course
      ? `继续问关于 ${course.display_name} 的问题…`
      : "有什么我可以帮你的？";

  return (
    <div className="main">
      <header className="main-header">
        <h1>{course?.display_name ?? "新对话"}</h1>
        {courseId && (
          <Link to={`/courses/${courseId}/plan`} className="btn">
            学习计划
          </Link>
        )}
      </header>

      <div className="main-content" ref={scrollRef}>
        <div className="content-center">
          {/* 计划步骤上下文 Chip（可移除，不永久绑定会话） */}
          {step && (
            <div className="step-chip">
              <span>学习计划 · {step.title}</span>
              <button type="button" className="step-chip-x" onClick={removeStep} aria-label="移除计划上下文">
                ×
              </button>
            </div>
          )}
          {stepError && (
            <div className="step-chip step-chip-error">{stepError}</div>
          )}

          {messages.length === 0 && !loading ? (
            <ChatEmptyState suggestions={SUGGESTIONS} onPick={send} />
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
          {loading && <div className="chat-message assistant">…</div>}
          {error && (
            <div className="chat-message assistant" style={{ color: "var(--danger)" }}>
              {error}
            </div>
          )}
        </div>
      </div>

      <div className="composer-wrap">
        <ChatComposer placeholder={placeholder} disabled={loading} onSend={send} />
      </div>
    </div>
  );
}
