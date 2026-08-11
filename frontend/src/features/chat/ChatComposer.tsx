import { useEffect, useRef, useState } from "react";

interface Props {
  placeholder: string;
  disabled: boolean;
  onSend: (text: string) => void;
}

/** Composer：固定底部中央，Enter 发送 / Shift+Enter 换行。 */
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
  };

  return (
    <div className="composer">
      <textarea
        ref={taRef}
        rows={1}
        value={text}
        placeholder={placeholder}
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
      <button onClick={submit} disabled={disabled || !text.trim()} title="发送">
        ➤
      </button>
    </div>
  );
}
