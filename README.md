# Ascended STT

Hey. Jasper Hex here.

Speak, and it lands in your VRChat chatbox — no typing, no breaking
flow, no losing the moment to a keyboard. Pick whichever speech engine
actually fits you — Azure, Google Cloud, or AWS in the cloud, or
Whisper, Vosk, and Windows' own built-in recognizer running fully
offline — and Ascended STT sends what you say over OSC straight into
the game, with optional live translation (where the engine supports
it), a profanity filter, UWU mode, and 26 joke "persona" filters if you
want your words mangled into a pirate, a drill sergeant, a sleepy
ghost, or 23 other things before they go out. Not everything has to be
serious. Some of this exists purely because it made us laugh while
building it.

Built on **PySide6 + QWebEngineView** — a real Qt window with a
Chromium tab inside it, talking to a Python backend over Qt's
`QWebChannel` bridge. The HTML/CSS/JS in `ui/` is the actual interface;
`main.py` is the audio/OSC engine underneath it, the quiet machinery
that makes the front of house work, and `speech_engines.py` is where
the six speech services actually live.

## What's in this app

- **`speech_engines.py`** — six ways to turn a voice into text, behind
  one shape. `Bridge` never talks to Azure, Google, AWS, Whisper, Vosk,
  or Windows directly — it talks to whichever `SpeechEngine` is
  currently selected, and every engine answers the same questions the
  same way: can you translate, do you have real regional dialects or
  just bare languages, does Keep Alive mean anything for you.
  Switching engines is picking a different subclass, not rewriting the
  pipeline underneath it. Worth knowing going in, since these six
  aren't actually equivalent under the hood:
  - **Azure, Google Cloud, and AWS Transcribe** are real cloud
    streaming services — a live connection that can go idle and needs
    Keep Alive's proactive refresh. Azure is verified against a real
    account; Google and AWS are built correctly against their
    documented SDK shapes but haven't been tested against real
    credentials by whoever built this — an untested edge, not a guess
    at the wrong API. Neither does inline translation the way Azure
    does; that's a genuinely separate product on both platforms.
  - **Whisper** isn't a streaming API — it transcribes a buffered
    chunk of audio in one shot, using a simple RMS-energy silence
    check to decide when an utterance is probably over. Real, working
    design, genuinely different latency feel than "the recognizer
    tells you the instant it's sure." Can translate speech, but only
    into English.
  - **Vosk** is a real streaming recognizer, same incremental shape as
    the cloud engines, entirely local. No translation, and language is
    fixed by whichever model folder you point it at — a Vosk model
    IS a specific language, not a runtime dropdown choice.
  - **Windows Speech Recognition (SAPI)** is the odd one out on
    purpose: it manages its own microphone input through Windows' own
    audio stack rather than accepting audio this app captured, because
    that's the correct way to use SAPI, not a shortcut. Language
    follows whatever's set system-wide (Settings → Time & Language →
    Speech), not an in-app choice.

  All six return raw, unfiltered text — Azure's `ProfanityOption.Raw`,
  Google's `profanity_filter=False`, the rest simply have no
  service-side filter to fight in the first place — so the app's own
  profanity toggle stays the one place that decision actually gets
  made, same as it always was.
