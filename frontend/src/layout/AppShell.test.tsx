import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { ChatPage } from "../features/chat/ChatPage";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    listCourses: vi.fn().mockResolvedValue([]),
    listCourseCategories: vi.fn().mockResolvedValue([]),
    listConversations: vi.fn().mockResolvedValue([]),
    createCourseCategory: vi.fn(),
    renameCourseCategory: vi.fn(),
    deleteCourseCategory: vi.fn(),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: "C-1", course_id: null, messages: [] }),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python" }),
    getStep: vi.fn(),
  },
}));

vi.mock("../api/ApiProvider", () => ({ useApi: () => mockApi }));

function stubMatchMedia(matchesFactory: (query: string) => boolean) {
  const orig = window.matchMedia;
  window.matchMedia = ((query: string) =>
    ({
      matches: matchesFactory(query),
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown) as typeof window.matchMedia;
  return () => {
    window.matchMedia = orig;
  };
}

function renderShell() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/" element={<ChatPage />} />
        </Route>
      </Routes>
    </MemoryRouter>
  );
}

beforeAll(() => {
  if (!window.matchMedia) {
    stubMatchMedia(() => false);
  }
});

describe("AppShell layout", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders exactly one main workspace (no nested main)", async () => {
    renderShell();
    const mains = document.querySelectorAll("main");
    expect(mains.length).toBe(1);
    expect(mains[0].className).toBe("workspace");
  });

  it("renders sidebar alongside workspace", async () => {
    renderShell();
    await waitFor(() => expect(document.querySelector(".sidebar")).toBeTruthy());
    expect(document.querySelector(".eduagents-app")).toBeTruthy();
  });

  it("mobile: sidebar receives collapsed=false (drawer shows full text, not icon rail)", async () => {
    const restore = stubMatchMedia((q) => q.includes("max-width: 768px"));
    try {
      renderShell();
      await waitFor(() => expect(document.querySelector(".sidebar")).toBeTruthy());
      expect(document.querySelector(".sidebar")?.classList.contains("collapsed")).toBe(false);
    } finally {
      restore();
    }
  });

  it("desktop: sidebar can collapse to icon rail", async () => {
    const restore = stubMatchMedia(() => false);
    try {
      renderShell();
      const sidebar = await waitFor(() => document.querySelector(".sidebar")) as HTMLElement;
      // 点击折叠按钮 → collapsed class
      const toggle = sidebar.querySelector(".sidebar-toggle") as HTMLButtonElement;
      toggle?.click();
      await waitFor(() =>
        expect(document.querySelector(".sidebar")?.classList.contains("collapsed")).toBe(true)
      );
    } finally {
      restore();
    }
  });
});
