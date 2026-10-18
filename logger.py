"""JARVIS structured logging.

One `get_logger(__name__)` per module. Writes a rotating jarvis.log next
to the other user data (so there's always a trail when something goes
wrong), with a JARVIS_LOG_LEVEL env knob. Noisy third-party loggers are
quieted. Never raises — logging must not break the app.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_NAME = "jarvis.log"


def _data_dir() -> str:
    try:
        from paths import data_dir
        d = data_dir()
    except Exception:
        d = os.path.dirname(os.path.abspath(__file__))
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(f"jarvis.{name}")
    if log.handlers:
        return log
    try:
        level = os.environ.get("JARVIS_LOG_LEVEL", "INFO").upper()
        log.setLevel(getattr(logging, level, logging.INFO))
    except Exception:
        log.setLevel(logging.INFO)
    try:
        fh = RotatingFileHandler(
            os.path.join(_data_dir(), _LOG_NAME),
            maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"))
        log.addHandler(fh)
    except Exception:
        pass
    for noisy in ("urllib3", "requests", "ollama", "openwakeword"):
        try:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        except Exception:
            pass
    return log
