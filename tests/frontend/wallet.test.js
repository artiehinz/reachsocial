// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatUsdc,
  initializeWalletDialog,
  initializeWalletReadiness as initialize,
  requestAccounts,
  shortAddress,
  switchToBase,
} from "../../static/wallet.js";

const ADDRESS = "0xcf8fD9bd415C36326597E8079fCb3125FE2dB369";
let cleanups = [];
function initializeWalletReadiness(root) { cleanups.push(initialize(root)); }
afterEach(() => { cleanups.forEach((cleanup) => cleanup()); cleanups = []; });

function panel() {
  document.body.innerHTML = `<div data-wallet-readiness
    data-usdc-address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    data-usdc-decimals="6" data-minimum-atomic="50000">
    <select data-wallet-select disabled><option>Looking</option></select>
    <button data-wallet-connect disabled>Connect</button>
    <button data-wallet-switch hidden>Switch</button>
    <button data-wallet-refresh hidden>Refresh</button>
    <button data-wallet-disconnect hidden>Disconnect</button>
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
    expect(root.querySelector("[data-wallet-select]").textContent).toContain("No browser wallet");
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

  it("deduplicates the legacy provider and preserves wallet selection on late discovery", () => {
    const provider = { request: vi.fn() };
    Object.defineProperty(window, "ethereum", { value: provider, configurable: true });
    const root = panel();
    initializeWalletReadiness(root);
    announce("primary", "Primary", provider);
    expect(root.querySelector("select").options).toHaveLength(1);
    announce("second", "Second", { request: vi.fn() });
    root.querySelector("select").value = "second";
    announce("third", "Third", { request: vi.fn() });
    expect(root.querySelector("select").value).toBe("second");
  });

  it("clears state and listeners when the user disconnects", async () => {
    const events = new Map();
    const provider = {
      request: vi.fn(async ({ method }) => {
        if (method === "eth_requestAccounts") return [ADDRESS];
        if (method === "eth_chainId") return "0x2105";
        if (method === "eth_call") return "0x186a0";
        throw new Error("Unexpected wallet request");
      }),
      on: (name, handler) => events.set(name, handler),
      removeListener: (name) => events.delete(name),
    };
    const root = panel();
    initializeWalletReadiness(root);
    announce("primary", "Primary", provider);
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    expect(events.size).toBe(3);
    expect(root.querySelector("[data-wallet-balance]").textContent).toBe("0.1 USDC");
    events.get("chainChanged")();
    await settle();
    events.get("accountsChanged")([]);
    expect(events.size).toBe(0);
    expect(root.querySelector("[data-wallet-address]").textContent).toBe("Not connected");
    expect(root.querySelector("[data-wallet-network]").textContent).toBe("Not checked");
    expect(root.querySelector("[data-wallet-balance]").textContent).toBe("Not checked");
    expect(root.querySelector("[data-wallet-switch]").hidden).toBe(true);
  });

  it("ignores a late balance result after switching wallets", async () => {
    let resolveBalance;
    const oldProvider = { request: vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [ADDRESS];
      if (method === "eth_chainId") return "0x2105";
      return new Promise((resolve) => { resolveBalance = resolve; });
    }) };
    const root = panel();
    initializeWalletReadiness(root);
    announce("old", "Old", oldProvider);
    announce("new", "New", { request: vi.fn() });
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    root.querySelector("select").value = "new";
    root.querySelector("select").dispatchEvent(new Event("change"));
    resolveBalance("0x186a0");
    await settle();
    expect(root.querySelector("[data-wallet-address]").textContent).toBe("Not connected");
    expect(root.querySelector("[data-wallet-balance]").textContent).toBe("Not checked");
  });

  it("handles an unavailable balance without leaving Checking forever", async () => {
    const request = vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [ADDRESS];
      if (method === "eth_chainId") return "0x2105";
      throw new Error("RPC offline");
    });
    const root = panel();
    initializeWalletReadiness(root);
    announce("offline", "Offline", { request });
    root.querySelector("[data-wallet-connect]").click();
    await settle();
    expect(root.querySelector("[data-wallet-balance]").textContent).toBe("Unavailable");
    expect(root.querySelector("[data-wallet-status]").textContent).toContain("refresh");
  });
});

describe("header connection", () => {
  it("opens the dialog and requests connection only after a click", async () => {
    const root = panel();
    const dialog = document.createElement("dialog");
    root.replaceWith(dialog);
    dialog.append(root);
    dialog.showModal = vi.fn();
    const trigger = document.createElement("a");
    trigger.href = "/docs/api#wallet-readiness";
    document.body.append(trigger);
    Object.defineProperty(window, "ethereum", { value: undefined, configurable: true });
    const request = vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [ADDRESS];
      if (method === "eth_chainId") return "0x2105";
      if (method === "eth_call") return "0xc350";
      throw new Error("Unexpected wallet request");
    });
    initializeWalletReadiness(root);
    announce("header", "Wallet", { request });
    initializeWalletDialog(dialog, [trigger]);
    expect(request).not.toHaveBeenCalled();
    trigger.click();
    await settle();
    expect(dialog.showModal).toHaveBeenCalledOnce();
    expect(request.mock.calls.map(([call]) => call.method)).toEqual([
      "eth_requestAccounts", "eth_chainId", "eth_call",
    ]);
  });

  it("asks users to choose when multiple wallets are detected", () => {
    const root = panel();
    const dialog = document.createElement("dialog");
    root.replaceWith(dialog);
    dialog.append(root);
    dialog.showModal = vi.fn();
    const trigger = document.createElement("a");
    document.body.append(trigger);
    Object.defineProperty(window, "ethereum", { value: undefined, configurable: true });
    const request = vi.fn();
    initializeWalletReadiness(root);
    announce("a", "Wallet A", { request });
    announce("b", "Wallet B", { request });
    initializeWalletDialog(dialog, [trigger]);
    trigger.click();
    expect(request).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(root.querySelector("[data-wallet-select]"));
  });
});

describe("header wallet state", () => {
  it("restores permission without prompting and follows network/account/disconnect changes", async () => {
    const { initializeWalletNavigation } = await import("../../static/wallet.js");
    document.body.innerHTML = '<a class="nav-wallet"><span data-wallet-label>Connect wallet</span></a>';
    const button = document.querySelector('.nav-wallet');
    let accounts = [ADDRESS];
    let chain = '0x2105';
    const events = new Map();
    const provider = {
      request: vi.fn(async ({ method }) => {
        if (method === 'eth_accounts') return accounts;
        if (method === 'eth_chainId') return chain;
        throw new Error('Unexpected wallet prompt');
      }),
      on: (name, handler) => events.set(name, handler),
      removeListener: (name) => events.delete(name),
    };
    Object.defineProperty(window, 'ethereum', { value: provider, configurable: true });
    cleanups.push(initializeWalletNavigation(button));
    await settle();
    expect(button.textContent).toBe(shortAddress(ADDRESS));
    expect(button.dataset.walletState).toBe('connected');
    expect(button.getAttribute('aria-label')).toContain(ADDRESS);
    chain = '0x1'; events.get('chainChanged')(); await settle();
    expect(button.textContent).toBe('Switch to Base');
    expect(button.dataset.walletState).toBe('wrong-network');
    accounts = ['0x1111111111111111111111111111111111111111'];
    chain = '0x2105'; events.get('accountsChanged')(); await settle();
    expect(button.textContent).toBe('0x1111…1111');
    accounts = []; events.get('accountsChanged')(); await settle();
    expect(button.textContent).toBe('Connect wallet');
    expect(provider.request.mock.calls.every(([call]) => ['eth_accounts', 'eth_chainId'].includes(call.method))).toBe(true);
  });

  it("does not restore a stale account after a page disconnect", async () => {
    const { initializeWalletNavigation } = await import("../../static/wallet.js");
    document.body.innerHTML = '<a class="nav-wallet"><span data-wallet-label>Connect wallet</span></a>';
    let resolveAccounts;
    const provider = { request: vi.fn(() => new Promise(resolve => { resolveAccounts = resolve; })) };
    Object.defineProperty(window, 'ethereum', { value: provider, configurable: true });
    cleanups.push(initializeWalletNavigation(document.querySelector('.nav-wallet')));
    document.dispatchEvent(new CustomEvent('reachsocial:wallet', { detail: {} }));
    resolveAccounts([ADDRESS]); await settle();
    expect(document.querySelector('.nav-wallet').textContent).toBe('Connect wallet');
  });
});
