import { useState } from "react";
import type { LearningMapNode, TutorResponse } from "../../../api/types";
import { useApi } from "../../../api/ApiProvider";
import { masteryText, STATUS_STYLES } from "../LearningMap/statusStyles";

interface Props {
  courseId: string;
  currentKc: LearningMapNode | null;
  onMapChanged: () => void;
}

export default function TutorPanel({ courseId, currentKc, onMapChanged }: Props) {
  const api = useApi();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<TutorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const kcId = currentKc?.id ?? null;

  const send = async (text: string | null) => {
    if (!kcId) {
      setError("请先在学习地图中选择一个知识组件。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await api.tutorTurn(courseId, { kc_id: kcId, message: text });
      setLast(resp);
      onMapChanged(); // 成功后自动刷新 Learning Map
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "请求失败";
      setError(msg);
    } finally {
      setBusy(false);
      setInput("");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
        <strong>智能导师</strong>
        {currentKc && (
          <span style={{ fontSize: 12, color: "#64748b" }}>
            · {currentKc.name}（{masteryText(currentKc.mastery)} / {STATUS_STYLES[currentKc.status].label}）
          </span>
        )}
      </div>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          background: "#f8fafc",
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          padding: 10,
          fontSize: 13,
        }}
      >
        {!kcId && <div style={{ color: "#94a3b8" }}>点击学习地图中的节点开始辅导。</div>}
        {last && (
          <div>
            <span
              style={{
                fontSize: 10,
                background: "#eef2ff",
                color: "#4338ca",
                borderRadius: 6,
                padding: "1px 6px",
                marginRight: 6,
              }}
            >
              {last.teaching_action}
            </span>
            <span style={{ color: "#64748b", fontSize: 11 }}>
              {last.reason_codes.join(", ")}
            </span>
            <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{last.message}</div>
            {last.learner_state_changed && (
              <div style={{ marginTop: 6, fontSize: 11, color: "#15803d" }}>
                学习者状态已更新：掌握度 {masteryText(last.mastery)}，置信度{" "}
                {last.confidence === null ? "?" : `${Math.round(last.confidence * 100)}%`}
              </div>
            )}
          </div>
        )}
      </div>

      {error && <div style={{ color: "#dc2626", fontSize: 12, marginTop: 6 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) send(input.trim() || null);
          }}
          placeholder={last ? "输入你的回答…" : "（开始 / 下一轮教学）"}
          style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: "1px solid #cbd5e1" }}
          disabled={busy || !kcId}
        />
        <button
          onClick={() => send(input.trim() || null)}
          disabled={busy || !kcId}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: "#6366f1",
            color: "#fff",
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "…" : "发送"}
        </button>
      </div>
    </div>
  );
}
