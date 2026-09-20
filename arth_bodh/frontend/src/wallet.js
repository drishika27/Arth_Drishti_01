// Browser-wallet helpers (MetaMask or any EIP-1193 wallet). ArthDrishti only ever asks the
// wallet for (1) the public address and (2) a signature over a plain-text ownership message.
// It never sees a private key or seed phrase, and nothing here can send a transaction.
export const hasWallet = () => typeof window !== 'undefined' && !!window.ethereum;

const NO_WALLET = 'No browser wallet found. Install MetaMask (metamask.io) or another Ethereum wallet, then reload this page.';

function friendly(e) {
  if (e?.code === 4001 || /reject|denied|cancel/i.test(e?.message || '')) return new Error('You cancelled the request in your wallet.');
  if (e?.code === -32002) return new Error('A wallet request is already open — check your wallet extension.');
  return e instanceof Error ? e : new Error(e?.message || 'The wallet request failed.');
}

export async function requestAccount() {
  if (!hasWallet()) throw new Error(NO_WALLET);
  try {
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    if (!accounts?.length) throw new Error('No account was shared from your wallet.');
    return accounts[0];
  } catch (e) { throw friendly(e); }
}

export async function signText(address, message) {
  const hex = '0x' + Array.from(new TextEncoder().encode(message), (b) => b.toString(16).padStart(2, '0')).join('');
  try {
    return await window.ethereum.request({ method: 'personal_sign', params: [hex, address] });
  } catch (e) { throw friendly(e); }
}
