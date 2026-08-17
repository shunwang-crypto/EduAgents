/** API 类型定义（与 backend FastAPI 对应）。 */

export interface Goal {
  goal_id: string;
  name: string;
  target: string;
  progress: number;
  target_kcs: string[];
}

/** 课程分类（纯组织层，用户自己创建；不拥有任何 Adaptive 数据）。 */
export interface CourseCategory {
  category_id: string;
  name: string;
}

export interface Course {
  course_id: string;
  display_name: string;
  topic: string;
  /** 完整 Active Goal 对象（后端 Active Goal Resolver 的唯一解）。 */
  goal: Goal | null;
  /** 当前课程目标文本；null / "" = 未设置。 */
  current_goal: string | null;
  /** 所属分类（null = 未分类）。 */
  category_id: string | null;
  progress: number;
  plan_summary: string;
  duration_days: number;
  daily_minutes: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface PlanStep {
  step_id: string;
  seq: number;
  stage_id: string;
  stage_title: string;
  stage_order: number;
  kc_id: string;
  title: string;
  description: string;
  learning_objective: string;
  prerequisites: string[];
  difficulty: string;
  minutes: number;
  status: "not_started" | "in_progress" | "completed";
  lesson_markdown: string | null;
  lesson_generated_at: string | null;
}

export interface PlanStage {
  stage_id: string;
  stage_title: string;
  order: number;
  steps: PlanStep[];
}

export interface StudyPlan {
  plan_id: string;
  course_id: string;
  goal_id: string;
  title: string;
  summary: string;
  plan_markdown: string;
  progress: number;
  created_at: string;
  updated_at: string;
  stages: PlanStage[];
  steps: PlanStep[];
}

export interface ChatMessage {
  message_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface Conversation {
  conversation_id: string | null;
  course_id: string | null;
  messages: ChatMessage[];
}

/** 最近对话摘要（GET /api/chat/conversations）。title 已由后端做 COALESCE fallback。 */
export interface ConversationSummary {
  conversation_id: string;
  course_id: string | null;
  title: string;
  updated_at: string;
}

/** 课程资料（Web / GitHub）。status=importing 期间勿展示 chunk 内容。 */
export interface CourseSource {
  source_id: string;
  user_id: string;
  course_id: string;
  source_type: "web" | "github";
  source_url: string;
  title: string;
  status: "importing" | "ready" | "failed";
  chunk_count: number;
  error_message: string;
  created_at: string;
  updated_at: string;
}

/** 互联网搜索候选（不直接导入）。 */
export interface SourceSearchResult {
  title: string;
  url: string;
  snippet: string;
}

export interface ChatContext {
  type: "general" | "course" | "plan_step";
  course_id: string | null;
  plan_step_id: string | null;
  step_title: string;
}

export interface ChatResponse {
  message_id: string;
  conversation_id: string;
  content: string;
  course_id: string | null;
  created_at: string;
  profile_updates: string[];
  context?: ChatContext;
}

// ---------------------------------------------------------------------------
// Adaptive Learning Map + Tutor
// ---------------------------------------------------------------------------

export type KCStatus = "unknown" | "weak" | "learning" | "mastered";

export interface LearningMapEvidence {
  kc_id: string;
  type: string;
  correctness: string | null;
  difficulty: number | null;
  hint_level: number | null;
  confidence: number | null;
  misconceptions: string[];
  timestamp: string | null;
}

export interface LearningMapNode {
  id: string;
  name: string;
  description: string;
  difficulty: string;
  mastery: number | null; // null = 未评估 (UNKNOWN)，绝不为 0
  confidence: number | null;
  status: KCStatus;
  recommended: boolean;
  locked: boolean;
  prerequisites: string[];
  misconceptions: string[];
  recent_evidence: LearningMapEvidence[];
  reason_codes: string[];
}

export interface LearningMapEdge {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

export interface LearningMapResponse {
  course_id: string;
  goal: string;
  nodes: LearningMapNode[];
  edges: LearningMapEdge[];
  recommended_path: string[];
  current_recommended_kc: string | null;
  /** 图来源：generated（动态生成）/ builtin（内置）/ legacy；调试用。 */
  graph_source?: string | null;
  graph_version?: number | null;
}

export type TeachingAction =
  | "ASSESS"
  | "PROBE"
  | "HINT"
  | "EXPLAIN"
  | "EXAMPLE"
  | "COMPARE"
  | "PRACTICE"
  | "FEEDBACK"
  | "REFLECT"
  | "CHALLENGE"
  | "APPLICATION";

export interface TutorTurnRequest {
  kc_id: string;
  message?: string | null;
  learning_goal?: string | null;
  difficulty?: number;
}

export interface TutorResponse {
  kc_id: string;
  teaching_action: TeachingAction;
  message: string;
  learner_state_changed: boolean;
  learning_map_changed: boolean;
  mastery: number | null;
  confidence: number | null;
  reason_codes: string[];
  next_recommended_kc: string | null;
  explanation: string;
}
