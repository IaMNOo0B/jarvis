"""
JARVIS phone link — Telegram channel (Phase 5).

The PC polls Telegram's servers (long polling), so there is no port
forwarding, no open ports, no extra server. Your phone's Telegram app
becomes a remote for JARVIS: send text or a voice note, his brain answers.

Setup:
  1. Talk to @BotFather on Telegram -> /newbot -> copy the token.
  2. Settings panel (Ctrl+Alt+S) -> API Keys -> "Telegram bot token",
     or set TELEGRAM_BOT_TOKEN in the environment, or put
     telegram_bot_token in secrets.local.yaml.
  3. Find your numeric Telegram user ID (ask @userinfobot) and list it in
     config.yaml -> telegram.allowed_user_ids. ONLY those IDs get answers.
  4. config.yaml -> telegram.enabled: true. Restart.

Security: updates from anyone not in allowed_user_ids are silently
ignored. The channel never touches the mic or speakers — pure chat.

No new dependencies: stdlib + requests (long polling, not asyncio).
"""

import io
import threading
import time

import requests

_API = "https://api.telegram.org/bot{token}/{method}"
_FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
_MAX_SEND = 4000  # Telegram message limit is 4096; stay safely under it


def _chunk(text, size=_MAX_SEND):
    text = text or ""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


class TelegramChannel:
    """Polls Telegram and routes chat into the brain.

    handle_text(text) -> reply text. transcribe_voice(float32 mono @16kHz
    numpy array) -> transcript text, or None to disable voice notes.
    """

    def __init__(self, token: str, allowed_user_ids=(), handle_text=None,
                 transcribe_voice=None, poll_timeout: int = 50, api=None,
                 on_note=None):
        self.token = token
        # allowed_user_ids: list of ints, or a comma-separated string
        # (the settings panel writes text).
        if isinstance(allowed_user_ids, str):
            allowed_user_ids = [u.strip() for u in allowed_user_ids.split(",")]
        self.allowed = {int(u) for u in (allowed_user_ids or [])
                        if str(u).strip().isdigit()}
        self.handle_text = handle_text or (lambda t: "(no handler)")
        self.transcribe_voice = transcribe_voice
        self.poll_timeout = max(10, int(poll_timeout or 50))
        self.on_note = on_note or (lambda m: None)
        self._api = api or self._http_api
        self._stop = threading.Event()
        self._thread = None
        self._guard = threading.Lock()

    # ------------------------------------------------------------------ net
    def _http_api(self, method: str, params: dict):
        r = requests.post(_API.format(token=self.token, method=method),
                          json=params or {},
                          timeout=self.poll_timeout + 15)
        r.raise_for_status()
        return r.json()

    def _download(self, file_path: str) -> bytes:
        r = requests.get(_FILE_API.format(token=self.token, path=file_path),
                         timeout=60)
        r.raise_for_status()
        return r.content

    # -------------------------------------------------------------- control
    def start(self) -> bool:
        """Begin polling in a daemon thread. Idempotent."""
        with self._guard:
            if self._thread and self._thread.is_alive():
                return True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="jarvis-telegram")
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._guard:
            self._stop.set()
            t, self._thread = self._thread, None
        if t and t is not threading.current_thread():
            t.join(timeout=5)

    # ------------------------------------------------------------------ loop
    def _loop(self) -> None:
        offset = 0
        self.on_note("telegram channel polling")
        while not self._stop.is_set():
            try:
                data = self._api("getUpdates", {
                    "offset": offset, "timeout": self.poll_timeout,
                    "allowed_updates": ["message"]})
            except Exception as e:
                self.on_note(f"telegram poll error: {e}")
                self._stop.wait(5)
                continue
            for upd in (data or {}).get("result", []):
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                try:
                    self._handle_update(upd)
                except Exception as e:
                    self.on_note(f"telegram update error: {e}")
            # tight-loop guard when the server answers instantly and empty
            if not (data or {}).get("result"):
                self._stop.wait(0.2)

    # --------------------------------------------------------------- updates
    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        sender = (msg.get("from") or {}).get("id")
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return
        if sender not in self.allowed:
            return  # strangers are silently ignored
        text = (msg.get("text") or "").strip()
        if text:
            if text.lower() == "/start":
                self._send(chat_id, "At your service, sir. Send text or a voice note.")
                return
            reply = self._safe_handle(text)
            self._send(chat_id, reply)
            return
        voice = msg.get("voice") or msg.get("audio")
        if voice and self.transcribe_voice:
            self._send(chat_id, self._handle_voice(voice))
        elif voice:
            self._send(chat_id, "Voice notes aren't wired up on this PC, sir — send text.")
        # stickers/photos/etc: ignored quietly

    def _safe_handle(self, text: str) -> str:
        try:
            return self.handle_text(text) or "(no reply)"
        except Exception as e:
            return f"Forgive me, sir — something went wrong: {e}"

    def _handle_voice(self, voice: dict) -> str:
        try:
            info = self._api("getFile", {"file_id": voice["file_id"]})
            path = ((info or {}).get("result") or {}).get("file_path", "")
            if not path:
                return "I couldn't fetch that voice note, sir."
            audio = self._decode_ogg(self._download(path))
            if audio is None:
                return "I couldn't decode that voice note, sir."
            transcript = (self.transcribe_voice(audio) or "").strip()
            if not transcript:
                return "I didn't catch that, sir — say it once more?"
            return self._safe_handle(transcript)
        except Exception as e:
            return f"Voice note failed, sir: {e}"

    @staticmethod
    def _decode_ogg(data: bytes):
        """OGG/Opus bytes -> float32 mono @16kHz numpy, or None."""
        try:
            import numpy as np
            import soundfile as sf
            audio, sr = sf.read(io.BytesIO(data), dtype="float32",
                                always_2d=True)
            mono = audio.mean(axis=1).astype(np.float32)
            if sr != 16000:
                n = int(len(mono) * 16000 / sr)
                if n < 1:
                    return None
                mono = np.interp(np.linspace(0, len(mono) - 1, n),
                                 np.arange(len(mono)), mono).astype(np.float32)
            return np.clip(mono, -1.0, 1.0)
        except Exception:
            return None

    def _send(self, chat_id, text: str) -> None:
        for part in _chunk(text):
            try:
                self._api("sendMessage", {
                    "chat_id": chat_id, "text": part,
                    "disable_web_page_preview": True})
            except Exception as e:
                self.on_note(f"telegram send error: {e}")
                time.sleep(1)


def resolve_token(cfg: dict | None = None) -> str:
    """Bot token: TELEGRAM_BOT_TOKEN env, then secrets.local.yaml, then config."""
    import os
    val = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if val:
        return val
    try:
        import yaml
        from paths import user_file
        sp = user_file("secrets.local.yaml")
        if os.path.isfile(sp):
            with open(sp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            val = str(data.get("telegram_bot_token") or "").strip()
            if val:
                return val
    except Exception:
        pass
    cfg = cfg or {}
    val = str(cfg.get("telegram_bot_token") or "").strip()
    return val if len(val) > 16 else ""