- **`main.py`** — the whole backend, in one file:
  - **Dependency + required-file checks run first**, before any
    third-party import — a missing package or a `ui`/`assets` folder
    that isn't sitting right next to `main.py` prints exactly what's
    wrong (and the install command to fix it) instead of a raw
    traceback or a blank window. Know the problem before you fight it.
  - **`Bridge`** (`QObject`) owns all live state — mic, Azure
    recognizer, OSC client, prefs — and is exposed to the JS side as
    `bridge` via `QWebChannel`. Every button in the UI calls a
    `@Slot`-decorated method on it directly; state changes get pushed
    back to the UI through one signal (`pushSignal`) rather than
    hand-built `evaluate_js` strings.
  - **The mic → speech engine → VRChat pipeline** (`_build_pipeline`):
    opens the selected input device, resamples whatever rate/channel
    count it natively gives to 16kHz mono, and hands it to whichever
    `SpeechEngine` is currently selected via `feed_audio` — `Bridge`
    itself never branches on which of the six is actually running.
    Windows Speech Recognition is the one exception: it manages its
    own microphone input, so the pipeline skips mic capture entirely
    for that engine rather than feeding it audio it never asked for.
    Azure still supports **147 input locales across 78 language
    groups** and **11 output translation languages**, plus an optional
    custom Azure Speech endpoint ID for anyone running their own
    trained model — the other five engines each expose their own
    (honestly scoped, see `speech_engines.py`) language lists through
    the same interface. Speak in whatever tongue is yours; the
    pipeline should meet you there.
  - **Keep Alive** (`_keep_alive_tick`) is the actual fix for a real
    bug: a cloud recognizer session can go dead after sitting idle —
    often a NAT/firewall idle timeout — *without* ever firing a
    disconnect event, so nothing would tell the old version to
    reconnect. This proactively refreshes the connection during idle
    periods, before that gap has a chance to open, and doubles as the
    TX/RX activity-light heartbeat. Only runs for engines where it
    actually means something (`supports_keep_alive`) — Azure, Google,
    and AWS; a loaded local model has no connection to go stale, so
    Whisper/Vosk/Windows skip this branch entirely rather than faking
    a meaningless reconnect. Presence maintained on purpose, not just
    hoped for.
  - **Hotkey support**, keyboard or VR controller, each in Toggle or
    Push-to-Talk mode. Keyboard uses `pynput` for a single key
    (letter/number or named key like `f9`/`space`). VR uses OpenVR —
    **fully optional**; the app runs fine without it installed, and the
    VR option in Config is just unavailable if it's missing or SteamVR
    isn't running. Capturing a VR combo (`start_vr_capture`) works by
    holding buttons down and watching what's held together, then
    finalizing the combo once everything's released.
  - **Text pipeline before sending to VRChat** (`_process_and_send`):
    profanity filter (word-boundary regex over a 12-word list, masks
    interior letters rather than blanking the whole word) → persona
    filter, if enabled → UWU-ify, if enabled → sent to
    `/chatbox/input` over OSC (default port 9000, configurable).
  - **26 personas** (`PERSONA_STYLES`) — Robot, Cat, Dog, Pirate, Lisp,
    Shakespeare, Valley Girl, Surfer, Drill Sergeant, Radio Announcer,
    Cowboy, Wizard, Sleepy, Conspiracy Theorist, Anime Protagonist,
    Ghost, Vampire, Noir Detective, Fairy, Grumpy Old Man, Auctioneer,
    Newscaster, Villain, Motivational Speaker, Zombie, Alien — each a
    small, self-contained text transform (word swaps, capitalization,
    a chance-based tag line appended after). Twenty-six different
    masks, one voice underneath all of them.
  - **Tiny Mode** shrinks the main window down to just the status
    light/last-heard-text/talk button/toggle — everything else hides
    client-side, the window itself just gets shorter
    (`enter_tiny_mode`/`enter_full_mode`). Sometimes you just need the
    essentials on screen and nothing else competing for space.
  - **A local HTTP server** (`start_local_server`) serves the app's own
    `ui/`/`assets/` folders on `127.0.0.1` at a random free port, so
    relative asset paths and background-image URLs behave exactly like
    a real website would — `QWebEngineView` loads `index.html` from
    that server rather than a raw `file://` path.
  - **Config and About are separate windows sharing the same `Bridge`
    object** as the main window (`make_secondary_window`), not a copy —
    so a change made in Config is immediately live in the running app,
    no separate "apply" round-trip. Both keep an explicit Python
    reference to their view/channel for as long as they're open, since
    without one, nothing else holds a reference and every button
    silently stops calling into Python once the garbage collector gets
    to it. Some things need a real anchor to keep existing.
  - **Closing the window (titlebar X) and the footer's power icon run
    the exact same shutdown path** (`MainWindow.closeEvent` →
    `bridge.shutdown()`) — mic, speech engine connection, and the
    hotkey hook all get released properly either way. Leave the room
    the same way,
    however you choose to leave it.
- **`ui/index.html` + `ui/app.js`** — the main window: a startup
  checklist (loading interface → connecting to app → settings → mic →
  connecting to speech service → mic open → ready) that reflects real
  backend progress rather than a fake spinner, the status light +
  last-heard-text, language pickers (rebuilt live if you switch speech
  service from Config mid-session, via a `speech_service_changed`
  push event — no restart needed), the big Start/Stop button,
  UWU/Persona/Profanity toggles, Keep Alive toggle with TX/RX/heartbeat
  status LEDs, and the footer (power/gear/copyright/heart — Guardian's
  footer is actually modeled on this one, same fingerprint across both
  apps). A shutdown confirmation modal replaces the native browser
  `confirm()`, which showed raw IP:port chrome in the titlebar.
- **`ui/config.html` + `ui/config.js`** — a **Speech Service dropdown**
  at the top, right where Azure's fields used to live alone, switching
  between six per-engine field groups (API keys, service-account/model
  files or folders via native file/folder pickers, model size/device
  for Whisper, or just a Test button for Windows, which has nothing to
  configure). Every Save button runs the same pattern Azure's always
  used — test the connection for real, then save, with the result
  shown right there — for whichever engine you just filled in. Below
  that: text color/font, input device picker, OSC port, hotkey setup
  (keyboard or VR, Toggle or Push-to-Talk), separate background-image
  pickers for the main window and Tiny Mode, and **Overlay Mode** —
  built for pinning the window in VR via XSOverlay or OVR Toolkit's
  generic desktop-window capture. A photographic background is more
  likely to capture badly than a flat one, so this withholds the
  background image entirely and switches decorative outlines
  (dropdown/modal borders, otherwise a fixed purple) over to whatever
  text color is already set, so the whole panel reads as one consistent
  color in a headset. The saved background path itself is untouched —
  turning this back off restores it exactly as it was.
