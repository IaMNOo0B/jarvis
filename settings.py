"""
JARVIS settings panel — a Qt dialog so nobody has to hand-edit YAML again.

Open it from the HUD (gear button) or with Ctrl+Alt+S.

Tabs: Voice, API Keys, Brain, HUD, Routines, Safety.

Persistence:
  * settings.local.yaml — the panel's overrides, deep-merged over config.yaml
    by brain.load_config(). Gitignored, never committed.
  * secrets.local.yaml — API keys only. Merged with whatever is already there,
    so the Gemini key written by set_cloud_key.py is preserved.

Live apply (no restart needed): voice engine + API keys (the speaker is
rebuilt on the fly) and HUD corner/size/click-through. Everything else needs
a restart — the dialog says so at the bottom.
"""

import os

import yaml
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QDoubleSpinBox, QFormLayout, QLabel, QLineEdit,
                             QSpinBox, QTabWidget, QVBoxLayout, QWidget)

_BASE = os.path.dirname(os.path.abspath(__file__))
# Writable locations: next to the repo in dev, %APPDATA%/JARVIS when installed.
from paths import user_file
SETTINGS_PATH = user_file("settings.local.yaml")
SECRETS_PATH = user_file("secrets.local.yaml")

# (tab, dotted key, label, kind, options, help text)
# kind: text | password | combo | check | double | int
# "secret:" keys live in secrets.local.yaml, everything else in settings.local.yaml
FIELDS = [
    ("Voice", "voice.tts_backend", "Voice engine", "combo",
     ["piper", "fish", "elevenlabs"],
     "Neural voices need an API key (API Keys tab). Applies live."),
    ("Voice", "voice.fish_voice_id", "Fish Audio voice ID", "text", None,
     "Model ID from the voice page URL on fish.audio."),
    ("Voice", "voice.elevenlabs_voice_id", "ElevenLabs voice ID", "text", None,
     "Voice ID from your ElevenLabs voice library."),
    ("Voice", "voice.tts_voice", "Piper voice (offline)", "text", None,
     "Used when the engine is piper, or as fallback."),
    ("Voice", "voice.wake_threshold", "Wake-word sensitivity", "double",
     (0.1, 0.9), "Lower = easier to trigger. Needs restart."),
    ("Voice", "voice.stt_language", "Speech language", "combo",
     ["auto", "en", "hi"],
     "auto = detects Hindi-English mix per sentence. Needs restart."),
    ("Voice", "voice.wake_word_cloud", "Cloud wake word", "text", None,
     "'hello jarvis' wakes the cloud brain. Needs a trained model + restart."),

    ("API Keys", "secret:gemini_api_key", "Gemini API key", "password", None,
     "Online brain. Free key: aistudio.google.com/apikey"),
    ("API Keys", "secret:fish_api_key", "Fish Audio API key", "password", None,
     "fish.audio → API keys."),
    ("API Keys", "secret:elevenlabs_api_key", "ElevenLabs API key", "password",
     None, "elevenlabs.io → API keys."),
    ("API Keys", "secret:telegram_bot_token", "Telegram bot token", "password",
     None, "Phone link. Create via @BotFather on Telegram."),

    ("Phone", "telegram.enabled", "Phone link (Telegram)", "check", None,
     "Control JARVIS from your phone. Needs restart."),
    ("Phone", "telegram.allowed_user_ids", "Your Telegram user ID", "text",
     None, "Numeric ID from @userinfobot. Comma-separated if several."),

    ("Brain", "brain.mode", "Driving brain", "combo",
     ["local_first", "cloud_first"], "Needs restart."),
    ("Brain", "brain.cloud.provider", "Cloud provider", "combo",
     ["gemini", "openai"], "Needs restart."),
    ("Brain", "brain.cloud.model", "Cloud model", "text", None,
     "Empty = provider default. Needs restart."),
    ("Brain", "brain.local_model", "Local model (Ollama tag)", "text", None,
     "Needs restart."),
    ("Brain", "brain.temperature", "Temperature", "double", (0.0, 1.5),
     "Needs restart."),

    ("HUD", "hud.corner", "Corner", "combo",
     ["bottom-right", "bottom-left", "top-right", "top-left"], "Applies live."),
    ("HUD", "hud.width", "Width", "int", (300, 900), "Applies live."),
    ("HUD", "hud.height", "Height", "int", (400, 1100), "Applies live."),
    ("HUD", "hud.click_through", "Click-through", "check", None,
     "Applies live. Off = you can drag the HUD."),

    ("Routines", "routines.morning_briefing", "Morning briefing (HH:MM)",
     "text", None, "Empty disables. Needs restart."),
    ("Routines", "routines.evening_briefing", "Evening briefing (HH:MM)",
     "text", None, "Empty disables. Needs restart."),
    ("Routines", "routines.weather_location", "Weather location", "text", None,
     "Empty = auto by IP."),
    ("Routines", "routines.startup_greeting", "Greeting on startup", "check",
     None, ""),

    ("Safety", "safety.confirm_destructive", "Confirm shutdown / restart",
     "check", None, ""),
    ("Safety", "presence.enabled", "Webcam presence sensor", "check", None,
     "Needs restart."),
    ("Safety", "presence.greet_on_return", "Greet on return", "check", None, ""),
    ("Safety", "screen_watcher.enabled", "Watching eyes", "check", None,
     "He glances at your screen and speaks up when you look stuck. "
     "Captures stay in RAM. Needs the cloud brain + restart."),
    ("Safety", "screen_watcher.interval_seconds", "Watching eyes: check every",
     "int", (30, 600),
     "Seconds between glances. Needs restart."),
]


