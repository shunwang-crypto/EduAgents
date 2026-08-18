import type { PlanBrief } from "../../../api/types";

/** PlanBrief：解释「为什么这样安排学习计划」（第一页能一眼看完，§60/§106）。 */
export default function PlanBriefPanel({ brief }: { brief: PlanBrief | null }) {
  if (!brief) return null;
  return (
    <section className="plan-brief">
      <div className="plan-brief-head">
        <span className="plan-brief-eyebrow">你的学习路线</span>
        <h2 className="plan-brief-goal">{brief.target_outcome || brief.goal}</h2>
      </div>

      {brief.why_this_plan.length > 0 && (
        <div className="plan-brief-section">
          <h4>为什么这样安排？</h4>
          <ul className="plan-brief-list">
            {brief.why_this_plan.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {brief.critical_path.length > 0 && (
        <div className="plan-brief-section">
          <h4>关键路径</h4>
          <div className="plan-brief-critical-path">
            {brief.critical_path.map((kc, i, arr) => (
              <span key={i} className="plan-brief-cp-item">
                {kc}
                {i < arr.length - 1 && <span className="plan-brief-cp-arrow">↓</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {brief.difficulty_hotspots.length > 0 && (
        <div className="plan-brief-section">
          <h4>预计难点</h4>
          <ol className="plan-brief-list">
            {brief.difficulty_hotspots.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ol>
        </div>
      )}

      {brief.adaptation_rules.length > 0 && (
        <div className="plan-brief-section">
          <h4>计划如何调整？</h4>
          <ul className="plan-brief-list">
            {brief.adaptation_rules.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {brief.time_budget && (
        <div className="plan-brief-meta">⏱ {brief.time_budget}</div>
      )}
    </section>
  );
}
