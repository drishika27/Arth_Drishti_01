# Dataset provenance

`ethereum_fraud_dataset.csv` — 4,681 Ethereum addresses (2,502 normal,
2,179 flagged fraudulent/scam), each with 48 engineered behavioral
features (transaction timing, sent/received counts and values, ERC20
token activity, unique counterparty counts).

Downloaded 2026-09-14 from a public GitHub mirror used for an MSc thesis:
https://github.com/sfarrugia15/Ethereum_Fraud_Detection/blob/master/Account_Stats/Complete.csv

That mirror traces back to the "Ethereum Fraud Detection Dataset"
originally published on Kaggle (search: "Ethereum Fraud Detection
Dataset"), itself built from Etherscan's labelled-address data and widely
cited in academic fraud-detection literature (see e.g. arXiv:2301.01809).

**License note, stated honestly:** the GitHub mirror carries no LICENSE
file, and the original Kaggle listing's exact terms weren't re-verified
here. This is used as a research/educational dataset for this project,
consistent with how it appears across many public academic repos and
papers. Before any commercial/production use, re-source it directly from
Kaggle (or a feed you have clear rights to, e.g. Chainabuse or your own
Etherscan-labelled export) and confirm the license explicitly.
