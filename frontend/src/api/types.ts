/** API 类型定义（与 backend FastAPI 对应）。 */

export interface Goal {
  goal_id: string;
  name: string;
  target: string;
  progress: number;
  target_kcs: string[];
}

export interface Course {
  course_id: string;
  display_name: string;
  topic: string;
  goal: Goal | null;
  progress: number;
  plan_summary: string;
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
  conversation_id: string;
  course_id: string | null;
  messages: ChatMessage[];
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
