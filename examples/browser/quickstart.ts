import {
  connectBrowserWallet,
  executeReachSocial,
  recoverReachSocial,
  type BrowserProvider,
} from "./reachsocial-client.js";

const service = "instagram.profile";
const input = { url: "https://www.instagram.com/instagram/" };
const savedKey = "reachsocial:instagram-example";

// Call from your application's button handler. The wallet asks for approval.
export async function loadInstagramProfile() {
  if (sessionStorage.getItem(savedKey)) {
    throw new Error("An earlier request exists. Use recoverInstagramProfile first.");
  }
  const provider = (window as Window & { ethereum?: BrowserProvider }).ethereum;
  if (!provider) throw new Error("Open your app in a browser with a wallet installed.");
  const account = await connectBrowserWallet(provider);
  // A second click may finish connecting while the first request is underway.
  if (sessionStorage.getItem(savedKey)) {
    throw new Error("An earlier request exists. Use recoverInstagramProfile first.");
  }
  const key = crypto.randomUUID();
  // Keep this BEFORE payment, so a lost response or reload cannot lose the key.
  sessionStorage.setItem(savedKey, key);
  const paid = await executeReachSocial(
    provider, account, service, input, "https://reachsocial.dev", key,
  );
  return paid.result;
}

// Works after a reload in this tab. It never connects or signs with a wallet.
export async function recoverInstagramProfile() {
  const key = sessionStorage.getItem(savedKey);
  if (!key) throw new Error("No saved request key in this tab.");
  return recoverReachSocial(service, input, key);
}
