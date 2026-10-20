"""Compatibility exports for JARVIS's editable persona and response policy.

Prompt text and response-filter phrases live in JARVIS_PROTOCOLS.txt.
"""

from protocols import load_prompt


# Retained as compatibility aliases for older imports. The brain reloads prompts
# from the TXT file during active turns instead of relying on these snapshots.
SYSTEM_PROMPT = load_prompt("SYSTEM_PROMPT")
CONSULT_SYSTEM_PROMPT = load_prompt("CONSULT_SYSTEM_PROMPT")
RESEARCH_AGAIN_PROMPT = load_prompt("RESEARCH_AGAIN_PROMPT")


def is_hedged(text: str) -> bool:
    """Detect configured hedge phrases from the current TXT policy."""
    low = str(text or "").casefold()
    patterns = [
        line.strip().casefold()
        for line in load_prompt("HEDGE_PATTERNS").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return any(pattern in low for pattern in patterns)
