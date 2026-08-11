import { useEffect, useRef, useState } from "react";
import { ArrowUp } from "lucide-react";

interface Props {
  placeholder: string;
  disabled: boolean;
  onSend: (text: string) => void;
}

/** Composer：GPT 风格，底部中央，Enter 发送 / Shift+Enter 换行，ArrowUp 圆形发送。 */
export function ChatComposer({ placeholder, disabled, onSend }: Props) {
  const [text, setText] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (disabled) return;
    taRef.current?.focus();
  }, [disabled]);

  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
    if (taRef.current) {
      taRef.current.style.height = "auto";
    }
  };

  const canSend = Boolean(text.trim()) && !disabled;

  return (
    <div className="composer">
      <div className={`composer-box ${canSend ? "has-content" : ""}`}>
        <textarea
          ref={taRef}
          rows={1}
          value={text}
          placeholder={placeholder}
          aria-label="消息输入框"
          onChange={(e) => {
            setText(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button
          type="button"
          className="composer-send"
          onClick={submit}
          disabled={!canSend}
          title="发送"
          aria-label="发送"
        >
          <ArrowUp size={18} aria-hidden />
        </button>
      </div>
      <div className="composer-footer">AI 生成内容可能存在错误，请结合课程资料判断。</div>
    </div>
  );
}
