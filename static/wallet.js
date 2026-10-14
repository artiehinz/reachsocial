const BASE_CHAIN_ID = "0x2105";
const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const validAddress = (value) => typeof value === "string" && /^0x[0-9a-fA-F]{40}$/.test(value);

export function shortAddress(address) {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function formatUsdc(value, decimals = 6) {
  const atomic = BigInt(value);
  const scale = 10n ** BigInt(decimals);
  const fraction = (atomic % scale).toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${atomic / scale}${fraction ? "." + fraction : ""}`;
}

export async function requestAccounts(provider) {
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!Array.isArray(accounts) || !validAddress(accounts[0])) {
    throw new Error("The wallet did not return an account.");
  }
  return accounts[0];
}

export async function switchToBase(provider) {
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId: BASE_CHAIN_ID }] });
  } catch (error) {
    if (error?.code !== 4902) throw error;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId: BASE_CHAIN_ID,
        chainName: "Base",
        nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
        rpcUrls: ["https://mainnet.base.org"],
        blockExplorerUrls: ["https://basescan.org"],
      }],
    });
  }
}

export async function readUsdcBalance(provider, token, address) {
  if (!validAddress(token) || !validAddress(address)) throw new Error("Invalid USDC or wallet address.");
  const data = `0x70a08231${address.slice(2).toLowerCase().padStart(64, "0")}`;
  const result = await provider.request({ method: "eth_call", params: [{ to: token, data }, "latest"] });
  if (typeof result !== "string" || !/^0x[0-9a-fA-F]+$/.test(result)) {
    throw new Error("The wallet could not read the USDC balance.");
  }
  return BigInt(result);
}

export function collectWallets(onChange) {
  const wallets = new Map();
  const announce = (event) => {
    const detail = event.detail;
    if (typeof detail?.info?.uuid !== "string" || typeof detail.info.name !== "string" ||
        typeof detail.provider?.request !== "function") return;
    for (const [id, wallet] of wallets) {
      if (wallet.provider === detail.provider) wallets.delete(id);
    }
    wallets.set(detail.info.uuid, detail);
    onChange(wallets);
  };
  window.addEventListener("eip6963:announceProvider", announce);
  window.dispatchEvent(new Event("eip6963:requestProvider"));
  if (typeof window.ethereum?.request === "function" &&
      ![...wallets.values()].some((wallet) => wallet.provider === window.ethereum)) {
    wallets.set("window.ethereum", { info: { uuid: "window.ethereum", name: "Browser wallet" }, provider: window.ethereum });
  }
  onChange(wallets);
  return () => window.removeEventListener("eip6963:announceProvider", announce);
}

export function initializeWalletReadiness(root) {
  const select = root.querySelector("[data-wallet-select]");
  const connect = root.querySelector("[data-wallet-connect]");
  const switchButton = root.querySelector("[data-wallet-switch]");
  const disconnect = root.querySelector("[data-wallet-disconnect]");
  const refreshButton = root.querySelector("[data-wallet-refresh]");
  const addressNode = root.querySelector("[data-wallet-address]");
  const networkNode = root.querySelector("[data-wallet-network]");
  const balanceNode = root.querySelector("[data-wallet-balance]");
  const statusNode = root.querySelector("[data-wallet-status]");
  let wallets = new Map();
  let provider;
  let account;
  let generation = 0;
  let readVersion = 0;
  let busy = false;
  let removeProviderListeners = () => {};

  const controls = () => {
    connect.disabled = busy || !wallets.size;
    select.disabled = busy || !wallets.size;
    connect.textContent = busy ? "Waiting for wallet…" : account ? "Reconnect" : "Connect wallet";
    if (disconnect) disconnect.hidden = !provider;
    if (refreshButton) refreshButton.hidden = !account;
    switchButton.disabled = busy;
  };
  const reset = (message = "Wallet disconnected from this page.") => {
    generation++;
    readVersion++;
    removeProviderListeners();
    removeProviderListeners = () => {};
    provider = undefined;
    account = undefined;
    busy = false;
    addressNode.textContent = "Not connected";
    addressNode.removeAttribute("title");
    networkNode.textContent = "Not checked";
    balanceNode.textContent = "Not checked";
    switchButton.hidden = true;
    statusNode.textContent = message;
    controls();
  };

  const refresh = async () => {
    if (!provider || !account) return;
    const selectedProvider = provider;
    const selectedAccount = account;
    const version = ++readVersion;
    const current = () => version === readVersion && selectedProvider === provider && selectedAccount === account;
    balanceNode.textContent = "Checking…";
    statusNode.textContent = "Checking network and balance…";
    try {
      const chainId = await selectedProvider.request({ method: "eth_chainId" });
      if (!current()) return;
      const onBase = String(chainId).toLowerCase() === BASE_CHAIN_ID;
      networkNode.textContent = onBase ? "Base mainnet" : "Wrong network";
      switchButton.hidden = onBase;
      if (!onBase) {
        balanceNode.textContent = "Not checked";
        statusNode.textContent = "Switch to Base to check your USDC balance.";
        return;
      }
      const balance = await readUsdcBalance(selectedProvider, BASE_USDC, selectedAccount);
      if (!current()) return;
      balanceNode.textContent = `${formatUsdc(balance)} USDC`;
      statusNode.textContent = balance >= BigInt(root.dataset.minimumAtomic || "50000")
        ? "Balance is enough for a $0.05 request. Payment still needs wallet approval."
        : "USDC balance is below $0.05. Add native USDC on Base, then refresh.";
    } catch {
      if (current()) {
        balanceNode.textContent = "Unavailable";
        statusNode.textContent = "Could not read the wallet. Unlock it and refresh.";
      }
    }
  };
  const accountsChanged = (accounts) => {
    readVersion++;
    if (!Array.isArray(accounts) || !validAddress(accounts[0])) {
      reset("No account connected. Connect your wallet to check again.");
      return;
    }
    account = accounts[0];
    addressNode.textContent = shortAddress(account);
    addressNode.title = account;
    controls();
    void refresh();
  };

  const connectWallet = async () => {
    if (busy) return;
    const wallet = wallets.get(select.value);
    if (!wallet) return;
    reset("Approve the connection in your wallet.");
    provider = wallet.provider;
    const selectedProvider = provider;
    const version = generation;
    busy = true;
    controls();
    try {
      const address = await requestAccounts(selectedProvider);
      if (version !== generation) return;
      const onDisconnect = () => reset();
      selectedProvider.on?.("accountsChanged", accountsChanged);
      selectedProvider.on?.("chainChanged", refresh);
      selectedProvider.on?.("disconnect", onDisconnect);
      removeProviderListeners = () => {
        selectedProvider.removeListener?.("accountsChanged", accountsChanged);
        selectedProvider.removeListener?.("chainChanged", refresh);
        selectedProvider.removeListener?.("disconnect", onDisconnect);
      };
      accountsChanged([address]);
    } catch (error) {
      if (version === generation) reset(error?.code === 4001
        ? "Wallet connection was rejected. You can try again."
        : "Could not connect. Unlock your wallet and try again.");
    } finally {
      if (provider === selectedProvider) { busy = false; controls(); }
    }
  };

  const switchNetwork = async () => {
    if (!provider || busy) return;
    const selectedProvider = provider;
    busy = true;
    controls();
    try {
      await switchToBase(selectedProvider);
      if (provider === selectedProvider) await refresh();
    } catch (error) {
      if (provider === selectedProvider) statusNode.textContent = error?.code === 4001
        ? "Network switch was rejected."
        : "Could not switch to Base. Select Base in your wallet, then refresh.";
    } finally {
      if (provider === selectedProvider) { busy = false; controls(); }
    }
  };
  const selectionChanged = () => reset("Wallet selected. Connect to check it.");
  const clearConnection = () => reset();
  connect.addEventListener("click", connectWallet);
  select.addEventListener("change", selectionChanged);
  switchButton.addEventListener("click", switchNetwork);
  disconnect?.addEventListener("click", clearConnection);
  refreshButton?.addEventListener("click", refresh);
  const stopDiscovery = collectWallets((found) => {
    const oldValue = select.value;
    wallets = new Map(found);
    select.replaceChildren();
    if (!wallets.size) {
      select.add(new Option("No browser wallet found", ""));
      statusNode.textContent = "Open this page in a browser with a wallet extension installed.";
    } else {
      for (const [id, wallet] of wallets) select.add(new Option(wallet.info.name.slice(0, 80), id));
      if (wallets.has(oldValue)) select.value = oldValue;
      else if (provider) select.value = [...wallets].find(([, wallet]) => wallet.provider === provider)?.[0] || select.value;
      if (!provider) statusNode.textContent = "Choose your wallet, then connect.";
    }
    controls();
  });
  return () => {
    stopDiscovery();
    reset();
    connect.removeEventListener("click", connectWallet);
    select.removeEventListener("change", selectionChanged);
    switchButton.removeEventListener("click", switchNetwork);
    disconnect?.removeEventListener("click", clearConnection);
    refreshButton?.removeEventListener("click", refresh);
  };
}

for (const root of document.querySelectorAll("[data-wallet-readiness]")) initializeWalletReadiness(root);

export function initializeWalletDialog(walletDialog, triggers) {
  if (!walletDialog || typeof walletDialog.showModal !== "function") return;
  for (const trigger of triggers) {
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      walletDialog.showModal();
      const select = walletDialog.querySelector("[data-wallet-select]");
      const connect = walletDialog.querySelector("[data-wallet-connect]");
      const disconnect = walletDialog.querySelector("[data-wallet-disconnect]");
      if (select.options.length === 1 && !connect.disabled && disconnect.hidden) {
        connect.click();
      } else {
        select.focus();
      }
    });
  }
}

initializeWalletDialog(document.querySelector("[data-wallet-dialog]"), document.querySelectorAll("[data-wallet-open]"));
