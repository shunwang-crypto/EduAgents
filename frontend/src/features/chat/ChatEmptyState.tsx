interface Props {
  suggestions: string[];
  onPick: (text: string) => void;
}

/** Empty State：中央问候 + 最多 3 个 suggestion（不堆卡片）。 */
export function ChatEmptyState({ suggestions, onPick }: Props) {
  return (
    <div className="empty-state">
      <h2>今天想学习什么？</h2>
      <p>告诉我你的目标，我可以帮你创建课程并生成个性化学习计划。</p>
      <div className="suggestion-list">
        {suggestions.map((s) => (
          <button key={s} className="suggestion-chip" onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
