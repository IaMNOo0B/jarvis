import sys
from pathlib import Path


PROTOCOLS_FILENAME = "JARVIS_PROTOCOLS.txt"
BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
REQUIRED_SECTIONS = {
    "SYSTEM_PROMPT",
    "CONSULT_SYSTEM_PROMPT",
    "RESEARCH_AGAIN_PROMPT",
    "OPERATING_PROTOCOLS",
}


class ProtocolsError(RuntimeError):
    pass


def _read_sections() -> dict[str, str]:
    path = BASE_DIR / PROTOCOLS_FILENAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProtocolsError(
            f"Required policy file {PROTOCOLS_FILENAME} is missing or unreadable. "
            "Restore it beside the Jarvis application before starting the AI."
        ) from exc

    sections = {}
    active = None
    buffer = []
    for line in lines:
        if active is None and line.startswith("=== ") and line.endswith(" ===") and not line.startswith("=== END "):
            name = line[4:-4].strip()
            if name in sections:
                raise ProtocolsError(f"Duplicate section {name} in {PROTOCOLS_FILENAME}.")
            active = name
            buffer = []
            continue
        if active is not None and line == f"=== END {active} ===":
            sections[active] = "\n".join(buffer).strip()
            active = None
            buffer = []
            continue
        if active is not None:
            buffer.append(line)

    if active is not None:
        raise ProtocolsError(f"Section {active} is missing its end marker in {PROTOCOLS_FILENAME}.")
    missing = REQUIRED_SECTIONS.difference(sections)
    if missing:
        raise ProtocolsError(
            f"{PROTOCOLS_FILENAME} is missing required sections: {', '.join(sorted(missing))}."
        )
    if any(not sections[name] for name in REQUIRED_SECTIONS):
        raise ProtocolsError(f"One or more required sections in {PROTOCOLS_FILENAME} are empty.")
    return sections


def load_prompt(name: str) -> str:
    sections = _read_sections()
    if name not in {"SYSTEM_PROMPT", "CONSULT_SYSTEM_PROMPT", "RESEARCH_AGAIN_PROMPT"}:
        raise ProtocolsError(f"Unknown prompt section: {name}")
    return sections[name]


def load_protocols() -> str:
    policy = _read_sections()["OPERATING_PROTOCOLS"]
    if len(policy.split()) < 20:
        raise ProtocolsError(
            f"Operating protocols in {PROTOCOLS_FILENAME} are empty or too short."
        )
    return policy


def apply_protocols(system_instructions: str) -> str:
    base = (system_instructions or "").strip()
    policy = load_protocols()
    return f"{base}\n\n--- EDITABLE JARVIS PROTOCOLS ---\n{policy}"
