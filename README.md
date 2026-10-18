# JARVIS — as close to the movies as a Windows PC gets

Voice-first, British-butler AI that lives on your desktop: a holographic HUD
overlay, a "Hey Jarvis" wake word, full PC control, proactive briefings,
webcam presence greetings — and a brain that **never** answers "I don't know".

## Quick start

```powershell
# run these from the repo root (where you cloned it)
python setup_models.py        # one-shot: deps + models + desktop icon
python jarvis_app.py          # the full experience (HUD + voice + camera)
```

Or just double-click the **JARVIS** icon on your Desktop (created
automatically — arc-reactor icon, launches with `pythonw`, no console window).

Say **"Hey Jarvis"**, wait for the chime, and talk. Or press **Ctrl+Alt+Space**
(push-to-talk) if the room is noisy.

## Two brains, one JARVIS

JARVIS runs a **local Ollama core** and can pair it with an **online brain
(Gemini)** — both brains share the SAME toolset (PC control, research, files,
code), and each can delegate to the other mid-task:

- The driving brain can call **consult_online_brain** / **consult_local_brain**
  to hand off a sub-task (a second opinion, hard reasoning, parallel work) —
  the consulted brain runs its own tool loop and reports back.
- Guard rails: consultations never nest (no brain can consult from inside a
  consultation) and each turn has a consultation budget (`brain.cloud.consult_*`
  in `config.yaml`).
- `brain.mode: local_first` — local drives, consults Gemini for hard parts.
  `brain.mode: cloud_first` — Gemini drives, consults the local core.
- Either brain failing or hedging automatically hands the turn to the other.

### Add your Gemini key (one command)

```powershell
python set_cloud_key.py YOUR_GEMINI_API_KEY   # stores + tests the key
python set_cloud_key.py --test                # re-test anytime
```

Free key: https://aistudio.google.com/apikey (default model `gemini-3.8-flash`,
free tier, function calling). The key goes into `secrets.local.yaml` — never
committed, never printed, deleted by removing that file. The `GEMINI_API_KEY`
environment variable works too. Without a key everything still runs local.

## Modes

| Command | What it does |
|---|---|
| `python jarvis_app.py` | Full app: HUD + voice + webcam + brain |
| `python jarvis_app.py --text` | Console brain only (no audio/HUD/camera) |
| `python jarvis_app.py --no-camera` | Skip presence detection |
| `python jarvis_app.py --no-hud` | Voice only, no overlay |
| `python jarvis_app.py --mute` | Listens & thinks, prints replies |
| `python jarvis_app.py --no-wake` | Push-to-talk only |
| `python jarvis_app.py --test-audio file.wav` | One supervised end-to-end turn from a file |
| `python main.py` | Legacy terminal chat (same brain, plus auto web-research) |

## Hotkeys

- **Ctrl+Alt+J** — show/hide the HUD
- **Ctrl+Alt+I** — toggle mouse pass-through (turn off so you can drag the HUD)
- **Ctrl+Alt+Space** — start/stop a dictated turn
- **Ctrl+Alt+S** — settings panel (or the ⚙ button on the HUD)
- **Ctrl+Alt+Q** — quit JARVIS (also: `python jarvis_app.py --text` then `quit`)
- Say **"Jarvis"** while he's speaking to interrupt (barge-in)

## What he can do

- **Voice**: offline wake word (`hey_jarvis`), offline STT (faster-whisper),
  offline British TTS (Piper `en_GB-northern_english_male`) — no cloud needed.
  Optional neural voices: set `voice.tts_backend: "fish"` (Fish Audio) or
  `"elevenlabs"` in `config.yaml` plus the API key — JARVIS falls back to
  Piper automatically if the key or network fails.
- **PC control**: open/close apps, volume, brightness, URLs, files, screenshots,
  clipboard, typing, hotkeys, lock/shutdown (with spoken confirmation)
- **Research**: web search, page reading, code execution, memory recall —
  the brain loops over tools instead of ever saying "I don't know"
- **Diagnostics**: "Jarvis, run diagnostics" — CPU/RAM/disk/battery/GPU report
  plus live HUD gauges
- **Proactive**: time-of-day greeting when you sit down, morning/evening
  briefings (weather + headlines + system), spoken reminders
- **Presence**: webcam greets you when you arrive and when you return
- **Phone link**: Telegram bot — text him or send a voice note from your
  phone; his brain answers. `@BotFather` → token in Settings > API Keys,
  your user ID in `telegram.allowed_user_ids`, `telegram.enabled: true`.
- **Watching eyes** (opt-in): he glances at your screen and speaks up when
  you look stuck — "I see you're fighting that error, sir." Captures stay
  in RAM, never touch disk. Needs the cloud brain.
  `screen_watcher.enabled: true`.

