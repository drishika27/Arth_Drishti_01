// Real client-side wallet signing via ethers.js + window.ethereum
// (MetaMask or any EIP-1193-compatible extension).
//
// This is the ONE place in the frontend that touches a wallet provider.
// It never asks for or sees a private key — connectWallet() and
// signAndSendPayload() both delegate to the extension's own
// eth_requestAccounts / eth_sendTransaction methods, which is where
// MetaMask shows the user its own review-and-sign UI and does the actual
// signing, entirely inside the extension. The backend only ever produces
// the unsigned `payload` this module hands off; nothing here can sign or
// send without the user approving MetaMask's own prompt.
import { BrowserProvider } from "ethers";

export function isWalletAvailable() {
  return typeof window !== "undefined" && !!window.ethereum;
}

export async function connectWallet() {
  if (!isWalletAvailable()) {
    throw new Error(
      "No wallet extension detected. Install MetaMask (or another EIP-1193 wallet) to connect for real."
    );
  }
  const provider = new BrowserProvider(window.ethereum);
  const accounts = await provider.send("eth_requestAccounts", []);
  if (!accounts || accounts.length === 0) {
    throw new Error("No account was authorized in your wallet.");
  }
  const network = await provider.getNetwork();
  return { address: accounts[0], chainId: Number(network.chainId) };
}

/**
 * Hands an already-confirmed backend payload ({to, value, data?, chain})
 * to the user's connected wallet for them to review and sign. Returns the
 * real transaction hash MetaMask gives back once the user approves —
 * this function does not wait for the transaction to be mined, and it
 * throws (never silently swallows) if the user rejects the prompt or the
 * wallet reports any other error.
 */
export async function signAndSendPayload(payload) {
  if (!isWalletAvailable()) {
    throw new Error("No wallet extension available to sign with.");
  }
  const provider = new BrowserProvider(window.ethereum);
  const signer = await provider.getSigner();

  const tx = { to: payload.to, value: payload.value || "0x0" };
  if (payload.data) tx.data = payload.data;

  const sent = await signer.sendTransaction(tx); // <- MetaMask's own sign/confirm UI appears here
  return sent.hash;
}
