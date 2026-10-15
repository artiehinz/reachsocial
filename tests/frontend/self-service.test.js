// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ provider: { request: vi.fn() }, execute: vi.fn(), connect: vi.fn() }));
vi.mock('../../static/wallet.js?v=20261014-4', () => ({ collectWallets: callback => callback(new Map([
  ['wallet', { info: { name: 'Test wallet' }, provider: mocks.provider }],
])) }));
vi.mock('../../static/reachsocial-client.js', () => ({ executeReachSocial: mocks.execute, connectBrowserWallet: mocks.connect }));
const ADDRESS = '0x1111111111111111111111111111111111111111';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
beforeEach(() => {
  vi.resetModules(); vi.clearAllMocks();
  window.history.replaceState({}, '', '/');
});
it('account page does not sign until the user explicitly logs in', async () => {
  document.body.innerHTML = `<div data-account>
    <select data-account-wallet></select><button data-account-login></button><p data-account-status></p>
    <div data-account-consent hidden><span data-account-client></span><button data-account-approve></button><button data-account-deny></button></div>
    <div data-account-details hidden><ul data-account-connections></ul><ul data-account-requests></ul><button data-account-logout></button></div></div>`;
  let signedIn = false;
  global.fetch = vi.fn(async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (url === '/auth/session') return { ok: signedIn, status: signedIn ? 200 : 401, json: async () => ({ address: ADDRESS, csrf: 'csrf', connections: [] }) };
    if (url === '/auth/challenge') { expect(body.address).toBe(ADDRESS); return { ok: true, json: async () => ({ message: 'Non-payment login challenge' }) }; }
    if (url === '/auth/verify') { signedIn = true; return { ok: true, json: async () => ({ address: ADDRESS, csrf: 'csrf' }) }; }
    if (url === '/account/requests') return { ok: true, json: async () => ({ requests: [] }) };
    throw new Error('Unexpected endpoint');
  });
  mocks.provider.request.mockImplementation(async ({ method }) => method === 'eth_requestAccounts' ? [ADDRESS] : '0xsignature');
  await import('../../static/account.js'); await tick();
  expect(mocks.provider.request).not.toHaveBeenCalled();
  document.querySelector('[data-account-login]').click(); await tick(); await tick();
  expect(mocks.provider.request.mock.calls.map(([args]) => args.method)).toEqual(['eth_requestAccounts', 'personal_sign']);
  expect(document.querySelector('[data-account-details]').hidden).toBe(false);
  expect(mocks.execute).not.toHaveBeenCalled();
});
it('payment page refresh never signs and approval executes only once', async () => {
  document.body.innerHTML = `<div data-payment-request="request-id"><select data-payment-wallet></select>
    <button data-payment-approve disabled></button><button data-payment-refresh></button>
    <pre data-payment-summary></pre><p data-payment-status></p><pre data-payment-result></pre></div>`;
  let paid = false;
  global.fetch = vi.fn(async (url) => ({ ok: true, json: async () => {
    if (url === '/auth/session') return { address: ADDRESS, csrf: 'csrf' };
    if (url === '/status.json') return { payment: { receiver: ADDRESS } };
    if (url.endsWith('/approve')) return { service: 'instagram.profile', input: { url: 'https://www.instagram.com/instagram/' }, payment_key: 'mcp_key', authorization: 'approval', owner: ADDRESS };
    return { status: paid ? 'succeeded' : 'payment_required', price_cents: 5, owner: ADDRESS, service: 'instagram.profile', input: {}, ...(paid ? { result: { status: 'success' } } : {}) };
  } }));
  mocks.connect.mockResolvedValue(ADDRESS);
  mocks.execute.mockImplementation(async () => { paid = true; });
  await import('../../static/payment.js'); await tick();
  expect(mocks.execute).not.toHaveBeenCalled();
  document.querySelector('[data-payment-refresh]').click(); await tick();
  expect(mocks.connect).not.toHaveBeenCalled();
  const approve = document.querySelector('[data-payment-approve]');
  approve.click(); approve.click(); await tick(); await tick();
  expect(mocks.execute).toHaveBeenCalledTimes(1);
  expect(mocks.execute.mock.calls[0].slice(5, 7)).toEqual(['mcp_key', 'approval']);
  document.querySelector('[data-payment-refresh]').click(); await tick();
  expect(mocks.execute).toHaveBeenCalledTimes(1);
  expect(approve.disabled).toBe(true);
});

