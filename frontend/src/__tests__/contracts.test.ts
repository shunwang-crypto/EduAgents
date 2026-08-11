import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// contracts.test.ts 位于 src/__tests__/，frontend 根需上移两级
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const pkg = JSON.parse(readFileSync(resolve(ROOT, "package.json"), "utf-8"));
const read = (p: string) => readFileSync(resolve(ROOT, p), "utf-8");

/** Build Contract Tests：防止"写了一个组件却没接线 / 依赖没声明 / Props 漂移 / 直渲"等问题回归。 */

describe("dependency contract", () => {
  it("declares all markdown + math + icon deps in package.json", () => {
    const deps = { ...pkg.dependencies };
    for (const d of [
      "lucide-react",
      "react-markdown",
      "remark-gfm",
      "remark-math",
      "rehype-katex",
      "katex",
    ]) {
      expect(deps[d], `missing dependency ${d}`).toBeTruthy();
    }
  });

  it("has test and build scripts", () => {
    expect(pkg.scripts?.test).toContain("vitest");
    expect(pkg.scripts?.build).toContain("tsc");
    expect(pkg.scripts?.build).toContain("vite");
  });
});

describe("rich markdown wiring contract", () => {
  const chatPage = read("src/features/chat/ChatPage.tsx");

  it("ChatPage imports and consumes RichMarkdown for assistant messages", () => {
    expect(chatPage).toContain('RichMarkdown from "../../components/content/RichMarkdown"');
    expect(chatPage).toContain("<RichMarkdown content={m.content} />");
  });

  it("ChatPage never renders raw {m.content} for assistant", () => {
    // 用户消息允许文本渲染，但 assistant 不允许 <div>{m.content}</div> 直渲
    const directDiv = chatPage.match(/<div>\{m\.content\}<\/div>/);
    expect(directDiv).toBeNull();
  });

  it("RichMarkdown exists and is exported", () => {
    const rm = read("src/components/content/RichMarkdown.tsx");
    expect(rm).toContain("export default function RichMarkdown");
  });
});

describe("api identity contract", () => {
  const client = read("src/api/client.ts");
  const provider = read("src/api/ApiProvider.tsx");
  const main = read("src/main.tsx");

  it("client.ts exports createApiClient factory (no global api singleton)", () => {
    expect(client).toContain("export function createApiClient");
    expect(client).not.toMatch(/export const api\s*=/);
    expect(client).not.toContain("export function setApiUserId");
  });

  it("ApiProvider exports ApiProvider + useApi", () => {
    expect(provider).toContain("export function ApiProvider");
    expect(provider).toContain("export function useApi");
  });

  it("no business component imports the removed client singleton", () => {
    const files = [
      "src/layout/Sidebar.tsx",
      "src/layout/AppShell.tsx",
      "src/features/chat/ChatPage.tsx",
      "src/features/study-plan/StudyPlanPage.tsx",
      "src/features/courses/CreateCourseModal.tsx",
    ];
    for (const f of files) {
      const src = read(f);
      expect(src, `${f} must not import api singleton`).not.toContain('from "../api/client"');
      expect(src, `${f} must use useApi`).toContain("useApi");
    }
  });

  it("client.ts has no hardcoded dev user; DEV_USER_ID only in main.tsx", () => {
    expect(client).not.toContain("VITE_DEV_USER_ID");
    expect(client).not.toContain("STU-001");
    expect(main).toContain("VITE_DEV_USER_ID");
  });

  it("single entry: main.tsx owns BrowserRouter; LearningApp does not", () => {
    const router = read("src/app/router.tsx");
    expect(main).toContain("<BrowserRouter>");
    // 只检查 JSX 渲染（注释里提及 BrowserRouter 是文档说明，不违规）
    expect(router).not.toContain("<BrowserRouter");
    expect(existsSync(resolve(ROOT, "src/app/App.tsx"))).toBe(false);
  });
});

describe("empty state props contract", () => {
  it("ChatEmptyState takes only onPick (single suggestion source)", () => {
    const src = read("src/features/chat/ChatEmptyState.tsx");
    expect(src).toMatch(/interface Props \{[\s\S]*?onPick: \(text: string\) => void[\s\S]*?\}/);
    expect(src).not.toContain("suggestions");
  });

  it("ChatPage passes only onPick to ChatEmptyState", () => {
    const chatPage = read("src/features/chat/ChatPage.tsx");
    expect(chatPage).toContain("<ChatEmptyState onPick={send} />");
  });
});
