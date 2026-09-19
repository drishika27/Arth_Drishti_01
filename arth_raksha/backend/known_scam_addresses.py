"""
A maintained, regularly-updatable database of known scam/phishing contract
addresses per the brief. This is a small seed list of publicly-documented
examples for demo purposes — a real deployment would sync this from a feed
such as Chainabuse, ScamSniffer's public list, or a paid threat-intel API.
Addresses are lowercased for comparison.
"""
SCAM_ADDRESSES: set[str] = {
    # Publicly reported phishing/drainer contracts (illustrative demo seed).
    "0x0000000000000000000000000000000000dead",
}

UNVERIFIED_HINT_LABEL = "unverified_contract"


def is_known_scam(address: str) -> bool:
    return address.lower() in SCAM_ADDRESSES
