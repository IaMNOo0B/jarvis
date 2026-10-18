# JARVIS — as close to the movies as a Windows PC gets

Voice-first, British-butler AI that lives on your desktop: a holographic HUD
overlay, a "Hey Jarvis" wake word, full PC control, proactive briefings,
webcam presence greetings — and a brain that **never** answers "I don't know".

## Quick start

```powershell
cd AI_Model
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
| `python jarvis_app.py --mute` | Listens & thinks, prints instead of speaking |
| `python jarvis_app.py --no-wake` | Push-to-talk only |
| `python jarvis_app.py --test-audio file.wav` | One supervised end-to-end turn from a file |
| `python main.py` | Legacy terminal chat (same brain, plus auto web-research) |

## Hotkeys

- **Ctrl+Alt+J** — show/hide the HUD
- **Ctrl+Alt+I** — toggle mouse pass-through (turn off so you can drag the HUD)
- **Ctrl+Alt+Space** — start/stop a dictated turn
- **Ctrl+Alt+Q** — quit JARVIS (also: `python jarvis_app.py --text` then `quit`)
- Say **"Jarvis"** while he's speaking to interrupt (barge-in)

## What he can do

- **Voice**: offline wake word (`hey_jarvis`), offline STT (faster-whisper),
  offline British TTS (Piper `en_GB-northern_english_male`) — no cloud needed
- **PC control**: open/close apps, volume, brightness, URLs, files, screenshots,
  clipboard, typing, hotkeys, lock/shutdown (with spoken confirmation)
- **Research**: web search, page reading, code execution, memory recall —
  the brain loops over tools instead of ever saying "I don't know"
- **Diagnostics**: "Jarvis, run diagnostics" — CPU/RAM/disk/battery/GPU report
  plus live HUD gauges
- **Proactive**: time-of-day greeting when you sit down, morning/evening
  briefings (weather + headlines + system), spoken reminders
- **Presence**: webcam greets you when you arrive and when you return

## Configuration — `config.yaml`

Everything lives there: model name, voice, wake threshold, briefing times,
HUD position/size, presence settings, safety flags.

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
AI_Model/
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
