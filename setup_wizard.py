"""JARVIS graphical installer — no terminal, no typing.

Double-click Install_JARVIS.bat (it runs this file). Everything is buttons:
checks → Install → Gemini key (optional) → Launch.

Uses only tkinter (ships with Python), so it runs before any JARVIS
dependency is installed. The heavy work runs in a background thread and
streams into the log box.
"""

import contextlib
import io
import queue
import sys
import threading
import traceback


def _run_install(log_q: queue.Queue, done_q: queue.Queue) -> None:
    """Background thread: the whole setup_models.py pipeline."""
    class _GuiLog(io.TextIOBase):
        def write(self, s):
            if s.strip():
                log_q.put(s.rstrip())
            return len(s)

    try:
        import setup_models
        with contextlib.redirect_stdout(_GuiLog()):
            setup_models.main()
        done_q.put((True, "Installed, sir. Add your Gemini key below (or later in Settings), then launch."))
    except SystemExit as e:
        done_q.put((False, f"Stopped: {e}"))
    except Exception:
        done_q.put((False, "Something broke:\n" + traceback.format_exc(limit=3)))


def main() -> int:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("JARVIS Setup")
    root.geometry("560x520")
    root.resizable(False, False)

    log_q: queue.Queue = queue.Queue()
    done_q: queue.Queue = queue.Queue()
    worker: list = []

    # ------------------------------------------------------------- header
    ttk.Label(root, text="JARVIS Setup",
              font=("Segoe UI", 18, "bold")).pack(pady=(14, 2))
    ttk.Label(root, text="Your personal AI — one click, no terminal.",
              foreground="#5b7183").pack(pady=(0, 10))

    # ------------------------------------------------------------- checks
    checks = ttk.Frame(root)
    checks.pack(fill="x", padx=20)
    py_ok = sys.version_info >= (3, 10)
    try:
        import ensurepip  # noqa: F401
        pip_ok = True
    except ImportError:
        pip_ok = False
    for label, ok in (("Python 3.10+  (" + ".".join(map(str, sys.version_info[:3])) + ")", py_ok),
                      ("pip available", pip_ok)):
        ttk.Label(checks, text=("✓ " if ok else "✗ ") + label,
                  foreground="#2e7d32" if ok else "#c62828").pack(anchor="w")

    # ---------------------------------------------------------------- log
    ttk.Label(root, text="Progress:").pack(anchor="w", padx=20, pady=(10, 0))
    log_box = scrolledtext.ScrolledText(root, height=12, state="disabled",
                                        font=("Consolas", 9))
    log_box.pack(fill="x", padx=20, pady=4)

    progress = ttk.Progressbar(root, mode="indeterminate")
    progress.pack(fill="x", padx=20, pady=4)

    # ---------------------------------------------------------- gemini key
    key_frame = ttk.Frame(root)
    key_frame.pack(fill="x", padx=20, pady=6)
    ttk.Label(key_frame, text="Gemini API key (optional now):").pack(anchor="w")
    key_var = tk.StringVar()
    key_entry = ttk.Entry(key_frame, textvariable=key_var, show="•", width=60)
    key_entry.pack(fill="x", pady=2)
    ttk.Label(key_frame, text="Free key: aistudio.google.com/apikey — or add it later in Settings → API Keys.",
              foreground="#5b7183", font=("Segoe UI", 8)).pack(anchor="w")

    # -------------------------------------------------------------- buttons
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=10)

    def pump():
        while True:
            try:
                line = log_q.get_nowait()
            except queue.Empty:
                break
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        try:
            ok, msg = done_q.get_nowait()
        except queue.Empty:
            root.after(150, pump)
            return
        progress.stop()
        install_btn.configure(state="disabled")
        launch_btn.configure(state="normal")
        log_box.configure(state="normal")
        log_box.insert("end", "\n" + msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        if not ok:
            messagebox.showerror("JARVIS Setup", msg)

    def on_install():
        if not (py_ok and pip_ok):
            messagebox.showerror("JARVIS Setup",
                                 "Python 3.10+ with pip is needed first.\n"
                                 "Install it from python.org (tick \"Add python.exe to PATH\").")
            return
        install_btn.configure(state="disabled")
        progress.start(12)
        t = threading.Thread(target=_run_install, args=(log_q, done_q),
                             daemon=True)
        worker.append(t)
        t.start()
        root.after(150, pump)

    def on_key_save():
        key = key_var.get().strip()
        if not key:
            return
        try:
            from set_cloud_key import store_key
            store_key(key)
            key_var.set("")
            messagebox.showinfo("JARVIS Setup", "Gemini key saved, sir.")
        except Exception as e:
            messagebox.showerror("JARVIS Setup", f"Couldn't save the key: {e}")

    def on_launch():
        import os
        import subprocess
        app = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "jarvis_app.py")
        try:
            subprocess.Popen([sys.executable, app],
                             cwd=os.path.dirname(app))
            root.destroy()
        except Exception as e:
            messagebox.showerror("JARVIS Setup", f"Couldn't launch: {e}")

    install_btn = ttk.Button(btn_frame, text="Install JARVIS", command=on_install)
    install_btn.pack(side="left", padx=6, ipadx=10, ipady=4)
    ttk.Button(btn_frame, text="Save key", command=on_key_save).pack(side="left", padx=6)
    launch_btn = ttk.Button(btn_frame, text="Launch JARVIS", command=on_launch,
                            state="disabled")
    launch_btn.pack(side="left", padx=6, ipadx=10, ipady=4)

    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("JARVIS Setup",
                                 "Couldn't start the installer:\n" +
                                 traceback.format_exc(limit=5))
        except Exception:
            pass
        raise
