"""
Multilingual, adjustable-simplicity explanation layer.

Built once here, reused as-is by both Arth Bodh and Arth Raksha, per the
brief. This module only holds the *scaffolding* strings (labels, UI copy,
disclaimers) that must never depend on the LLM — anything grounded in a
user's actual data goes through GroundedExplainer instead, in whichever
language/depth the caller asks for.
"""
from __future__ import annotations
from .schemas import Language

_STRINGS = {
    "no_evidence": {
        Language.ENGLISH: "I can't find real evidence for this, so I won't guess.",
        Language.HINDI: "इसके लिए मुझे ठोस सबूत नहीं मिला, इसलिए मैं अंदाज़ा नहीं लगाऊँगा।",
        Language.HINGLISH: "Iske liye mujhe pakka evidence nahi mila, isliye main guess nahi karunga.",
    },
    "confirm_before_sending": {
        Language.ENGLISH: "Please review every detail below before you sign.",
        Language.HINDI: "साइन करने से पहले नीचे हर विवरण ध्यान से देखें।",
        Language.HINGLISH: "Sign karne se pehle neeche har detail ध्यान se dekhiye.",
    },
    "revoke_suggestion": {
        Language.ENGLISH: "You can revoke this approval in one click.",
        Language.HINDI: "आप इस अनुमति को एक क्लिक में रद्द कर सकते हैं।",
        Language.HINGLISH: "Aap is approval ko ek click mein revoke kar sakte hain.",
    },
}


def phrase(key: str, language: Language = Language.ENGLISH) -> str:
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(language, entry[Language.ENGLISH])
