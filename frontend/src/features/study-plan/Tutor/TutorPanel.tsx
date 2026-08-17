import { useState } from "react";
import type { LearningMapNode, TutorResponse } from "../../../api/types";
import { useApi } from "../../../api/ApiProvider";
import { masteryText } from "../LearningMap/statusStyles";
import { teachingActionToHuman } from "../LearningMap/reasonText";

interface Props {
  courseId: string;
  currentKc: LearningMapNode | null;
  allNodes: LearningMapNode[];
  onMapChanged: () => void;
  onStartNextKc?: (kcId: string) => void;
}

export default function TutorPanel({ courseId, currentKc, allNodes, onMapChanged, onStartNextKc }: Props) {
  const api = useApi();
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<TutorResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [masteryDelta, setMasteryDelta] = useState<number | null>(null);

  const kcId = currentKc?.id ?? null;
  // P1-3：locked 节点只允许查看，不允许开始 Tutor。
  const locked = currentKc?.locked ?? false;
  const lockedPrereqs =
    currentKc?.prerequisites ?? [];

  // 是否达到“当前 KC 已掌握、需要用户手动切换到下一步”（P1-4）
  const currentMastered = (currentKc?.mastery ?? 0) >= 0.7;
  const nextKcId = last?.next_recommended_kc ?? null;
  const nextKcNode = allNodes.find((n) => n.id === nextKcId) ?? null;
  const nextKcName = nextKcNode?.name ?? nextKcId ?? "";

  const send = async (text: string | null) => {
    if (!kcId) {
      setError("请先在学习地图中选择一个知识组件。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await api.tutorTurn(courseId, {
        kc_id: kcId,
        message: text,
        // P1-5：answer 必须回传本轮 turn_id，供后端关联教学上下文 / 防重复计分
        turn_id: last?.turn_id ?? null,
      });
      // 计算 mastery 变化反馈（§32：42% → 51% 显示 +9%）
      const prev = masteryOf(last);
      const cur = resp.mastery;
      if (prev !== null && cur !== null) {
        setMasteryDelta(cur - prev);
      } else if (cur !== null) {
        setMasteryDelta(cur);
      } else {
        setMasteryDelta(null);
      }
      setLast(resp);
      onMapChanged(); // 成功后自动刷新 Learning Map（§：学习结果改变路径）
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "本轮教学暂时无法生成");
      setMasteryDelta(null);
    } finally {
      setBusy(false);
      setInput("");
    }
  };

  // P1-4：用户点击“进入下一知识点”才切换，绝不自动偷偷切换 selected node。
  const handleEnterNext = () => {
    if (!nextKcId) return;
    onStartNextKc?.(nextKcId);
    setLast(null);
    setMasteryDelta(null);
    setInput("");
  };

  const lastActionHuman = last ? teachingActionToHuman(last.teaching_action) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* 头部：当前知识点 + 教学策略（§35） */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", flexWrap: "wrap" }}>
        <strong>智能导师</strong>
        {currentKc && (
          <>
            <span style={{ fontSize: 12, color: "#1e293b" }}>
              当前知识点：{currentKc.name}
            </span>
            <span style={{ fontSize: 12, color: "#64748b" }}>
              （{masteryText(currentKc.mastery)}）
            </span>
          </>
        )}
        {lastActionHuman && (
          <span
            style={{
              fontSize: 11,
              background: "#eef2ff",
              color: "#4338ca",
              borderRadius: 6,
              padding: "1px 6px",
            }}
          >
            教学策略：{lastActionHuman} · {last?.teaching_action}
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

        {/* P1-3：locked 节点只能查看，不能 Tutor */}
        {kcId && locked && !last && (
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>🔒 该知识点尚未解锁</div>
            <div style={{ color: "#64748b", marginBottom: 6 }}>
              需要先掌握以下前置知识：
            </div>
            <ul style={{ margin: "0 0 6px 18px", padding: 0 }}>
              {lockedPrereqs.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
            <div style={{ color: "#94a3b8", fontSize: 12 }}>
              请先完成前置知识的学习，再开始本知识点的教学。
            </div>
          </div>
        )}

        {kcId && !locked && !last && (
          <div style={{ color: "#64748b" }}>
            选择一个动作开始：
            <button
              type="button"
              className="ea-button primary"
              style={{ marginTop: 8, display: "block" }}
              disabled={busy}
              onClick={() => void send(null)}
            >
              {busy ? "正在开始…" : "开始学习"}
            </button>
          </div>
        )}

        {last && (
          <div>
            <div style={{ whiteSpace: "pre-wrap" }}>{last.message}</div>
            {last.learner_state_changed && (
              <div style={{ marginTop: 6, fontSize: 11, color: "#15803d" }}>
                学习者状态已更新：掌握度 {masteryText(last.mastery)}，评估可信度{" "}
                {last.confidence === null ? "?" : `${Math.round(last.confidence * 100)}%`}
                {masteryDelta !== null && last.mastery !== null && (
                  <b style={{ color: masteryDelta >= 0 ? "#15803d" : "#dc2626" }}>
                    {" "}
                    {masteryDelta >= 0 ? "+" : ""}
                    {Math.round(masteryDelta * 100)}%
                  </b>
                )}
              </div>
            )}

            {/* P1-4：当前 KC 已掌握 → 由用户点击进入下一步，绝不自动切换 */}
            {currentMastered && nextKcId && nextKcId !== kcId && (
              <div
                style={{
                  marginTop: 8,
                  padding: 8,
                  borderRadius: 8,
                  background: "#f0fdf4",
                  border: "1px solid #86efac",
                }}
              >
                <div style={{ fontWeight: 600, color: "#15803d" }}>
                  {currentKc?.name} 已达到掌握标准（{masteryText(currentKc?.mastery ?? null)}）
                </div>
                <div style={{ color: "#475569", margin: "4px 0" }}>
                  下一步推荐：{nextKcName}
                </div>
                <button
                  type="button"
                  className="ea-button primary"
                  onClick={handleEnterNext}
                >
                  进入下一知识点
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div style={{ color: "#dc2626", fontSize: 12, marginTop: 6 }}>
          {error}
          <button
            type="button"
            className="ea-button"
            style={{ marginLeft: 8, fontSize: 12 }}
            onClick={() => void send(last ? input.trim() || null : null)}
          >
            重试
          </button>
        </div>
      )}

      {/* 输入区：请求期间 disabled + 文案（§38） */}
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) void send(input.trim() || null);
          }}
          placeholder={last ? "输入你的回答…" : "（开始 / 下一轮教学）"}
          style={{ flex: 1, padding: "8px 10px", borderRadius: 8, border: "1px solid #cbd5e1" }}
          disabled={busy || !kcId || locked}
        />
        <button
          onClick={() => void send(input.trim() || null)}
          disabled={busy || !kcId || locked}
          style={{
            padding: "8px 16px",
            borderRadius: 8,
            border: "none",
            background: busy || locked ? "#c7d2fe" : "#6366f1",
            color: "#fff",
            cursor: busy ? "wait" : locked ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "分析中" : "发送"}
        </button>
      </div>
      {busy && (
        <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>正在分析你的回答……</div>
      )}
    </div>
  );
}

function masteryOf(resp: TutorResponse | null): number | null {
  return resp?.mastery ?? null;
}
