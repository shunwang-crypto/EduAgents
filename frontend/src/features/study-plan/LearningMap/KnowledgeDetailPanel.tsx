import type { LearningMapNode } from "../../../api/types";
import { STATUS_STYLES } from "./statusStyles";
import { reasonCodeToHuman } from "../presentation/reasonText";
import { evidenceTypeToHuman } from "../presentation/evidenceText";
import { masteryText, confidenceText } from "../presentation/learningMapText";
import { recommendationCopy } from "../presentation/statusText";

interface Props {
  node: LearningMapNode | null;
  allNodes: LearningMapNode[];
  /** 讲解按钮文案（如「开始讲解」「继续讲解」「再次查看讲解」）；null=不显示。 */
  explanationCta?: string | null;
  onStartExplanation?: () => void;
}

export default function KnowledgeDetailPanel({
  node,
  allNodes,
  explanationCta = null,
  onStartExplanation,
}: Props) {
  if (!node) {
    return (
      <div style={{ padding: 16, color: "#94a3b8", fontSize: 13 }}>
        点击左侧节点查看详情。
      </div>
    );
  }
  const st = STATUS_STYLES[node.status];
  const nameOf = (id: string) => allNodes.find((n) => n.id === id)?.name ?? id;
  const prereqName = (id: string) => {
    const pn = allNodes.find((n) => n.id === id);
    return pn ? `${nameOf(id)}（${STATUS_STYLES[pn.status].label}）` : nameOf(id);
  };
  const reco = recommendationCopy(node);

  return (
    <div style={{ padding: 16, fontSize: 13, color: "#1e293b" }}>
      <h3 style={{ margin: "0 0 4px" }}>{node.name}</h3>
      <div style={{ color: "#64748b", fontSize: 12, marginBottom: 8 }}>{node.description}</div>

      {/* §35：知识讲解 CTA（点击节点即可进入讲解，无需回 Plan List） */}
      {explanationCta && (
        <button
          type="button"
          className="ea-button primary"
          style={{ width: "100%", marginBottom: 10 }}
          onClick={onStartExplanation}
        >
          {explanationCta}
        </button>
      )}

      {/* 主信息：掌握度（大）；Confidence 次级（§11） */}
      <Row
        label="掌握度"
        value={
          <span style={{ fontSize: 16, fontWeight: 700 }}>
            {masteryText(node.mastery)}
          </span>
        }
      />
      <Row
        label="评估可信度"
        value={confidenceText(node.confidence)}
      />
      <Row
        label="学习状态"
        value={<span style={{ color: st.color, fontWeight: 600 }}>{st.label}</span>}
      />

      <Section title="前置知识">
        {node.prerequisites.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>无</span>
        ) : (
          node.prerequisites.map((p) => {
            const pn = allNodes.find((n) => n.id === p);
            const ok = pn?.status === "mastered";
            return (
              <div key={p} style={{ color: ok ? "#15803d" : "#b45309" }}>
                {ok ? "✓" : "○"} {prereqName(p)}
              </div>
            );
          })
        )}
      </Section>

      {/* §12：最近学习记录（人类可读，绝不显示内部 event type） */}
      <Section title="最近学习记录">
        {node.recent_evidence.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>暂无</span>
        ) : (
          node.recent_evidence.slice(0, 5).map((ev, i) => (
            <div key={i}>
              {ev.correctness === "correct" ? "✓" : ev.correctness === "incorrect" ? "×" : "○"}{" "}
              {evidenceTypeToHuman(ev.type)}
              {ev.timestamp ? <span style={{ color: "#94a3b8" }}> · {ev.timestamp}</span> : null}
            </div>
          ))
        )}
      </Section>

      {/* §13：易混淆点 */}
      <Section title="可能存在的易混淆点">
        {node.misconceptions.length === 0 ? (
          <span style={{ color: "#94a3b8" }}>暂无</span>
        ) : (
          node.misconceptions.map((m) => (
            <div key={m} style={{ color: "#b45309" }}>⚠ {m}</div>
          ))
        )}
      </Section>

      {/* §14：系统推荐动作（显式判断 status，禁止用 !recommended 推导 mastered） */}
      <Section title="系统建议">
        <div style={{ fontWeight: 600, color: "#1e293b" }}>{reco.title}</div>
        <div style={{ color: "#64748b", fontSize: 12 }}>{reco.detail}</div>
        {node.locked && (
          <div style={{ marginTop: 6 }}>
            建议先学习以下前置知识：
            <ul style={{ margin: "4px 0 0 18px", padding: 0 }}>
              {node.prerequisites
                .filter((p) => allNodes.find((n) => n.id === p)?.status !== "mastered")
                .map((p) => (
                  <li key={p}>{prereqName(p)}</li>
                ))}
            </ul>
          </div>
        )}
      </Section>

      {node.reason_codes.length > 0 && (
        <Section title="为什么推荐这个知识点？">
          <ul style={{ margin: 0, paddingLeft: 18, color: "#475569" }}>
            {node.reason_codes.map((rc) => (
              <li key={rc}>{reasonCodeToHuman(rc)}</li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "3px 0",
        borderBottom: "1px solid #f1f5f9",
      }}
    >
      <span style={{ color: "#64748b" }}>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
      {children}
    </div>
  );
}
