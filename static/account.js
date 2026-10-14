import { collectWallets } from './wallet.js?v=20261014-4';
import { responseError, walletError, requestLabel } from './self-service-ui.js';

const root = document.querySelector('[data-account]');
if (root) {
  const status = root.querySelector('[data-account-status]');
  const select = root.querySelector('[data-account-wallet]');
  const login = root.querySelector('[data-account-login]');
  let wallets = new Map();
  let identity;
  let signingIn = false;
  const flow = new URL(location.href).searchParams.get('authorize');
  async function api(path, body) {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      redirect: 'error', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(identity ? { 'X-ReachSocial-CSRF': identity.csrf } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw await responseError(response);
    return response.json();
  }
  collectWallets((items) => {
    wallets = items;
    const selected = select.value;
    select.replaceChildren(...[...items].map(([id, wallet]) => new Option(wallet.info.name, id)));
    if (!items.size) select.add(new Option('No browser wallet detected', ''));
    select.disabled = !items.size || signingIn;
    if (items.has(selected)) select.value = selected;
    login.disabled = signingIn || !items.size;
  });
  async function render() {
    identity = await api('/auth/session');
    status.textContent = `Signed in as ${identity.address}`;
    root.querySelector('[data-account-details]').hidden = false;
    const list = root.querySelector('[data-account-connections]');
    list.replaceChildren();
    for (const connection of identity.connections) {
      const item = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = connection.client_id + ' ';
      const button = document.createElement('button');
      button.className = 'copy-button'; button.textContent = 'Revoke';
      button.onclick = () => run(async () => { await api('/auth/connections/revoke', { id: connection.id }); await render(); });
      item.append(name, button); list.append(item);
    }
    if (!identity.connections.length) list.textContent = 'No connected agents.';
    const requests = await api('/account/requests');
    const requestList = root.querySelector('[data-account-requests]');
    requestList.replaceChildren();
    for (const request of requests.requests) {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = '/pay/' + encodeURIComponent(request.request_id);
      link.textContent = `${request.service} · ${requestLabel(request.status)}`;
      item.append(link); requestList.append(item);
    }
    if (!requests.requests.length) requestList.textContent = 'No requests yet.';
    if (flow) {
      const consent = await api('/auth/consent?flow=' + encodeURIComponent(flow));
      root.querySelector('[data-account-client]').textContent = `${consent.client_name} (${consent.client_id}). Return address: ${consent.redirect_uri}. Only allow a connection you started; a localhost address refers to an application on your computer.`;
      root.querySelector('[data-account-consent]').hidden = false;
    }
  }
  async function run(action) {
    try { status.dataset.state = ''; await action(); } catch (error) { status.dataset.state = 'error'; status.textContent = walletError(error); }
  }
  login.onclick = () => run(async () => {
    if (signingIn) return;
    signingIn = true;
    login.disabled = true;
    try {
      const provider = wallets.get(select.value)?.provider;
      if (!provider) throw new Error('Select an installed browser wallet.');
      const [address] = await provider.request({ method: 'eth_requestAccounts' });
      if (!/^0x[0-9a-fA-F]{40}$/.test(address || '')) throw new Error('The wallet did not share an account. Check its site permissions.');
      const addressNode = root.querySelector('[data-account-address]');
      if (addressNode) addressNode.textContent = address;
      status.textContent = 'Approve the non-payment sign-in message in your wallet.';
      const challenge = await api('/auth/challenge', { address });
      const bytes = new TextEncoder().encode(challenge.message);
      const hex = '0x' + [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
      const signature = await provider.request({ method: 'personal_sign', params: [hex, address] });
      identity = await api('/auth/verify', { signature });
      await render();
    } finally { signingIn = false; login.disabled = !wallets.size; }
  });
  async function consent(approve) {
    const result = await api('/auth/consent', { flow, approve });
    // The server returns only the previously validated OAuth client's redirect.
    location.assign(result.redirect);
  }
  root.querySelector('[data-account-approve]').onclick = () => run(() => consent(true));
  root.querySelector('[data-account-deny]').onclick = () => run(() => consent(false));
  root.querySelector('[data-account-logout]').onclick = () => run(async () => {
    await api('/auth/logout', {}); identity = undefined;
    root.querySelector('[data-account-details]').hidden = true;
    root.querySelector('[data-account-consent]').hidden = true;
    status.textContent = 'Signed out.';
  });
  render().catch(error => {
    status.textContent = error.status === 401
      ? (wallets.size ? 'Choose a wallet and sign in. This signature does not authorize a payment.' : 'No browser wallet detected. Open this page with MetaMask or another installed wallet extension.')
      : walletError(error);
    status.dataset.state = error.status === 401 ? '' : 'error';
  });
}
