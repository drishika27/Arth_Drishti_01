"""
A small, maintained allow-list of well-known, legitimate contracts that are
safe to mark "verified" without a paid Etherscan API key. Mirrors the same
pattern as known_scam_addresses.py: a real (if incomplete) list, never a
guess. Anything not on this list is simply "not known to us" — that is
surfaced honestly as spender_verified=False, not "verified safe".

A production deployment would replace/extend this with a live query against
Etherscan's contract-verification API or a maintained registry feed.
"""

VERIFIED_CONTRACTS: dict[str, str] = {
    # Uniswap
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Router",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 Router 2",
    "0x000000000022d473030f116ddee9f6b43ac78ba3": "Permit2 (Uniswap)",
    "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router",
    # 1inch
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch V5 Router",
    "0x1111111254fb6c44bac0bed2854e76f90643097d": "1inch V4 Router",
    # SushiSwap
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": "SushiSwap Router",
    # OpenSea
    "0x00000000006c3852cbef3e08e8df289169ede581": "OpenSea Seaport 1.1",
    "0x0000000000000068f116a894984e2db1123eb395": "OpenSea Seaport 1.6",
    # Wrapped ETH
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH9",
    # Curve
    "0x99a58482bd75cbab83b27ec03ca68ff489b5788f": "Curve Router",
}


def is_verified_contract(address: str) -> bool:
    return address.lower() in VERIFIED_CONTRACTS


def verified_label(address: str) -> str | None:
    return VERIFIED_CONTRACTS.get(address.lower())
