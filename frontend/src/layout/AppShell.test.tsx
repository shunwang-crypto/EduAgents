import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "./AppShell";
import { ChatPage } from "../features/chat/ChatPage";

vi.mock("../api/client", () => ({
  api: {
    listCourses: vi.fn().mockResolvedValue([]),
    createConversation: vi.fn().mockResolvedValue({ conversation_id: "CONV-1" }),
    getChat: vi.fn().mockResolvedValue({ conversation_id: "C-1", course_id: null, messages: [] }),
    getCourse: vi.fn().mockResolvedValue({ course_id: "PY", display_name: "Python" }),
    getStep: vi.fn(),
  },
}));

describe("AppShell layout", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders exactly one main workspace (no nested main)", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<ChatPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    const mains = document.querySelectorAll("main");
    expect(mains.length).toBe(1);
    expect(mains[0].className).toBe("workspace");
  });

  it("renders sidebar alongside workspace", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<ChatPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => expect(document.querySelector(".sidebar")).toBeTruthy());
    expect(document.querySelector(".eduagents-app")).toBeTruthy();
  });
});
