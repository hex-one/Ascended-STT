# Building Ascended STT (Qt version) as a standalone Windows .exe

## What's been verified

Built and ran the actual Windows `.exe` for real (not just the Linux
build described further down) and used that to confirm the packaging
actually works, not just that the spec file looks right on paper.
Proof beats promises:

- Full build completes cleanly through PyInstaller's analysis, PYZ,
  PKG, EXE, and COLLECT stages.
- Ran the actual built executable and confirmed every single resource
  loads correctly through it - `index.html`, `style.css`, `app.js`,
  and all six toggle button images - via the same local HTTP server
  approach used running from source.
- No missing native library errors for Azure Speech SDK or Qt/WebEngine
  itself (the two things most likely to break in a from-scratch
  PyInstaller build, based on what actually broke in the earlier
  pywebview build's testing).

**A real bug was caught here, not just a warning:** if `openvr` happens
to be installed in the machine doing the build (it's optional per
`requirements.txt`, but was present on the build machine this time),
PyInstaller bundled its pure-Python wrapper but not the native
`libopenvr_api_64.dll` it loads via `ctypes` at import time — same
class of problem the spec already handles for the Azure Speech SDK, via
`collect_dynamic_libs`. Without that DLL, the packaged exe **crashed on
startup for everyone**, not just people without SteamVR, because
`main.py`'s `try: import openvr / except ImportError` didn't catch it —
PyInstaller's own load-failure exception isn't an `ImportError`. Both
are now fixed: `AscendedSTT.spec` explicitly collects `openvr`'s
dynamic libs (guarded so a build machine *without* openvr installed
still builds fine, just without VR-hotkey support baked in), and
`main.py`'s except clause was broadened to catch this class of failure
generally, as a second independent safety net. Confirmed fixed by
rebuilding and actually launching the packaged exe — window opens
normally instead of showing PyInstaller's "Unhandled exception in
script" crash dialog. Find the real cause, not just the symptom.

From-Linux build testing (earlier pass, before a Windows machine was
available) also showed one warning: `libtiff.so.5` missing — a
Linux-only optional Qt image-format plugin for TIFF files, irrelevant
here since the app only ever uses PNGs and Windows has its own
equivalent bundled correctly by Qt.

---

## How to build it

On a Windows machine, with Python installed:

```
cd files
pip install -r requirements.txt
pip install pyinstaller
pyinstaller AscendedSTT.spec
```

This produces `dist/AscendedSTT/` containing `AscendedSTT.exe` and its
supporting files. **Copy `ui/` and `assets/` into that same folder**
(intentionally not baked into the exe - see the note in
`AscendedSTT.spec`). **Also copy the six `*_SETUP.md` files** - Config's
"View Setup Guide" buttons read these off disk next to the exe at
runtime, so skipping this just means those buttons show a "couldn't
read" error instead of the guide, not a crash. **Also copy
`content_version.txt`** - the in-app content-updater (see main.py's
"CONTENT + APP UPDATE CHECKS" section) reads this to know what it's
currently running; skipping it just means the very next launch treats
everything as out of date and re-fetches once, not a crash either. Also
copy `.env` with your real Azure key/region, or configure it after
first launch via the gear icon.

```
dist/AscendedSTT/
├── AscendedSTT.exe
├── ui/                       (copied in manually)
├── assets/                   (copied in manually)
├── AZURE_SETUP.md            (copied in manually)
├── GOOGLE_SETUP.md           (copied in manually)
├── AWS_SETUP.md              (copied in manually)
├── WHISPER_SETUP.md          (copied in manually)
├── VOSK_SETUP.md             (copied in manually)
├── WINDOWS_SPEECH_SETUP.md   (copied in manually)
├── content_version.txt       (copied in manually)
└── ... (PyInstaller's own supporting files)
```

Zip up that whole folder - that's the distributable app.

No launcher, no supervisor process this time - `main.py` is the direct
entry point. That pattern only existed to work around a pywebview bug
that structurally can't happen with this Qt-based architecture. One
clean path in, same as it should be.

---

## Windows Defender / antivirus flagging - the honest picture

This is a genuinely common issue with PyInstaller-built executables in
general, not something specific to this app having done anything
wrong. I'd rather you hear it straight from me than guess from a scary
popup. Worth understanding *why* before deciding what to do about it.

### Why it happens

1. **Packing/compression patterns.** Tools that compress or bundle an
   executable (like UPX) are used by both legitimate small utilities
   *and* malware trying to evade signature-based detection - heuristic
   engines can't always tell the difference, so they flag both.
2. **No publisher identity.** An unsigned .exe has no verifiable
   "who made this" information. Windows SmartScreen and Defender's
   cloud reputation checks weigh this heavily - a brand-new, unsigned
   file starts with zero trust regardless of what it actually does.
3. **Runtime self-extraction.** A single-file exe that unpacks itself
   into a temp folder and runs from there is a behavioral pattern
   malware droppers also use.
4. **This app specifically uses a global keyboard hook** (for the F9
   hotkey, via `pynput`). That's a completely legitimate use here, but
   "installs a system-wide keyboard listener" is *also* exactly what a
   keylogger does - heuristic engines can't distinguish intent, only
   behavior. This is a real, residual factor that packaging changes
   alone can't fully remove. Same shape, different intent -- the
   machine can't tell the difference, only I can vouch for it.

### What's already applied in `AscendedSTT.spec`

- **`upx=False`** - no compression. Real, free mitigation; the
  trade-off is a larger file on disk.
- **`onedir` build** (via `COLLECT`, not a single-file `onefile`
  build) - a folder with the exe and its files sitting next to it,
  rather than a self-extracting single exe. Avoids the "unpacks itself
  to a temp folder" heuristic trigger entirely.

### What would help further, with real trade-offs

- **Code signing** - the actual, most effective fix. Get a
  code-signing certificate from a Certificate Authority (DigiCert,
  Sectigo, SSL.com, etc.), sign the exe with it. This gives Windows a
  verifiable publisher identity. Costs real money (roughly $70-400+/year
  depending on certificate type) and requires identity verification
  with the CA - not something I can set up for you, but the single
  biggest lever if this is going to be distributed widely.
  **Caveat:** even a signed exe starts with limited reputation on a
  *brand new* certificate - trust builds up over time and downloads,
  same as anywhere else, not instant.
- **Submit to Microsoft for false-positive review** - free, via
  https://www.microsoft.com/en-us/wdsi/filesubmission. If Defender
  flags a build you believe is a false positive, you can submit it and
  Microsoft can adjust detection for that specific file. Reactive, not
  preventative - a new build (new file hash) may need resubmitting.
- **Check VirusTotal before distributing** - upload the built exe to
  https://www.virustotal.com to see exactly which of the ~70 engines
  it scans against flag it, and often why. Turns "Defender doesn't
  like it" into concrete data instead of a guess.

### The honest bottom line

There's no way to *guarantee* zero false positives on a freshly built,
unsigned executable - that's true of any PyInstaller app, not a flaw
specific to this one. The mitigations already in the spec (no UPX,
onedir) are real and free. Code signing is the actual fix if this
needs to go out to people who aren't already expecting a "just trust
me" security prompt, but it's a cost/effort decision only you can make.
I'll tell you what's true and let you decide -- that's the deal.

**See `DEFENDER_SUBMISSION.md`** for the actual step-by-step submission
checklist - it's a per-release thing (new build = new file hash = a
fresh review), not a one-time setup, so it's worth having as a runbook
rather than re-deriving each time.
