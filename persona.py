"""
JARVIS persona — the system prompt that makes him *JARVIS*.

Two jobs:
  1. Voice personality: British butler, precise, dry wit, addresses the user as "sir".
  2. The all-rounder rule: he NEVER says "I don't know" — he investigates with the
     tools he has (search, browse, memory, code execution, system diagnostics) and
     always finishes with a usable answer or a concrete action.
"""

from protocols import load_prompt

SYSTEM_PROMPT = load_prompt("SYSTEM_PROMPT")
CONSULT_SYSTEM_PROMPT = load_prompt("CONSULT_SYSTEM_PROMPT")
RESEARCH_AGAIN_PROMPT = load_prompt("RESEARCH_AGAIN_PROMPT")

# Phrases that mean the model is about to say "I don't know" out loud.
HEDGE_PATTERNS = [
    "i don't know",
    "i do not know",
    "i dont know",
    "i'm not sure",
    "i am not sure",
    "i cannot assist",
    "i can't assist",
    "i cannot help",
    "i have no information",
    "no information about",
    "i don't have information",
    "i don't have access to",
    "as an ai",
    "unable to find any information",
    "i'm unable to",
    "i am unable to",
    "cannot provide that",
    "i can't answer",
    "i cannot answer",
    "no idea",
]


def is_hedged(text: str) -> bool:
    """True if the spoken reply still contains an ignorance-hedge."""
    low = text.lower()
    return any(p in low for p in HEDGE_PATTERNS)
