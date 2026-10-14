// Display server decisions without turning every rejection into a session error.
export async function responseError(response) {
  let detail = '';
  try {
    const body = await response.json();
    detail = body.error?.message || body.detail || '';
  } catch { /* A proxy may return HTML instead of API JSON. */ }
  const messages = {
    'Self-service access is in limited validation': 'This wallet is not enabled for the current pilot. Choose the approved buyer account in your wallet’s site permissions, then reconnect.',
    'A same-origin browser request is required': 'The browser could not verify this page’s origin. Open https://reachsocial.dev/account directly and try again.',
    'Invalid session protection token': 'This page’s session has changed. Refresh it and sign in again before continuing.',
    'Authorization expired or already used': 'This connection link has expired or was already used. Restart the connecting client with its saved checkpoint.',
    'Authorization expired': 'This connection link has expired. Restart the connecting client with its saved checkpoint.',
  };
  const fallback = response.status === 401 ? 'Sign in with your wallet to continue. Your session may have expired.'
    : response.status === 403 ? 'Access was denied. Check the wallet account connected to this site.'
    : response.status === 429 ? 'Too many requests. Wait a minute before trying again.'
    : response.status >= 500 ? 'ReachSocial is temporarily unavailable. Refresh the existing request; do not create another payment.'
    : `Request failed (${response.status}).`;
  const error = new Error(messages[detail] || (typeof detail === 'string' && detail.length <= 500 ? detail : '') || fallback);
  error.status = response.status;
  return error;
}

export function walletError(error) {
  if (error?.code === 4001) return 'You declined the wallet prompt. No new approval was submitted by this page.';
  if (error?.code === -32002) return 'A wallet prompt is already open. Finish or dismiss it in your wallet extension.';
  return error?.message || 'The wallet could not complete this step. Check the wallet extension.';
}

export function requestStatus(request) {
  return ({
    payment_required: 'Ready for your payment approval.',
    awaiting_approval: 'An approval window is open. Complete the wallet prompt, or refresh after it expires.',
    succeeded: 'Result ready. You can retrieve it again without paying.',
    failed: 'The request did not succeed. Keep this request for support or refund review; do not pay again.',
    reconciliation_required: 'Payment or processing needs review. Refresh this request for updates; do not pay again.',
    expired: 'This unpaid request expired. It can no longer accept a payment.',
  })[request.status] || request.message || 'Checking request status…';
}

export const requestLabel = status => ({ payment_required: 'Awaiting payment', awaiting_approval: 'Approval in progress', succeeded: 'Result ready', failed: 'Failed', reconciliation_required: 'Under review', expired: 'Expired' })[status] || 'Pending';