it('shows the rejected account and the actual access restriction without requesting a signature', async () => {
  document.body.innerHTML = `<div data-account><select data-account-wallet></select><button data-account-login></button>
    <span data-account-address></span><p data-account-status></p><div data-account-details hidden></div>
    <button data-account-approve></button><button data-account-deny></button><button data-account-logout></button></div>`;
  global.fetch = vi.fn(async url => ({ ok: false, status: url === '/auth/session' ? 401 : 403,
    json: async () => ({ error: { message: url === '/auth/session' ? 'Sign in with your wallet' : 'Self-service access is in limited validation' } }) }));
  mocks.provider.request.mockResolvedValue([ADDRESS]);
  await import('../../static/account.js'); await tick();
  document.querySelector('[data-account-login]').click(); await tick(); await tick();
  expect(document.querySelector('[data-account-address]').textContent).toBe(ADDRESS);
  expect(document.querySelector('[data-account-status]').textContent).toContain('site permissions');
  expect(document.querySelector('[data-account-status]').textContent).not.toContain('session expired');
  expect(mocks.provider.request.mock.calls.map(([args]) => args.method)).toEqual(['eth_requestAccounts']);
});

it('clears a signed-in state when the wallet changes accounts', async () => {
  document.body.innerHTML = `<div data-account>
    <select data-account-wallet></select><button data-account-login></button><span data-account-address></span>
    <p data-account-status></p><div data-account-consent hidden><button data-account-approve></button><button data-account-deny></button></div>
    <div data-account-details hidden><ul data-account-connections></ul><ul data-account-requests></ul><button data-account-logout></button></div></div>`;
  const handlers = {};
  mocks.provider.on = vi.fn((event, handler) => { handlers[event] = handler; });
  mocks.provider.removeListener = vi.fn();
  let signedIn = false;
  global.fetch = vi.fn(async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : {};
    if (url === '/auth/session') return { ok: signedIn, status: signedIn ? 200 : 401, json: async () => ({ address: ADDRESS, csrf: 'csrf', connections: [] }) };
    if (url === '/auth/challenge') return { ok: true, json: async () => ({ message: 'Non-payment login challenge' }) };
    if (url === '/auth/verify') { signedIn = true; return { ok: true, json: async () => ({ address: ADDRESS, csrf: 'csrf' }) }; }
    if (url === '/account/requests') return { ok: true, json: async () => ({ requests: [] }) };
    if (url === '/auth/logout') { expect(body).toEqual({}); signedIn = false; return { ok: true, json: async () => ({ status: 'signed_out' }) }; }
    throw new Error('Unexpected endpoint: ' + url);
  });
  mocks.provider.request.mockImplementation(async ({ method }) => method === 'eth_requestAccounts' ? [ADDRESS] : '0xsignature');
  await import('../../static/account.js'); await tick();
  document.querySelector('[data-account-login]').click(); await tick(); await tick();
  expect(handlers.accountsChanged).toEqual(expect.any(Function));
  handlers.accountsChanged([]); await tick(); await tick();
  expect(global.fetch).toHaveBeenCalledWith('/auth/logout', expect.objectContaining({ method: 'POST' }));
  expect(document.querySelector('[data-account-details]').hidden).toBe(true);
  expect(document.querySelector('[data-account-status]').textContent).toContain('changed');
});

it('distinguishes origin rejection, expired session, and pending settlement', async () => {
  const { responseError, requestStatus } = await import('../../static/self-service-ui.js');
  const error = await responseError({ status: 403, json: async () => ({ error: { message: 'A same-origin browser request is required' } }) });
  expect(error.message).toContain('origin');
  const expired = await responseError({ status: 401, json: async () => { throw new Error('not JSON'); } });
  expect(expired.message).toContain('session');
  expect(requestStatus({ status: 'reconciliation_required' })).toContain('do not pay again');
  expect(requestStatus({ status: 'succeeded' })).toContain('without paying');
});
