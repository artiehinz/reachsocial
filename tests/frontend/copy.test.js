// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

const source = readFileSync("static/site.js", "utf8");
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
function setup(clipboard) {
  document.body.innerHTML = '<details><summary>Source</summary><pre id="code">line one\nline two</pre></details><button data-copy-target="code" data-copy-status="status">Copy example</button><span id="status"></span>';
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: clipboard });
  window.eval(source);
  return document.querySelector("button");
}
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
describe("copy controls", () => {
  it("copies real newlines and restores the label after repeated clicks", async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue();
    const button = setup({ writeText });
    button.click(); await flush();
    expect(writeText).toHaveBeenCalledWith("line one\nline two");
    expect(button.textContent).toBe("Copied");
    button.click(); await flush();
    await vi.advanceTimersByTimeAsync(1700);
    expect(button.textContent).toBe("Copy example");
  });
  it("opens the source for manual copying if both clipboard methods fail", async () => {
    const button = setup({ writeText: vi.fn().mockRejectedValue(new Error("Denied")) });
    document.execCommand = vi.fn(() => { throw new Error("Unsupported"); });
    button.click(); await flush();
    expect(document.querySelector("details").open).toBe(true);
    expect(document.querySelector("#status").textContent).toContain("manually");
    expect(document.querySelector(".copy-fallback")).toBeNull();
    expect(button.disabled).toBe(false);
  });
});
