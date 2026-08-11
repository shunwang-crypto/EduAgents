import { BookOpen } from "lucide-react";

const SUGGESTIONS = [
  "解释一下 Transformer 的 Attention",
  "帮我梳理 Python 数据分析入门路线",
  "Java 多态到底是什么？",
];

interface Props {
  onPick: (text: string) => void;
}

/** Empty State：中央小 Logo + 标题 + 描述 + 最多 3 个建议 chip。 */
export function ChatEmptyState({ onPick }: Props) {
  return (
    <div className="empty-state">
      <span className="empty-state-logo" aria-hidden>
        <BookOpen size={22} />
      </span>
      <h2>今天想学习什么？</h2>
      <p>告诉我你想学习的内容，也可以直接提出任何问题。</p>
      <div className="suggestion-list">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" className="suggestion-chip" onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
