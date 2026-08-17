# Ascended STT (Qt version) — Setup Guide

This is a rebuild of the app on a fundamentally different foundation
than the earlier pywebview-based version. The short version: pywebview's
Windows backend routed everything through `pythonnet`'s .NET interop
layer to reach WebView2, and that layer had a real, unresolved upstream
bug that caused the intermittent startup freezes chased at length
before. Qt's WebEngine talks to its own embedded Chromium directly
through Qt's own bindings — no .NET interop at all, so that specific
bug class cannot happen here. That's the actual point of this version:
a more stable foundation, not new features. Sometimes you don't patch
the crack, you build on ground that doesn't crack.

Practical effect: **no separate launcher/supervisor process anymore.**
Just run the app directly.

---

## 1. Install Python

Python 3.9 or newer, from https://python.org/downloads (check "Add
Python to PATH" during install on Windows).

## 2. Install the required packages

```
pip install -r requirements.txt
```

This installs PySide6, which bundles its own Chromium — unlike the old
version, **there's no separate WebView2 Runtime to install.** Qt brings
its own browser engine with it.

## 3. Set up your `.env` file

Copy `.env.example` to `.env` and fill in your real Azure values:

```
AZURE_SPEECH_KEY=your_actual_key_here
AZURE_SPEECH_REGION=eastus
```

Don't have those yet? **See [`AZURE_SETUP.md`](AZURE_SETUP.md)** for
the full walkthrough — creating a free Azure account and a Speech
resource on the permanent free tier (5 hours/month, genuinely free
forever, no card charged) takes about fifteen minutes.

(You can also set/update these later from inside the app via the gear
icon → Config.)

## 4. Run it

```
python main.py
```

That's it — no launcher, no supervisor, no startup checklist working
around a known freeze. Just the app. Present, not propped up.

---

## What's different from the pywebview version

- **No `launcher.py`.** It existed specifically to detect and recover
  from the pywebview startup freeze. That bug can't happen with this
  architecture, so the whole supervisor pattern is gone.
- **No WebView2 Runtime requirement.** Qt bundles its own Chromium.
- **Same UI, same features.** The HTML/CSS/JS in `ui/` is almost
  entirely unchanged - transparency, the startup checklist, Config,
  About, personas, everything. What changed is the Python-side shell:
  window creation, and the JS↔Python bridge (now Qt's `QWebChannel`
  instead of pywebview's `js_api`).
- **Still has the startup checklist** (Loading interface → Connecting
  to app → ... → Ready) - it's good UX for showing real backend
  progress (finding the mic, connecting to Azure) regardless of
  whether the underlying bridge is fragile, so it stayed. Show the
  work, don't just ask for trust.

## Troubleshooting

- **"Missing required package(s)"** — run the `pip install` command it
  prints.
- **No sound recognized** — check the Input Device dropdown in Config.
- **Azure errors in the log** — usually a wrong key/region or no
  internet; check/update via the gear icon (Save now actually tests
  the connection before saving).
- **Nothing shows up in VRChat** — make sure OSC is enabled in VRChat
  (Action Menu → Options → OSC → Enabled), and the port in Config
  matches what VRChat is using (default 9000).