## Configuration — `config.yaml`

Everything lives there: model name, voice, wake threshold, briefing times,
HUD position/size, presence settings, safety flags.

Prefer clicking to typing? Press **Ctrl+Alt+S** (or the ⚙ on the HUD) for the
settings panel — API keys, voice engine, brain, HUD, routines and safety, all
in one place. Keys land in `secrets.local.yaml` (never committed); the rest
becomes overrides in `settings.local.yaml`, merged over `config.yaml`.

### Other online providers

Any OpenAI-compatible endpoint works — set `brain.cloud.provider: "openai"` in
`config.yaml` plus environment variables:

```powershell
$env:JARVIS_CLOUD_BASE_URL = "https://api.groq.com/openai/v1"   # or openrouter/openai
$env:JARVIS_CLOUD_API_KEY  = "gsk_..."
$env:JARVIS_CLOUD_MODEL    = "llama-3.3-70b-versatile"
```

Without a key, everything still works locally — research tools cover the gap.

## Layout

```
.  (repo root — run the app from here)
  jarvis_app.py     entry point + voice state machine
  brain.py          hybrid tool-loop orchestrator (shared by all modes)
  persona.py        the JARVIS system prompt (butler voice + never-say-idk)
  config.yaml       all settings
  tts.py stt.py     Piper speech out / faster-whisper speech in
  audio.py wake.py  mic engine, VAD capture, chimes, "hey jarvis" listener
  overlay.py        HUD window: click-through, hotkeys, drag
  hud_widgets.py    arc reactor, waveform, gauges, transcript
  system_actions.py Windows control tools (+ destructive-action confirmation)
  diagnostics.py    psutil/nvidia-smi health reports
  presence.py       webcam face detection greetings
  scheduler.py      reminders + weather/news/system briefings
  actions.py        research/file/code tools + tool registry
  skills/           drop-in skill packs (new powers, no core edits) — see skills/README.md
  memory.py         JSON/Markdown memory bank
  shortcut.py       desktop icon (.ico) + JARVIS.lnk launcher
  set_cloud_key.py  store/test the Gemini key for the online brain
  main.py           legacy terminal mode
  setup_models.py   one-shot installer
  test_dual_brain.py  dual-brain verification (see below)
```

### Verify the dual brain

```powershell
python set_cloud_key.py --test   # Gemini ping + function-calling round trip
python test_dual_brain.py        # consult guards + cross-brain delegation
```

## Distribute as one double-click `.exe` (no Python needed on the target PC)

If you want to hand a single `JARVIS.exe` to a friend or a non-technical
machine (or to a PC that has no Python installed), build it once with
PyInstaller. The build wizard is in this repo:

```
AI_Model/
  build_wizard/        the one-click build kit
    build_jarvis_exe.bat   double-click this on Windows to build JARVIS.exe
    build_jarvis_exe.ps1   same build, PowerShell
    (no other files belong here)
  freeze_jarvis.py     PyInstaller entry point the frozen exe runs
  Jarvis.spec          PyInstaller spec (the real source of truth for the build)
```

### Build on ANY Windows PC (even one with no Python installed)

1. Install Python 3.10-3.12 (64-bit) from https://python.org, ticking
   **"Add python.exe to PATH"** during install. A normal user install is fine;
   admin is not required.
2. Open `AI_Model/build_wizard/` in Explorer and **double-click
   `build_jarvis_exe.bat`**. (Or, from PowerShell:
   ```
   cd AI_Model\build_wizard\
   .\build_jarvis_exe.ps1
   ```)
3. A fresh isolated build venv is created under
   `build_wizard/build_env`, pip deps are installed from `requirements.txt`,
   PyInstaller runs via the spec, and the result appears in `dist/JARVIS/`.

That's it. No Git, no manual pip steps, no editing anything. The first build
downloads PyInstaller + the runtime Python wheels into the build env; that can
take a few minutes on first run. Subsequent builds reuse the build env and are
faster.

### What you get

- **`dist/JARVIS/`** — an *onedir* package: a folder containing `JARVIS.exe`
  plus all the bundled DLLs/Python bits side by side. Copy this whole folder
  to the target machine and run `JARVIS.exe`.
- The target machine needs **no Python, no pip, no Git, no venv** — the `.exe`
  is self-contained except for the runtime downloads below.

### Want a single `.exe` instead of a folder?

Edit `build_jarvis_exe.bat` (or the `.ps1`) and change the build command's
`--onedir` flag to `--onefile`, then rerun. That produces a single
`dist/JARVIS.exe`.

Tradeoffs (both are real, pick what matters more to you):

- **--onedir** (current default): faster startup, smaller repeated extraction
  overhead, far fewer AV false positives, easier to debug if something goes
  wrong. Slight downside: you distribute a folder, not one file.