# ------------------------------------------------------------ dotted helpers
def _get_path(cfg: dict, dotted: str, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _set_path(cfg: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _load_secrets() -> dict:
    try:
        if os.path.isfile(SECRETS_PATH):
            with open(SECRETS_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


# ------------------------------------------------------------------ saving
def save_panel(values: dict, secrets: dict) -> None:
    """Persist the dialog. values: dotted -> value; secrets: name -> key.

    Only non-empty secrets are written, so a blank password field keeps the
    existing key instead of wiping it.
    """
    nested: dict = {}
    for dotted, val in values.items():
        _set_path(nested, dotted, val)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(nested, f, sort_keys=False, allow_unicode=True)

    secrets = {k: v for k, v in secrets.items() if str(v or "").strip()}
    if secrets:
        merged = _load_secrets()
        merged.update({k: str(v).strip() for k, v in secrets.items()})
        with open(SECRETS_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, sort_keys=False)


# ------------------------------------------------------------------- dialog
class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("JARVIS Settings")
        self.setMinimumWidth(480)
        self._widgets: dict = {}
        secrets = _load_secrets()

        tabs = QTabWidget()
        pages: dict = {}
        for tab, dotted, label, kind, options, help_text in FIELDS:
            if tab not in pages:
                page = QWidget()
                pages[tab] = (page, QFormLayout(page))
                tabs.addTab(page, tab)
            _page, form = pages[tab]

            if kind == "combo":
                w = QComboBox()
                w.addItems(options)
                cur = str(_get_path(cfg, dotted, options[0]))
                if cur in options:
                    w.setCurrentText(cur)
            elif kind == "check":
                w = QCheckBox()
                w.setChecked(bool(_get_path(cfg, dotted, False)))
            elif kind == "double":
                lo, hi = options
                w = QDoubleSpinBox()
                w.setRange(lo, hi)
                w.setSingleStep(0.05)
                w.setDecimals(2)
                try:
                    w.setValue(float(_get_path(cfg, dotted, lo)))
                except (TypeError, ValueError):
                    w.setValue(lo)
            elif kind == "int":
                lo, hi = options
                w = QSpinBox()
                w.setRange(lo, hi)
                try:
                    w.setValue(int(_get_path(cfg, dotted, lo)))
                except (TypeError, ValueError):
                    w.setValue(lo)
            elif kind == "password":
                w = QLineEdit()
                w.setEchoMode(QLineEdit.EchoMode.Password)
                secret_key = dotted.split(":", 1)[1]
                if secrets.get(secret_key):
                    w.setPlaceholderText("•••••••• (saved — leave blank to keep)")
            else:  # text
                w = QLineEdit()
                w.setText(str(_get_path(cfg, dotted, "") or ""))

            if help_text:
                w.setToolTip(help_text)
            form.addRow(label, w)
            self._widgets[dotted] = (kind, w)

        note = QLabel(
            "Voice engine & API keys apply immediately. "
            "Everything else needs a restart.")
        note.setWordWrap(True)
        note.setStyleSheet("color: rgba(160,200,220,0.75);")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _read_values(self) -> tuple[dict, dict]:
        values: dict = {}
        secrets: dict = {}
        for dotted, (kind, w) in self._widgets.items():
            if kind == "combo":
                val = w.currentText()
            elif kind == "check":
                val = bool(w.isChecked())
            elif kind in ("double", "int"):
                val = w.value()
            else:
                val = w.text().strip()
            if dotted.startswith("secret:"):
                secrets[dotted.split(":", 1)[1]] = val
            else:
                values[dotted] = val
        return values, secrets

    def accept(self) -> None:  # noqa: N802 (Qt naming)
        values, secrets = self._read_values()
        save_panel(values, secrets)
        super().accept()


def open_settings_dialog(cfg: dict, parent=None) -> bool:
    """Show the dialog; True if the user pressed OK (settings were saved)."""
    dlg = SettingsDialog(cfg, parent)
    return dlg.exec() == dlg.DialogCode.Accepted
