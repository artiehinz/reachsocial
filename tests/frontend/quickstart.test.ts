// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { connectBrowserWallet, executeReachSocial, recoverReachSocial } from "../../examples/browser/reachsocial-client.js";
import { loadInstagramProfile, recoverInstagramProfile } from "../../examples/browser/quickstart.js";

vi.mock("../../examples/browser/reachsocial-client.js", () => ({
  connectBrowserWallet: vi.fn(), executeReachSocial: vi.fn(), recoverReachSocial: vi.fn(),
}));

beforeEach(() => {
  sessionStorage.clear();
  vi.resetAllMocks();
  Object.defineProperty(window, "ethereum", { configurable: true, value: { request: vi.fn() } });
  vi.mocked(connectBrowserWallet).mockResolvedValue("0x1111111111111111111111111111111111111111");
});

it("keeps the original key before a lost response and recovers without a second execution", async () => {
  vi.mocked(executeReachSocial).mockImplementation(async (...args) => {
    expect(sessionStorage.getItem("reachsocial:instagram-example")).toBe(args[5]);
    throw new Error("Response lost");
  });
  await expect(loadInstagramProfile()).rejects.toThrow("Response lost");
  const key = sessionStorage.getItem("reachsocial:instagram-example");
  expect(key).toMatch(/^[a-z0-9-]{36}$/);
  await recoverInstagramProfile();
  expect(recoverReachSocial).toHaveBeenCalledWith("instagram.profile", {
    url: "https://www.instagram.com/instagram/",
  }, key);
  expect(executeReachSocial).toHaveBeenCalledTimes(1);
  expect(connectBrowserWallet).toHaveBeenCalledTimes(1);
});

it("does not start two purchases when connect resolves for concurrent clicks", async () => {
  vi.mocked(executeReachSocial).mockResolvedValue({ result: {}, idempotencyKey: "unused", payment: null });
  const results = await Promise.allSettled([loadInstagramProfile(), loadInstagramProfile()]);
  expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
  expect(executeReachSocial).toHaveBeenCalledTimes(1);
});
