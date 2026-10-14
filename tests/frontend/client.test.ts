import { describe, expect, it, vi } from "vitest";

import {
  acceptsRequirement,
  acceptsResource,
  buildPaymentClient,
  connectBrowserWallet,
  recoverReachSocial,
} from "../../examples/browser/reachsocial-client.js";

const endpoint = "https://reachsocial.dev/v1/services/instagram.profile/execute";
const expected = {
  endpoint,
  amountAtomic: 50_000n,
  metadata: {
    enabled: true,
    version: 2,
    network: "eip155:8453",
    chain_id: 8453,
    asset: {
      address: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      symbol: "USDC",
      decimals: 6,
    },
    receiver: "0x76bCc44696A4c67579A6aF2F25CF953BE0931E38",
  },
};
const requirement = {
  scheme: "exact",
  network: "eip155:8453" as const,
  asset: expected.metadata.asset.address,
  amount: "50000",
  payTo: expected.metadata.receiver,
  maxTimeoutSeconds: 300,
  extra: {},
};
const declaration = {
  x402Version: 2,
  resource: { url: endpoint },
  accepts: [requirement],
};

describe("browser x402 guard", () => {
  it("connects an injected wallet only on Base mainnet", async () => {
    const request = vi.fn(async ({ method }) => {
      if (method === "eth_requestAccounts") return [expected.metadata.receiver];
      if (method === "eth_chainId") return "0x2105";
      throw new Error(`Unexpected method ${method}`);
    });
    await expect(connectBrowserWallet({ request })).resolves.toBe(expected.metadata.receiver);
    expect(request).toHaveBeenCalledTimes(2);

    const wrongNetwork = vi.fn(async ({ method }) =>
      method === "eth_requestAccounts" ? [expected.metadata.receiver] : "0x1",
    );
    await expect(connectBrowserWallet({ request: wrongNetwork })).rejects.toThrow("Base mainnet");
  });

  it("accepts only the exact expected payment", () => {
    expect(acceptsRequirement(2, requirement, expected)).toBe(true);
    for (const changed of [
      { network: "eip155:84532" },
      { asset: "0x0000000000000000000000000000000000000001" },
      { payTo: "0x0000000000000000000000000000000000000001" },
      { amount: "50001" },
    ]) {
      expect(acceptsRequirement(2, { ...requirement, ...changed }, expected)).toBe(false);
    }
    expect(acceptsRequirement(1, requirement, expected)).toBe(false);
    expect(acceptsResource(declaration, endpoint)).toBe(true);
    expect(acceptsResource({ ...declaration, resource: { url: `${endpoint}/wrong` } }, endpoint)).toBe(false);
  });

  it("rejects tampered requirements before asking the wallet to sign", async () => {
    const request = vi.fn();
    const client = buildPaymentClient({ request }, expected.metadata.receiver as `0x${string}`, expected);
    await expect(client.createPaymentPayload({
      ...declaration,
      accepts: [{ ...requirement, payTo: "0x0000000000000000000000000000000000000001" }],
    })).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });

  it("recovers with ordinary fetch and no wallet interaction", async () => {
    const response = new Response(JSON.stringify({ result: { status: "success" } }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
    const result = await recoverReachSocial(
      "instagram.profile",
      { url: "https://www.instagram.com/instagram/" },
      "5d714f31-41f6-4bbb-a692-f54e0a2babdc",
    );
    expect(result).toEqual({ result: { status: "success" } });
    expect(fetchMock).toHaveBeenCalledOnce();
    fetchMock.mockRestore();
  });
});