- **`ui/about.html` + `ui/about.js`** — credits, links to the Ascended
  VRChat Group and Discord, and a donate button — opened from the
  footer's heart icon. The part where I get to say hello directly.
- **`ui/style.css` / `ui/config.css`** — the app's visuals. Widget
  backgrounds are transparent by design (`WA_TranslucentBackground`),
  with a `--text-color` CSS variable the whole UI (including the footer
  icons) follows, driven by Config's text color picker.
- **`assets/`** — app icon, default main/tiny-mode background art, and
  the toggle-button images (UWU/Persona/Profanity/Keep Alive/Tiny Mode,
  each with an on/off state) plus the Start/Stop button art.
- **`.env` / `.env.example`** — `AZURE_SPEECH_KEY` and
  `AZURE_SPEECH_REGION`. Only `.env.example` (a template with no real
  values) is tracked; your real `.env` stays local — see
  `.gitignore`. Some things you keep close, not published. Config's
  gear icon can set/update both from inside the app instead of
  hand-editing the file. Azure is the one engine with its own env-file
  path for historical reasons; the other five engines' credentials
  and paths (Google's service-account key path, AWS's keys/region,
  Whisper's model size/device, Vosk's model folder) live in
  `prefs.json` instead, set entirely from Config — same never-committed
  treatment, see `.gitignore`.
- **`content_version.txt`** — a single integer, bumped by hand whenever
  `ui/`, `assets/`, or the setup guides change. The only thing the
  content-updater compares against.
- **Update checks** (`main.py`, "CONTENT + APP UPDATE CHECKS") — two
  independent things, on purpose. Content (`ui/`, `assets/`, the
  guides) is just loose data, so it's checked and applied fully
  automatically in the background at startup, and self-heals if any of
  it goes missing entirely (`check_required_files` fetches it fresh
  before giving up). The app itself can't self-replace its own running
  exe on Windows, so that check just compares `APP_VERSION` against
  GitHub's latest release and surfaces a dismissible banner with a
  link if there's something newer — same manual download-and-swap step
  as today, just not left to chance. Both are also available as
  on-demand buttons in Config.
