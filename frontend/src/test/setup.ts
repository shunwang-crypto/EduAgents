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

/** Rich Learning Document 用 IntersectionObserver 高亮目录当前节；jsdom 没有实现。 */
if (!("IntersectionObserver" in globalThis)) {
  class IntersectionObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  (globalThis as Record<string, unknown>).IntersectionObserver = IntersectionObserverStub;
}

/** 目录点击靠 scrollIntoView 定位；jsdom 没有实现，补一个可被 spy 的空实现。 */
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
