import sys
from pathlib import Path


PROTOCOLS_FILENAME = "JARVIS_PROTOCOLS.txt"
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)


class ProtocolsError(RuntimeError):
    pass


def load_protocols() -> str:
    path = BASE_DIR / PROTOCOLS_FILENAME
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProtocolsError(
            f"Required policy file {PROTOCOLS_FILENAME} is missing or unreadable. "
            "Restore it beside the Jarvis application before starting the AI."
        ) from exc
    if not text or len(text.split()) < 20:
        raise ProtocolsError(
            f"Required policy file {PROTOCOLS_FILENAME} is empty or too short. "
            "Add the operating instructions before starting the AI."
        )
    return text


def apply_protocols(system_instructions: str) -> str:
    base = (system_instructions or "").strip()
    policy = load_protocols()
    return f"{base}\n\n--- EDITABLE JARVIS PROTOCOLS ---\n{policy}"
