import { describe, expect, it } from "vitest";
import {
  courseChatPath,
  courseLearnPath,
  coursePlanPath,
  generalChatPath,
  learningAppBase,
} from "./navigation";

describe("navigation helpers (host-relative)", () => {
  it("learningAppBase strips /courses/ prefix, keeps host prefix", () => {
    expect(learningAppBase("/courses/PY/chat")).toBe("/");
    expect(learningAppBase("/adaptive-learning/courses/PY/chat")).toBe("/adaptive-learning");
    expect(learningAppBase("/host/learning/courses/PY/plan")).toBe("/host/learning");
    expect(learningAppBase("/")).toBe("/");
    expect(learningAppBase("/adaptive-learning")).toBe("/adaptive-learning");
  });

  it("generalChatPath stays within host prefix (New Chat = General Chat root)", () => {
    expect(generalChatPath("/courses/PY/chat", "X")).toBe("/?conversation=X");
    expect(generalChatPath("/host/learning/courses/PY/chat", "X")).toBe(
      "/host/learning?conversation=X"
    );
  });

  it("courseChatPath is host-relative and preserves step/conversation query", () => {
    expect(courseChatPath("/courses/PY/chat", "PY")).toBe("/courses/PY/chat");
    expect(courseChatPath("/host/learning/courses/PY/chat", "PY", { stepId: "S1" })).toBe(
      "/host/learning/courses/PY/chat?step=S1"
    );
    expect(
      courseChatPath("/adaptive-learning/courses/PY/chat", "PY", { conversationId: "C1" })
    ).toBe("/adaptive-learning/courses/PY/chat?conversation=C1");
  });

  it("coursePlanPath is host-relative", () => {
    expect(coursePlanPath("/host/learning/courses/PY/chat", "PY")).toBe(
      "/host/learning/courses/PY/plan"
    );
    expect(coursePlanPath("/courses/PY/chat", "PY")).toBe("/courses/PY/plan");
  });

  it("courseLearnPath points at the standalone learn page, host-relative", () => {
    expect(courseLearnPath("/courses/PY/plan", "PY", "S1")).toBe("/courses/PY/learn/S1");
    expect(courseLearnPath("/host/learning/courses/PY/plan", "PY", "S1")).toBe(
      "/host/learning/courses/PY/learn/S1"
    );
    expect(courseLearnPath("/adaptive-learning/courses/PY/learn/S1", "PY", "S2")).toBe(
      "/adaptive-learning/courses/PY/learn/S2"
    );
    // 从 General Chat 根进入也不越出前缀
    expect(courseLearnPath("/adaptive-learning", "PY", "S1")).toBe(
      "/adaptive-learning/courses/PY/learn/S1"
    );
  });
});
