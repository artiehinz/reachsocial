import { collectWallets } from './wallet.js?v=20261015-3';
import { responseError, walletError, requestStatus } from './self-service-ui.js';
import { connectBrowserWallet, executeReachSocial } from './reachsocial-client.js?v=20261015-2';

const root = document.querySelector('[data-payment-request]');
if (root) {
  const id = root.dataset.paymentRequest;
  const path = '/account/requests/' + encodeURIComponent(id);
  const select = root.querySelector('[data-payment-wallet]');
  const approve = root.querySelector('[data-payment-approve]');
  const status = root.querySelector('[data-payment-status]');
  let wallets = new Map();
  let identity, request, busy = false;
  let removeWalletListeners = () => {};
  async function api(url, body) {
    const response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      redirect: 'error', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(identity ? { 'X-ReachSocial-CSRF': identity.csrf } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw await responseError(response);
    return response.json();
  }
  const controls = () => { approve.disabled = busy || !wallets.size || request?.status !== 'payment_required' || request?.price_cents !== 5; };
  collectWallets(items => {
    wallets = items;
    const selected = select.value;
    select.replaceChildren(...[...items].map(([id, wallet]) => new Option(wallet.info.name, id)));
    if (!items.size) select.add(new Option('No browser wallet detected', ''));
    select.disabled = !items.size;
    if (items.has(selected)) select.value = selected;
    controls();
  });
  async function refresh() {
    identity = await api('/auth/session');
    request = await api(path);
    const metadata = await api('/status.json');
    const summary = root.querySelector('[data-payment-summary]');
    const facts = document.createElement('dl');
    facts.className = 'request-facts';
    for (const [label, value] of [
      ['Service', request.service], ['Target', request.input?.url || JSON.stringify(request.input || {})],
      ['Price', typeof request.price_cents === 'number' ? `$${(request.price_cents / 100).toFixed(2)} USDC` : 'Unavailable'],
      ['Network', 'Base mainnet'], ['Receiving wallet', metadata.payment?.receiver || 'Unavailable'],
    ]) {
      const row = document.createElement('div');
      const term = document.createElement('dt'); term.textContent = label;
      const definition = document.createElement('dd'); definition.textContent = value;
      row.append(term, definition); facts.append(row);
    }
    summary.replaceChildren(facts);
    status.textContent = requestStatus(request);
    status.dataset.state = ['failed', 'reconciliation_required'].includes(request.status) ? 'error' : '';
    const reference = root.querySelector('[data-payment-reference]');
    if (reference) reference.textContent = id;
    const result = root.querySelector('[data-payment-result]');
    result.hidden = !request.result;
    result.textContent = request.result ? JSON.stringify(request.result, null, 2) : '';
    controls();
  }
  async function invalidateWalletSession(message) {
    removeWalletListeners();
    removeWalletListeners = () => {};
    if (identity) {
      try { await api('/auth/logout', {}); } catch { /* The stale session is no longer usable here. */ }
    }
    identity = undefined;
    request = undefined;
    status.dataset.state = 'error';
    status.textContent = message;
    controls();
  }
  function watchWallet(provider) {
    removeWalletListeners();
    if (!provider?.on) { removeWalletListeners = () => {}; return; }
    const changed = () => { void invalidateWalletSession('Your wallet account or network changed. Sign in again and refresh this request before approving anything.'); };
    provider.on('accountsChanged', changed);
    provider.on('chainChanged', changed);
    removeWalletListeners = () => {
      provider.removeListener?.('accountsChanged', changed);
      provider.removeListener?.('chainChanged', changed);
    };
  }
  approve.onclick = async () => {
    if (busy || approve.disabled) return;
    busy = true; controls();
    try {
      const provider = wallets.get(select.value)?.provider;
      const account = await connectBrowserWallet(provider);
      if (account.toLowerCase() !== request.owner || account.toLowerCase() !== identity.address) {
        throw new Error(`Your wallet shared ${account}. This request belongs to ${request.owner}. Change the account allowed for reachsocial.dev in your wallet’s site permissions.`);
      }
      watchWallet(provider);
      const approval = await api(path + '/approve', {});
      status.textContent = 'Waiting for your wallet approval…';
      await executeReachSocial(provider, account, approval.service, approval.input,
        'https://reachsocial.dev', approval.payment_key, approval.authorization,
        approval.payment_endpoint);
      await refresh();
    } catch (error) {
      status.dataset.state = 'error';
      status.textContent = walletError(error) + ' Use Refresh result before taking another action.';
      request = undefined;
    } finally { busy = false; controls(); }
  };
  root.querySelector('[data-payment-refresh]').onclick = () => refresh().catch(error => { status.dataset.state = 'error'; status.textContent = walletError(error); });
  refresh().catch(error => { status.dataset.state = 'error'; status.textContent = walletError(error); });
}
