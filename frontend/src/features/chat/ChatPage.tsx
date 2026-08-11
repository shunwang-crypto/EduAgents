import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { ChatMessage, Course } from "../../api/types";
import { ChatComposer } from "./ChatComposer";
import { ChatEmptyState } from "./ChatEmptyState";

const SUGGESTIONS = [
  "我想学习 Python",
  "我准备学习 Java 面向对象",
  "我想学习 Transformer",
];

/** ChatPage：GPT 风格主聊天（有课程 → 课程上下文；无课程 → 普通对话）。 */
export function ChatPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const [course, setCourse] = useState<Course | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]);
    setError("");
    if (courseId) {
      api.getCourse(courseId).then(setCourse).catch(() => setCourse(null));
      api.getChat(courseId).then((conv) => setMessages(conv.messages)).catch(() => undefined);
    } else {
      setCourse(null);
      api.getChat(null).then((conv) => setMessages(conv.messages)).catch(() => undefined);
    }
  }, [courseId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, loading]);

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
        const reply = await api.chat({ message: text, course_id: courseId ?? null });
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
    [courseId, loading]
  );

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
          {messages.length === 0 && !loading ? (
            <ChatEmptyState suggestions={SUGGESTIONS} onPick={send} />
          ) : (
            messages.map((m) => (
              <div key={m.message_id} className={`chat-message ${m.role}`}>
                {m.role === "user" ? (
                  <div className="user-bubble">{m.content}</div>
                ) : (
                  <div>{m.content}</div>
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
        <ChatComposer
          placeholder={
            course
              ? `继续问关于 ${course.display_name} 的问题…`
              : "有什么我可以帮你的？"
          }
          disabled={loading}
          onSend={send}
        />
      </div>
    </div>
  );
}