- **`AscendedSTT.spec`** — PyInstaller build config; see
  [Building a standalone .exe](#building-a-standalone-exe) below.

## How to run it

1. Python 3.9+ (check "Add Python to PATH" during install on Windows).
2. `pip install -r requirements.txt` — installs PySide6, which bundles
   its own Chromium, so there's no separate WebView2 Runtime to install.
   This covers Azure by default; the other five speech engines are
   each an optional extra listed (commented out) at the bottom of
   `requirements.txt` — only install the one(s) you actually pick.
3. Pick a speech engine and get it talking. Azure's the fastest path
   to a working demo:
   Copy `.env.example` to `.env` and fill in your real Azure values:
   ```
   AZURE_SPEECH_KEY=your_actual_key_here
   AZURE_SPEECH_REGION=eastus
   ```
   Don't have those yet? **[`AZURE_SETUP.md`](AZURE_SETUP.md)** walks
   through creating a free Azure account and a Speech resource on the
   permanent free tier (5 hours/month, genuinely free forever) in
   about fifteen minutes. (Or set/update these later from inside the
   app via the gear icon → Config — it tests the connection for real
   before saving.)

   Prefer something else? Every engine gets set up the same way — the
   gear icon → Config → pick it from the Speech Service dropdown, fill
   in its fields, hit Save — with its own guide:
   [`GOOGLE_SETUP.md`](GOOGLE_SETUP.md),
   [`AWS_SETUP.md`](AWS_SETUP.md),
   [`WHISPER_SETUP.md`](WHISPER_SETUP.md) (local, no account),
   [`VOSK_SETUP.md`](VOSK_SETUP.md) (local, no account),
   [`WINDOWS_SPEECH_SETUP.md`](WINDOWS_SPEECH_SETUP.md) (local, no
   account).
4. `python main.py`

No launcher or supervisor process — `main.py` is the direct entry
point. One clean path in.

### Troubleshooting

- **"Missing required package(s)"** — run the `pip install` command it
  prints. If it's naming a package like `vosk` or `faster_whisper`
  rather than one of the core ones, that's the optional extra for
  whichever engine you picked in Config — see that engine's setup
  guide.
- **No sound recognized** — check the Input Device dropdown in Config
  (not shown for Windows Speech Recognition, which manages its own mic
  input — check Windows' own Sound settings instead).
- **Speech service errors in the log** — usually a wrong key/region/
  credentials file, a missing model folder, or no internet for a cloud
  engine; check/update via the gear icon.
- **Nothing shows up in VRChat** — make sure OSC is enabled in VRChat
  (Action Menu → Options → OSC → Enabled), and the port in Config
  matches what VRChat is using (default 9000).

## Building a standalone .exe

For handing this to someone who just wants to talk, not set up a dev
environment first:

```
pip install -r requirements.txt
pip install pyinstaller
pyinstaller AscendedSTT.spec
```

This produces `dist/AscendedSTT/` containing `AscendedSTT.exe` and its
supporting files. **Copy `ui/` and `assets/` into that same folder** —
intentionally not baked into the exe, see the note in
`AscendedSTT.spec`. **Also copy the six `*_SETUP.md` files** — Config's
"View Setup Guide" buttons read these straight off disk next to the
exe at runtime (`get_app_dir()`), so a build missing them just shows a
"couldn't read" error in that window instead of the guide, nothing
worse. **Also copy `content_version.txt`** — the in-app content-updater
reads this to know what it's currently shipping; missing it just means
the first launch treats everything as out of date and quietly
re-fetches it once. Also copy your `.env` (or configure Azure after
first launch via the gear icon). Zip up the whole `dist/AscendedSTT/`
folder — that's the distributable app.

Whoever you're handing this to only needs the optional package(s) for
the engine(s) they'll actually use (see `requirements.txt`) installed
in whatever Python environment `pyinstaller` ran in — same as any
other dependency. Vosk additionally needs its model folder present
somewhere on the machine it'll run on (Config points at it by path);
Whisper downloads its model the first time it's used, so that first
run needs internet even if every later one doesn't.

### Windows Defender / antivirus flagging

Common with PyInstaller-built executables generally, not specific to
this app having done anything wrong — I'd rather tell you straight
than let a scary popup do the talking. An unsigned, self-extracting
`.exe`, plus this app's legitimate use of a global keyboard hook (for
the hotkey, via `pynput`) look behaviorally similar to patterns
malware also uses, and heuristic engines can't tell intent from
behavior alone.

Already applied in `AscendedSTT.spec`: `upx=False` (no compression —
larger file, but avoids a real evasion-technique false-positive
trigger) and a `onedir` build via `COLLECT` rather than a single
self-extracting `onefile`, which avoids the "unpacks itself to a temp
folder" heuristic entirely.

The actual fix if this needs to go out to people who don't already
expect an unsigned-exe security prompt is **code signing** (a
certificate from a CA like DigiCert/Sectigo/SSL.com, roughly
$70–400+/year with identity verification) — a cost/effort call only you
can make. Free options: submit a build you believe is a false positive
at [microsoft.com/en-us/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission),
or check [virustotal.com](https://www.virustotal.com) before
distributing to see exactly which engines flag it and why. See
`DEFENDER_SUBMISSION.md` for the full step-by-step submission
checklist — it's a per-release thing (new build = new file hash = a
fresh review), not a one-time setup.

## Architecture note: why Qt/QWebEngine instead of pywebview

This is a rebuild of the app on a different foundation than an earlier
pywebview-based version. pywebview's Windows backend routed everything
through `pythonnet`'s .NET interop layer to reach WebView2, and that
layer had a real, unresolved upstream bug causing intermittent startup
freezes. Qt's WebEngine talks to its own embedded Chromium directly
through Qt's own bindings — no .NET interop at all, so that entire bug
class can't happen here. Sometimes the fix isn't patching the crack,
it's building on ground that doesn't crack. Practical effect: no
separate launcher/supervisor process anymore, just one process that
either works or reports a real error. The UI itself (the HTML/CSS/JS in
`ui/`) carried over essentially unchanged; what changed is the
Python-side shell and the JS↔Python bridge (`QWebChannel` instead of
pywebview's `js_api`).

## What's next (in rough order)

1. **Launch with SteamVR.** `openvr` (already a dependency, for the VR
   controller hotkey) exposes `addApplicationManifest` and
   `setApplicationAutoLaunch` directly — register a `.vrmanifest` on
   startup (regenerated each launch with the exe's current path, since
   this ships as a portable folder rather than a real Steam install,
   not a fixed install directory) and the app shows up in SteamVR's
   own Settings → Startup/Shutdown page with a normal on/off toggle,
   no custom UI required for that part. Worth mirroring the same
   toggle inside STT's own Config too, so it's not buried in SteamVR's
   settings for anyone who'd rather not go digging.
2. Anything else that comes up as the team actually uses this day to
   day. This project grows the way anything worth building does — one
   real need at a time, not a spec written in a vacuum.

Present in the now, built to last. — Jasper
