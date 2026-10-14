import { collectWallets } from './wallet.js';
import { connectBrowserWallet, executeReachSocial } from './reachsocial-client.js';

const root = document.querySelector('[data-payment-request]');
if (root) {
  const id = root.dataset.paymentRequest;
  const path = '/account/requests/' + encodeURIComponent(id);
  const select = root.querySelector('[data-payment-wallet]');
  const approve = root.querySelector('[data-payment-approve]');
  const status = root.querySelector('[data-payment-status]');
  let wallets = new Map();
  let identity, request, busy = false;
  async function api(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      redirect: 'error', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(identity ? { 'X-ReachSocial-CSRF': identity.csrf } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw new Error(`Request failed (${response.status}). Sign in with the wallet that created this request.`);
    return response.json();
  }
  const controls = () => { approve.disabled = busy || !wallets.size || request?.status !== 'payment_required'; };
  collectWallets(items => {
    wallets = items;
    const selected = select.value;
    select.replaceChildren(...[...items].map(([id, wallet]) => new Option(wallet.info.name, id)));
    if (items.has(selected)) select.value = selected;
    controls();
  });
  async function refresh() {
    identity = await api('/auth/session');
    request = await api(path);
    const metadata = await api('/status.json');
    root.querySelector('[data-payment-summary]').textContent = JSON.stringify({
      service: request.service, input: request.input, price: '$0.05 USDC', network: 'Base mainnet',
      receiver: metadata.payment?.receiver, request_id: id,
    }, null, 2);
    status.textContent = request.message || request.status;
    const result = root.querySelector('[data-payment-result]');
    result.hidden = !request.result;
    result.textContent = request.result ? JSON.stringify(request.result, null, 2) : '';
    controls();
  }
  approve.onclick = async () => {
    if (busy || approve.disabled) return;
    busy = true; controls();
    try {
      const provider = wallets.get(select.value)?.provider;
      const account = await connectBrowserWallet(provider);
      if (account.toLowerCase() !== request.owner || account.toLowerCase() !== identity.address) {
        throw new Error('Select the wallet that owns this request.');
      }
      const approval = await api(path + '/approve', {});
      status.textContent = 'Waiting for your wallet approval…';
      await executeReachSocial(provider, account, approval.service, approval.input,
        'https://reachsocial.dev', approval.payment_key, approval.authorization);
      await refresh();
    } catch (error) {
      status.textContent = error.message + ' Use Refresh result before taking another action.';
      request = undefined;
    } finally { busy = false; controls(); }
  };
  root.querySelector('[data-payment-refresh]').onclick = () => refresh().catch(error => { status.textContent = error.message; });
  refresh().catch(error => { status.textContent = error.message; });
}