- **--onefile** (single exe): one file to copy, but the exe unpacks itself to
  a temp dir every launch, so first-start is slower (seconds, not instant),
  large bundles take noticeable time, big one-file exes commonly trip AV
  heuristics unless code-signed, and killing the exe can leave temp dirs
  behind. With this project's torch + transformers + numpy + opencv + PyQt6
  payload, one-file startup is measurably heavier than onedir.

For a personal assistant you run on your own RTX 2060 / Ryzen 5 3600 / 16GB,
either is fine. For handing it to a friend, the onedir folder is usually the
smoother experience; switch to one-file only if "one file" is the priority.

### First-run model downloads

The frozen `JARVIS.exe` does **not** bundle the big offline voice/model weights
— that would push the exe toward multi-gigabyte and slow startup a lot. On the
**first launch** on the target PC, the frozen launcher downloads the offline
assets into `%APPDATA%\JARVIS\models`:

- Piper British voice
  `en_GB-northern_english_male-medium` (`.onnx` + `.onnx.json`)
- faster-whisper `base.en`
- openWakeWord `hey_jarvis` models

So the target PC needs network access on first launch. After that, the models
stay on disk and runs are purely offline (except whatever online brain you
configured). If the target is air-gapped, download those assets on another
machine and copy them into `%APPDATA%\JARVIS\models` before first launch.

### Runtime requirements on the target machine

- Windows (the overlay, hotkeys, COM desktop-icon creation, and PyAutoGUI
  window control are Windows-only).
- A GPU is used where available (PyTorch will use CUDA on your RTX 2060);
  the app still works on CPU, just slower for the local model and for
  faster-whisper/infer.
- Microphone + speaker access (Windows privacy settings → allow the app to use
  the mic).
- If you use the online brain, the target needs outbound HTTPS to the Gemini/
  OpenAI-compatible endpoint, plus the key stored via the in-app key flow or
  by dropping `secrets.local.yaml` into the same folder as `JARVIS.exe` (the
  frozen app reads `secrets.local.yaml` next to itself if present).

### Building again after you change source

Any edit to the Python source (`jarvis_app.py`, `brain.py`, etc.) or to
`config.yaml` / `persona.py` meant to ship inside the exe should be rebuilt:

```
cd AI_Model\build_wizard\
.\build_jarvis_exe.bat
```

To keep the git history clean, the build wizard and the built `dist/` are not
committed — only `build_wizard/*.bat`, `build_wizard/*.ps1`, `Jarvis.spec`,
and `freeze_jarvis.py` are part of the repo.

### Troubleshooting the build

- **"Microsoft Visual C++ 14.0 or greater is required"** during the build:
  install the matching [Visual Studio Build Tools
  (C++ build tools workload)](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
  on the build machine. This is a build-time need, not a runtime need.
- **torch / pytorch import errors in the build**: the build env is a fresh pip
  install from `requirements.txt`; if a wheel is missing for your exact Python/
  platform, install the correct one from https://pytorch.org first, or build
  with `--onedir` and inspect `build/` / the warnings PyInstaller prints.
- **"WARNING: lib not collected"** or "cannot find path" in the PyInstaller
  log: usually harmless for pure-python extras, but if a native lib is missing
  the frozen exe will crash at runtime for that feature. Recheck `hidden_imports`
  in `Jarvis.spec` and the collect calls; `--onedir` makes `dist/JARVIS/` easy to
  inspect.
- The spec intentionally does **not** bundle model weights; if you want a truly
  offline single exe for air-gapped use, download the Piper/whisper/openWakeWord
  assets separately and ship them alongside the exe in `%APPDATA%\JARVIS\models`.

## Troubleshooting

- **No sound / no mic**: check Windows privacy settings (Settings → Privacy →
  Microphone) and `python -c "import sounddevice; print(sounddevice.query_devices())"`.
- **Wake word won't fire**: raise mic volume or lower `voice.wake_threshold`
  in `config.yaml` (try 0.35); say it clearly once from your usual seat.
- **HUD invisible**: Ctrl+Alt+J; check `hud.corner` and that another
  fullscreen exclusive-mode app isn't covering it.
- **Slow replies**: the local 9B model needs your RTX 2060 — close other GPU
  apps, or set a smaller model in `config.yaml`.
- **"core offline"**: run `ollama serve` (or restart Ollama).
- **Online brain offline**: run `python set_cloud_key.py --test`. A 401/403
  means the key is wrong or revoked — store a fresh one. Delete
  `secrets.local.yaml` to remove the stored key entirely.
- **Desktop icon missing**: run `python setup_models.py` again (it recreates
  the shortcut), or `python shortcut.py`. If Windows blocks the shortcut,
  right-click → Unblock.
