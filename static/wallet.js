const BASE_CHAIN_ID = "0x2105";

export function shortAddress(address) {
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function formatUsdc(value, decimals = 6) {
  const atomic = BigInt(value);
  const scale = 10n ** BigInt(decimals);
  const whole = atomic / scale;
  const fraction = (atomic % scale).toString().padStart(decimals, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole.toString();
}

export async function requestAccounts(provider) {
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!Array.isArray(accounts) || typeof accounts[0] !== "string") {
    throw new Error("The wallet did not return an account.");
  }
  return accounts[0];
}

export async function switchToBase(provider) {
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId: BASE_CHAIN_ID }] });
  } catch (error) {
    if (error && (error.code === 4902 || error.code === -32603)) {
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
      return;
    }
    throw error;
  }
}

export async function readUsdcBalance(provider, token, address) {
  if (!/^0x[0-9a-fA-F]{40}$/.test(token) || !/^0x[0-9a-fA-F]{40}$/.test(address)) {
    throw new Error("Invalid USDC or wallet address.");
  }
  const data = `0x70a08231${address.slice(2).toLowerCase().padStart(64, "0")}`;
  const result = await provider.request({
    method: "eth_call",
    params: [{ to: token, data }, "latest"],
  });
  if (typeof result !== "string" || !/^0x[0-9a-fA-F]+$/.test(result)) {
    throw new Error("The wallet could not read the USDC balance.");
  }
  return BigInt(result);
}

export function collectWallets(onChange) {
  const wallets = new Map();
  const announce = (event) => {
    const detail = event.detail;
    if (!detail?.info?.uuid || !detail.provider?.request) return;
    wallets.set(detail.info.uuid, detail);
    onChange(wallets);
  };
  window.addEventListener("eip6963:announceProvider", announce);
  window.dispatchEvent(new Event("eip6963:requestProvider"));
  if (window.ethereum?.request) {
    wallets.set("window.ethereum", {
      info: { uuid: "window.ethereum", name: "Browser wallet", icon: "", rdns: "legacy" },
      provider: window.ethereum,
    });
  }
  onChange(wallets);
  return () => window.removeEventListener("eip6963:announceProvider", announce);
}

export function initializeWalletReadiness(root) {
  const select = root.querySelector("[data-wallet-select]");
  const connect = root.querySelector("[data-wallet-connect]");
  const switchButton = root.querySelector("[data-wallet-switch]");
  const addressNode = root.querySelector("[data-wallet-address]");
  const networkNode = root.querySelector("[data-wallet-network]");
  const balanceNode = root.querySelector("[data-wallet-balance]");
  const statusNode = root.querySelector("[data-wallet-status]");
  const wallets = new Map();
  let provider;
  let account;

  const renderWallets = (found) => {
    for (const [id, wallet] of found) wallets.set(id, wallet);
    select.replaceChildren();
    if (!wallets.size) {
      select.add(new Option("No injected wallet found", ""));
      select.disabled = true;
      connect.disabled = true;
      statusNode.textContent = "Install or open an EIP-6963 compatible browser wallet.";
      return;
    }
    for (const [id, wallet] of wallets) select.add(new Option(wallet.info.name, id));
    select.disabled = false;
    connect.disabled = false;
    statusNode.textContent = wallets.size > 1 ? "Choose a wallet, then connect." : "Wallet found. Connect to check readiness.";
  };

  const refresh = async () => {
    if (!provider || !account) return;
    const chainId = await provider.request({ method: "eth_chainId" });
    const onBase = String(chainId).toLowerCase() === BASE_CHAIN_ID;
    networkNode.textContent = onBase ? "Base mainnet" : `Wrong network (${chainId})`;
    switchButton.hidden = onBase;
    balanceNode.textContent = onBase ? "Checking…" : "Switch to Base first";
    if (!onBase) return;
    const balance = await readUsdcBalance(provider, root.dataset.usdcAddress, account);
    const formatted = formatUsdc(balance, Number(root.dataset.usdcDecimals));
    balanceNode.textContent = `${formatted} USDC`;
    statusNode.textContent = balance >= BigInt(root.dataset.minimumAtomic)
      ? "Ready for at least one current request."
      : "USDC balance is below the current minimum request price.";
  };

  connect.addEventListener("click", async () => {
    const wallet = wallets.get(select.value);
    if (!wallet) return;
    provider = wallet.provider;
    try {
      account = await requestAccounts(provider);
      addressNode.textContent = shortAddress(account);
      statusNode.textContent = "Connected for this readiness check.";
      provider.on?.("accountsChanged", async (accounts) => {
        if (!Array.isArray(accounts) || !accounts.length) {
          account = undefined;
          addressNode.textContent = "Not connected";
          balanceNode.textContent = "Not checked";
          return;
        }
        account = accounts[0];
        addressNode.textContent = shortAddress(account);
        await refresh();
      });
      provider.on?.("chainChanged", refresh);
      await refresh();
    } catch (error) {
      statusNode.textContent = error?.code === 4001 ? "Wallet connection was rejected." : "Wallet connection failed.";
    }
  });

  switchButton.addEventListener("click", async () => {
    try {
      await switchToBase(provider);
      await refresh();
    } catch (error) {
      statusNode.textContent = error?.code === 4001 ? "Network switch was rejected." : "Could not switch this wallet to Base.";
    }
  });

  return collectWallets(renderWallets);
}

for (const root of document.querySelectorAll("[data-wallet-readiness]")) {
  initializeWalletReadiness(root);
}
