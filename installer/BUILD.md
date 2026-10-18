# JARVIS installer — how to build it

`installer/JARVIS.iss` is an **Inno Setup 6** script. Compile it once and you
get `JARVIS_Setup.exe` — a normal Windows installer:

- installs to `%LocalAppData%\JARVIS` — **no admin / no UAC prompt**
- desktop icon (ticked by default) + Start Menu entry, with the arc-reactor icon
- **downloads all voices & AI models during installation**
  (`JARVIS.exe --prewarm`: whisper STT, Piper voice, wake-word models)
- "Launch JARVIS" checkbox on the finish page — double-click the icon later
  and he's running
- full uninstaller in Add/Remove Programs; your settings & API keys
  (`%APPDATA%\JARVIS`) are kept on uninstall

## Build (on your PC, one time)

1. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free).
2. Run `installer\build_installer.bat` — it freezes the app
   (`AI_Model\build_wizard\build_jarvis_exe.bat` → `dist\JARVIS\`) and then
   compiles the installer.
3. `JARVIS_Setup.exe` appears in the repo root. Run it.

## Notes

- First launch still needs your Gemini key for the cloud brain
  (Settings → API Keys, or say "set my cloud key").
- `JARVIS.exe --prewarm` can also be run manually any time to re-download assets.
- Installed-app paths: anything the app *writes* (settings, secrets, voices,
  workspace) lives in `%APPDATA%\JARVIS`, never in the install folder —
  see `paths.py`. Dev (`python jarvis_app.py`) behavior is unchanged.
