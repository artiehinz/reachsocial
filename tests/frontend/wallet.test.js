// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatUsdc,
  initializeWalletReadiness,
  requestAccounts,
  shortAddress,
  switchToBase,
} from "../../static/wallet.js";

const ADDRESS = "0xcf8fD9bd415C36326597E8079fCb3125FE2dB369";

function panel() {
  document.body.innerHTML = `<div data-wallet-readiness
    data-usdc-address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    data-usdc-decimals="6" data-minimum-atomic="50000">
    <select data-wallet-select disabled><option>Looking</option></select>
    <button data-wallet-connect disabled>Connect</button>
    <button data-wallet-switch hidden>Switch</button>
    <span data-wallet-address>Not connected</span>
    <span data-wallet-network>Not checked</span>
    <span data-wallet-balance>Not checked</span>
    <span data-wallet-status></span>
  </div>`;
  return document.querySelector("[data-wallet-readiness]");
}

function announce(uuid, name, provider) {
  window.dispatchEvent(new CustomEvent("eip6963:announceProvider", {
    detail: { info: { uuid, name, icon: "", rdns: `dev.${uuid}` }, provider },
  }));
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("wallet readiness", () => {
  beforeEach(() => {
    document.body.replaceChildren();
    Object.defineProperty(window, "ethereum", { value: undefined, configurable: true });
  });

  it("reports a missing wallet", () => {
    const root = panel();
    initializeWalletReadiness(root);
    expect(root.querySelector("[data-wallet-select]").textContent).toContain("No injected wallet");
    expect(root.querySelector("[data-wallet-connect]").disabled).toBe(true);
  });

  it("lists multiple EIP-6963 wallets", () => {
    const root = panel();
    initializeWalletReadiness(root);
    announce("one", "Wallet One", { request: vi.fn() });
    announce("two", "Wallet Two", { request: vi.fn() });
    expect([...root.querySelector("[data-wallet-select]").options].map((item) => item.text)).toEqual([
      "Wallet One",
      "Wallet Two",
    ]);
  });

  it("handles rejected connection without requesting a signature", async () => {
    const root = panel();
    const error = Object.assign(new Error("rejected"), { code: 4001 });
    const request = vi.fn().mockRejectedValue(error);
    initializeWalletReadiness(root);
    announce("reject", "Rejecting wallet", { request });
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    expect(root.querySelector("[data-wallet-status]").textContent).toContain("rejected");
    expect(request).toHaveBeenCalledWith({ method: "eth_requestAccounts" });
    expect(request.mock.calls.some(([call]) => call.method.includes("sign"))).toBe(false);
  });

  it("detects the wrong network without reading balance or signing", async () => {
    const root = panel();
    const request = vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [ADDRESS];
      if (method === "eth_chainId") return "0x1";
      throw new Error(`Unexpected method ${method}`);
    });
    initializeWalletReadiness(root);
    announce("wrong", "Wrong network wallet", { request });
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    expect(root.querySelector("[data-wallet-network]").textContent).toContain("Wrong network");
    expect(root.querySelector("[data-wallet-switch]").hidden).toBe(false);
    expect(request.mock.calls.some(([call]) => call.method === "eth_call")).toBe(false);
    expect(request.mock.calls.some(([call]) => call.method.includes("sign"))).toBe(false);
  });

  it("reports insufficient Base-USDC", async () => {
    const root = panel();
    const request = vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [ADDRESS];
      if (method === "eth_chainId") return "0x2105";
      if (method === "eth_call") return "0x2710";
      throw new Error(`Unexpected method ${method}`);
    });
    initializeWalletReadiness(root);
    announce("base", "Base wallet", { request });
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    expect(root.querySelector("[data-wallet-balance]").textContent).toBe("0.01 USDC");
    expect(root.querySelector("[data-wallet-status]").textContent).toContain("below");
    expect(request.mock.calls.some(([call]) => call.method.includes("sign"))).toBe(false);
  });

  it("formats values and handles a Base network switch", async () => {
    expect(shortAddress(ADDRESS)).toBe("0xcf8f…B369");
    expect(formatUsdc(4_846_000n)).toBe("4.846");
    const request = vi.fn().mockResolvedValue(undefined);
    await switchToBase({ request });
    expect(request).toHaveBeenCalledWith({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: "0x2105" }],
    });
    await expect(requestAccounts({ request: vi.fn().mockResolvedValue([]) })).rejects.toThrow(
      "did not return an account",
    );
  });
});
