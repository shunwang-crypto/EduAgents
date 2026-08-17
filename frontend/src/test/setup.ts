/** Vitest jsdom 全局补丁：React Flow（@xyflow/react）依赖浏览器 DOM 测量 API。 */

if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
}

if (!("DOMMatrixReadOnly" in globalThis)) {
  class DOMMatrixReadOnlyStub {
    m22 = 1;
    m11 = 1;
    static fromMatrix() {
      return new DOMMatrixReadOnlyStub();
    }
    static fromString() {
      return new DOMMatrixReadOnlyStub();
    }
  }
  (globalThis as Record<string, unknown>).DOMMatrixReadOnly = DOMMatrixReadOnlyStub;
}
