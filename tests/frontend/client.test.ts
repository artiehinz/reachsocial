import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptsRequirement,
  acceptsResource,
  buildPaymentClient,
  connectBrowserWallet,
  executeReachSocial,
  ReachSocialRequestError,
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
  extra: { name: "USD Coin", version: "2" },
};
const declaration = {
  x402Version: 2,
  resource: { url: endpoint },
  accepts: [requirement],
};

describe("browser x402 guard", () => {
  afterEach(() => vi.restoreAllMocks());
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

  it.each([
    { network: "eip155:84532" },
    { asset: "0x0000000000000000000000000000000000000001" },
    { amount: "50001" },
    { amount: "invalid" },
    { extra: { name: "USD Coin", version: "2", assetTransferMethod: "permit2" } },
    { extra: { name: "Other token", version: "2" } },
  ])("does not sign an unsafe requirement %j", async (changed) => {
    const request = vi.fn();
    const client = buildPaymentClient({ request }, expected.metadata.receiver as `0x${string}`, expected);
    await expect(client.createPaymentPayload({
      ...declaration, accepts: [{ ...requirement, ...changed }],
    })).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });

  it("rejects a different resource before signing", async () => {
    const request = vi.fn();
    const client = buildPaymentClient({ request }, expected.metadata.receiver as `0x${string}`, expected);
    await expect(client.createPaymentPayload({
      ...declaration, resource: { url: endpoint + "?other=true" },
    })).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
  });

  it("rechecks account and network at the signing boundary", async () => {
    const request = vi.fn(async ({ method }) => method === "eth_chainId" ? "0x1" : [expected.metadata.receiver]);
    const client = buildPaymentClient({ request }, expected.metadata.receiver as `0x${string}`, expected);
    await expect(client.createPaymentPayload(declaration)).rejects.toThrow("account or network changed");
    expect(request.mock.calls.some(([call]) => call.method.includes("sign"))).toBe(false);
  });

  it.each([
    { service: "instagram.profile", paymentEndpoint: undefined },
    { service: "instagram.feed", paymentEndpoint: "/v1/acceptance/private/instagram.feed/execute" },
    { service: "instagram.feed", paymentEndpoint: "https://reachsocial.dev/v1/acceptance/private/instagram.feed/execute" },
  ])("executes $service at $paymentEndpoint once, then recovers without another signature", async ({ service, paymentEndpoint }) => {
    const key = crypto.randomUUID();
    const paidEndpoint = paymentEndpoint ? new URL(paymentEndpoint, "https://reachsocial.dev").href : endpoint;
    const paymentDeclaration = { ...declaration, resource: { url: paidEndpoint } };
    const input = { url: "https://www.instagram.com/instagram/" };
    let providerExecutions = 0;
    const wallet = vi.fn(async ({ method, params }) => {
      if (method === "eth_chainId") return "0x2105";
      if (method === "eth_accounts") return [expected.metadata.receiver];
      if (method === "eth_signTypedData_v4") {
        const typed = JSON.parse(params[1]);
        expect(typed.types.EIP712Domain).toHaveLength(4);
        expect(typed.primaryType).toBe("TransferWithAuthorization");
        expect(typed.message.value).toBe("50000");
        expect(typed.domain.verifyingContract.toLowerCase()).toBe(requirement.asset.toLowerCase());
        return "0x" + "11".repeat(65);
      }
      throw new Error("Unexpected wallet request");
    });
    const result = { request_id: "req_test", status: "success", data: { profile: { handle: "instagram" } } };
    const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url, options) => {
      const req = url instanceof Request ? url : new Request(url, options);
      expect(req.credentials).toBe("omit");
      expect(req.redirect).toBe("error");
      if (req.url.endsWith("/status.json")) return json({ payment: expected.metadata, status: "operational" });
      if (req.url.endsWith("/v1/services")) return json({ services: [{ id: "instagram.profile", available: true, execution: "sync", price_cents: 5 }] });
      expect(req.headers.get("Idempotency-Key")).toBe(key);
      expect(await req.clone().json()).toEqual({ input });
      if (req.url.includes("/recover/")) {
        expect(req.headers.has("PAYMENT-SIGNATURE")).toBe(false);
        return json({ result });
      }
      expect(req.url).toBe(paidEndpoint);
      expect(req.headers.get("X-ReachSocial-Approval")).toBe(paymentEndpoint ? "test-approval" : null);
      if (!req.headers.has("PAYMENT-SIGNATURE")) return new Response("{}", {
        status: 402, headers: { "PAYMENT-REQUIRED": btoa(JSON.stringify(paymentDeclaration)) },
      });
      providerExecutions++;
      return new Response(JSON.stringify(result), { headers: {
        "PAYMENT-RESPONSE": btoa(JSON.stringify({ success: true, transaction: "0x" + "ab".repeat(32), network: "eip155:8453" })),
      } });
    });
    const paid = await executeReachSocial({ request: wallet }, expected.metadata.receiver as `0x${string}`, service, input, "https://reachsocial.dev", key, paymentEndpoint ? "test-approval" : undefined, paymentEndpoint);
    expect(paid.result).toEqual(result);
    expect(paid.idempotencyKey).toBe(key);
    expect(await recoverReachSocial(service, input, key)).toEqual({ result });
    expect(providerExecutions).toBe(1);
    expect(wallet.mock.calls.filter(([call]) => call.method.includes("sign"))).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(paymentEndpoint ? 4 : 5);
  });

  it.each([
    "https://example.com/v1/acceptance/private/instagram.feed/execute",
    "//example.com/v1/acceptance/private/instagram.feed/execute",
    "/v1/acceptance/private/instagram.highlight/execute",
    "/v1/acceptance/private/instagram.feed/execute?changed=true",
  ])("rejects an unexpected approval endpoint %s before fetching or signing", async (paymentEndpoint) => {
    const request = vi.fn().mockResolvedValue("0x2105");
    const fetchMock = vi.spyOn(globalThis, "fetch");
    await expect(executeReachSocial({ request }, expected.metadata.receiver as `0x${string}`,
      "instagram.feed", {}, "https://reachsocial.dev", crypto.randomUUID(), "test-approval", paymentEndpoint,
    )).rejects.toThrow("payment endpoint did not match");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(request.mock.calls.some(([call]) => call.method.includes("sign"))).toBe(false);
  });

  it("retains the original key on a lost execution response", async () => {
    const key = crypto.randomUUID();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      if (String(url).endsWith("/status.json")) return new Response(JSON.stringify({ payment: expected.metadata }));
      if (String(url).endsWith("/v1/services")) return new Response(JSON.stringify({ services: [{ id: "instagram.profile", available: true, execution: "sync", price_cents: 5 }] }));
      throw new TypeError("Network response lost");
    });
    const promise = executeReachSocial({ request: vi.fn().mockResolvedValue("0x2105") }, expected.metadata.receiver as `0x${string}`, "instagram.profile", {}, "https://reachsocial.dev", key);
    await expect(promise).rejects.toBeInstanceOf(ReachSocialRequestError);
    await expect(promise).rejects.toMatchObject({ idempotencyKey: key });
  });

  it("rejects a different host before any network or wallet request", async () => {
    const request = vi.fn();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    await expect(executeReachSocial({ request }, expected.metadata.receiver as `0x${string}`, "instagram.profile", {}, "https://example.com")).rejects.toThrow("only sends requests");
    expect(request).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
