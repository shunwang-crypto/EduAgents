import type { PlanBrief } from "../../../api/types";

/** PlanBrief：解释「为什么这样安排学习计划」（第一页能一眼看完，§60/§106）。 */
export default function PlanBriefPanel({ brief }: { brief: PlanBrief | null }) {
  if (!brief) return null;
  // §44/防御：旧数据可能缺失部分字段，统一归一化。
  const b: PlanBrief = {
    ...brief,
    why_this_plan: brief.why_this_plan ?? [],
    critical_path: brief.critical_path ?? [],
    difficulty_hotspots: brief.difficulty_hotspots ?? [],
    known_skills: brief.known_skills ?? [],
    skill_gaps: brief.skill_gaps ?? [],
    unassessed_skills: brief.unassessed_skills ?? [],
    adaptation_rules: brief.adaptation_rules ?? [],
    stage_overview: brief.stage_overview ?? [],
  };
  return (
    <section className="plan-brief">
      <div className="plan-brief-head">
        <span className="plan-brief-eyebrow">你的学习路线</span>
        <h2 className="plan-brief-goal">{b.target_outcome || b.goal}</h2>
      </div>

      {b.why_this_plan.length > 0 && (
        <div className="plan-brief-section">
          <h4>为什么这样安排？</h4>
          <ul className="plan-brief-list">
            {b.why_this_plan.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* §41/§45：关键路径显示人类名称，id 只做 key */}
      {b.critical_path.length > 0 && (
        <div className="plan-brief-section">
          <h4>关键路径</h4>
          <div className="plan-brief-critical-path">
            {b.critical_path.map((kc, i, arr) => (
              <span key={kc.kc_id} className="plan-brief-cp-item">
                {kc.name}
                {i < arr.length - 1 && <span className="plan-brief-cp-arrow">↓</span>}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* §43/§45：已确认掌握 / 建议加强 / 尚待评估 */}
      {b.known_skills.length > 0 && (
        <div className="plan-brief-section">
          <h4>已确认掌握</h4>
          <div className="plan-brief-skills">{b.known_skills.join("、")}</div>
        </div>
      )}
      {b.skill_gaps.length > 0 && (
        <div className="plan-brief-section">
          <h4>建议加强</h4>
          <div className="plan-brief-skills">{b.skill_gaps.join("、")}</div>
        </div>
      )}
      {b.unassessed_skills.length > 0 && (
        <div className="plan-brief-section">
          <h4>尚待评估</h4>
          <div className="plan-brief-skills">{b.unassessed_skills.join("、")}</div>
        </div>
      )}

      {b.difficulty_hotspots.length > 0 && (
        <div className="plan-brief-section">
          <h4>预计难点</h4>
          <ol className="plan-brief-list">
            {b.difficulty_hotspots.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ol>
        </div>
      )}

      {b.adaptation_rules.length > 0 && (
        <div className="plan-brief-section">
          <h4>计划如何调整？</h4>
          <ul className="plan-brief-list">
            {b.adaptation_rules.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {b.time_budget && (
        <div className="plan-brief-meta">⏱ {b.time_budget}</div>
      )}
    </section>
  );
}
