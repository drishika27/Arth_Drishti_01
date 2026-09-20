import { Card, Pill } from '../ui';

// Real wallet data (balances, prices, transactions) arrives with the crypto
// phase. Until then these pages state plainly that no wallet is connected
// instead of showing invented balances.
function NotConnected({ title, text }) {
  return <>
    <div className="section-intro"><Pill tone="green">Arth Raksha</Pill><h2>{title}</h2><p>{text}</p></div>
    <Card><div className="empty">No wallet connected yet.</div></Card>
  </>;
}

export const Wallet = () => <NotConnected title="Your wallet, in view." text="Connect a wallet address to see balances and activity. Arth Raksha never asks for seed phrases or private keys." />;
export const Assets = () => <NotConnected title="Your digital assets at a glance." text="Balances and prices appear once a wallet is connected." />;
export const Transactions = () => <NotConnected title="Transactions with context." text="Your on-chain activity appears once a wallet is connected." />;
export const Portfolio = () => <NotConnected title="Allocation you can actually read." text="Portfolio value and allocation appear once a wallet is connected." />;
export const Security = () => <NotConnected title="Protect the wallet without touching secrets." text="Risk checks run against your connected wallet's public data." />;
