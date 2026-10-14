import { x402Client, type PaymentCreationContext } from "@x402/core/client";
import type { PaymentRequired, PaymentRequirements } from "@x402/core/types";
import { ExactEvmScheme } from "@x402/evm";
import { wrapFetchWithPayment } from "@x402/fetch";

const BASE_URL = "https://reachsocial.dev";
const BASE_NETWORK = "eip155:8453";
const BASE_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const MAX_PAYMENT_ATOMIC = 50_000n;

export interface BrowserProvider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
}

interface PaymentMetadata {
  enabled: boolean;
  version: number;
  network: string;
  chain_id: number;
  asset: { address: string; symbol: string; decimals: number };
  receiver: string;
}

interface ServiceSummary {
  id: string;
  execution: "sync" | "async";
  available: boolean;
  price_cents: number;
}

interface ExpectedPayment {
  endpoint: string;
  amountAtomic: bigint;
  metadata: PaymentMetadata;
}

export class ReachSocialRequestError extends Error {
  constructor(message: string, readonly idempotencyKey: string) {
    super(message);
  }
}

export async function connectBrowserWallet(provider: BrowserProvider): Promise<`0x${string}`> {
  const accounts = await provider.request({ method: "eth_requestAccounts" });
  if (!Array.isArray(accounts) || typeof accounts[0] !== "string") {
    throw new Error("The browser wallet did not return an account");
  }
  const chainId = await provider.request({ method: "eth_chainId" });
  if (String(chainId).toLowerCase() !== "0x2105") {
    throw new Error("Switch the browser wallet to Base mainnet before paying");
  }
  return accounts[0] as `0x${string}`;
}

function sameAddress(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}

export function acceptsRequirement(
  version: number,
  requirement: PaymentRequirements,
  expected: ExpectedPayment,
): boolean {
  return (
    version === expected.metadata.version &&
    version === 2 &&
    requirement.scheme === "exact" &&
    requirement.network === BASE_NETWORK &&
    requirement.network === expected.metadata.network &&
    sameAddress(requirement.asset, expected.metadata.asset.address) &&
    sameAddress(requirement.payTo, expected.metadata.receiver) &&
    BigInt(requirement.amount) === expected.amountAtomic &&
    BigInt(requirement.amount) <= MAX_PAYMENT_ATOMIC
  );
}

export function acceptsResource(declaration: PaymentRequired, endpoint: string): boolean {
  try {
    return new URL(declaration.resource.url).href === new URL(endpoint).href;
  } catch {
    return false;
  }
}

function typedDataJson(value: unknown): string {
  return JSON.stringify(value, (_key, item) =>
    typeof item === "bigint" ? item.toString() : item,
  );
}

export function buildPaymentClient(
  provider: BrowserProvider,
  account: `0x${string}`,
  expected: ExpectedPayment,
): x402Client {
  let approvedDeclaration: PaymentRequired | undefined;
  const signer = {
    address: account,
    signTypedData: async (message: {
      domain: Record<string, unknown>;
      types: Record<string, unknown>;
      primaryType: string;
      message: Record<string, unknown>;
    }): Promise<`0x${string}`> => {
      if (!approvedDeclaration) throw new Error("Payment challenge was not approved");
      return (await provider.request({
        method: "eth_signTypedData_v4",
        params: [account, typedDataJson(message)],
      })) as `0x${string}`;
    },
  };

  return new x402Client()
    .register(BASE_NETWORK, new ExactEvmScheme(signer))
    .setSpendControls({ maxAmountPerPayment: "$0.05" })
    .registerPolicy((version, requirements) =>
      requirements.filter((requirement) => acceptsRequirement(version, requirement, expected)),
    )
    .onBeforePaymentCreation(async (context: PaymentCreationContext) => {
      if (
        !acceptsRequirement(
          context.paymentRequired.x402Version,
          context.selectedRequirements,
          expected,
        ) ||
        !acceptsResource(context.paymentRequired, expected.endpoint)
      ) {
        return { abort: true, reason: "ReachSocial payment challenge did not match the request" };
      }
      approvedDeclaration = context.paymentRequired;
    });
}

async function readConfiguration(baseUrl: string, serviceId: string) {
  const [statusResponse, servicesResponse] = await Promise.all([
    fetch(`${baseUrl}/status.json`),
    fetch(`${baseUrl}/v1/services`),
  ]);
  if (!statusResponse.ok || !servicesResponse.ok) {
    throw new Error("ReachSocial discovery is unavailable");
  }
  const status = (await statusResponse.json()) as { payment: PaymentMetadata };
  const catalog = (await servicesResponse.json()) as { services: ServiceSummary[] };
  const service = catalog.services.find((item) => item.id === serviceId);
  if (!service?.available || service.execution !== "sync" || service.price_cents > 5) {
    throw new Error("The requested service is not available within the $0.05 limit");
  }
  if (
    !status.payment.enabled ||
    status.payment.version !== 2 ||
    status.payment.network !== BASE_NETWORK ||
    status.payment.chain_id !== 8453 ||
    !sameAddress(status.payment.asset.address, BASE_USDC) ||
    status.payment.asset.decimals !== 6 ||
    status.payment.asset.symbol !== "USDC"
  ) {
    throw new Error("ReachSocial payment metadata did not match Base mainnet USDC");
  }
  return { metadata: status.payment, service };
}

export async function executeReachSocial(
  provider: BrowserProvider,
  account: `0x${string}`,
  serviceId: string,
  input: Record<string, unknown>,
  baseUrl = BASE_URL,
) {
  const chainId = await provider.request({ method: "eth_chainId" });
  if (String(chainId).toLowerCase() !== "0x2105") {
    throw new Error("Switch the browser wallet to Base mainnet before paying");
  }
  const endpoint = `${baseUrl}/v1/services/${encodeURIComponent(serviceId)}/execute`;
  const { metadata, service } = await readConfiguration(baseUrl, serviceId);
  const idempotencyKey = crypto.randomUUID();
  const client = buildPaymentClient(provider, account, {
    endpoint,
    metadata,
    amountAtomic: BigInt(service.price_cents * 10_000),
  });
  const paidFetch = wrapFetchWithPayment(fetch, client);

  try {
    const response = await paidFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ input }),
    });
    if (!response.ok) throw new Error(`ReachSocial returned HTTP ${response.status}`);
    return {
      idempotencyKey,
      result: await response.json(),
      settlement: response.headers.get("PAYMENT-RESPONSE"),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "ReachSocial request failed";
    throw new ReachSocialRequestError(message, idempotencyKey);
  }
}

export async function recoverReachSocial(
  serviceId: string,
  input: Record<string, unknown>,
  idempotencyKey: string,
  baseUrl = BASE_URL,
) {
  // Deliberately use ordinary fetch: recovery must never create or sign a payment.
  const response = await fetch(
    `${baseUrl}/v1/payments/recover/${encodeURIComponent(serviceId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ input }),
    },
  );
  if (!response.ok) throw new Error(`Recovery returned HTTP ${response.status}`);
  return response.json();
}
