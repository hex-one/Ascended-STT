# Ascended STT — Steam store page copy

Ready to paste into Steamworks once the AppID exists. Steam's store
page editor uses its own lightweight markup (`[b]`, `[i]`, `[list]`,
`[*]`, `[h1]`, `[url=...]`, etc.) rather than Markdown — the section
breaks and bullets below translate directly; swap `**bold**` for
`[b]bold[/b]` and so on when you paste. Exact field character limits
and current image-asset specs (capsule/header/hero art) are Valve's to
publish, not mine to guess at — check Steamworks' own docs for
whatever's current when you're actually filling the page in.

---

## Short description (search results / library blurb)

> Speak, and it lands in your VRChat chatbox. Six speech engines —
> cloud or fully offline — live translation, and 26 joke personas.
> Free and open source.

(153 characters — comfortably under Steam's short-description limit.)

## About This Game (main store page body)

**Say it out loud, and Ascended STT sends it straight into VRChat's
chatbox over OSC — no typing, no breaking flow.**

Built for anyone who'd rather talk than type mid-scene: push-to-talk
or hands-free toggle, and it just works, without a separate launcher
or a fragile startup checklist standing between you and being heard.

**Pick your own speech engine — whichever actually fits how you
play:**
[list]
[*] **Azure Speech Services** — the original, most fully-featured
option: 147 input locales across 78 language groups, live translation
into 11 output languages, custom endpoint support for your own
trained model. Genuine permanent free tier, 5 hours/month, no card
ever charged past identity verification.
[*] **Google Cloud Speech-to-Text** — broad regional dialect coverage,
free tier around 60 minutes/month at last check (Google's own current
pricing page has the up-to-date number).
[*] **AWS Transcribe** — real-time streaming recognition, 60
minutes/month free for your first 12 months on a new AWS account.
[*] **Whisper (local)** — runs entirely on your own PC, five model
sizes to trade speed for accuracy, no account, no key, nothing ever
leaves your machine.
[*] **Vosk (local)** — also fully offline, lighter weight and
genuinely real-time, good on modest hardware.
[*] **Windows Speech Recognition (local)** — rides on Windows' own
built-in recognizer. If it's already set up on your PC, there is
nothing left to configure.
[/list]

Every engine gets the same Config screen: pick it from a dropdown,
fill in whatever it needs (a key, a downloaded model folder, or
nothing at all), hit Save — it tests the connection for real before
committing, with the result shown right there.

**Because not everything has to be serious:**
[list]
[*] **26 joke personas** — Pirate, Drill Sergeant, Shakespeare, Sleepy
Ghost, Grumpy Old Man, and 21 more — each one a small, real text
transform, not a gimmick that only half-works.
[*] **UWU mode**, because sometimes that's exactly what the room needs.
[*] Built-in profanity filter, on by default, one click to turn off —
works the same regardless of which engine is doing the listening.
[/list]

**Built to actually stay connected:**
[list]
[*] **Keep Alive** proactively refreshes cloud engine connections
during idle periods — the actual fix for the "goes silent after
sitting a while" problem, not a band-aid on top of it. (Local engines
skip this entirely — a loaded model has no connection to go stale.)
[*] Hotkey support, keyboard or VR controller, Toggle or
Push-to-Talk.
[*] **Overlay Mode** — pin the app in VR via XSOverlay or OVR
Toolkit's window capture. Background steps aside, borders match your
text color, tested clean in an actual headset.
[/list]

**Free. Open source. GPL-3.0.** Azure's the fastest path to a working
demo — the app walks you through its genuine permanent free tier in
about fifteen minutes — but every engine has its own setup guide
included in-app and in the repo, including two (Whisper, Vosk) that
need no account or key at all.

## System requirements

- **OS:** Windows 10/11 (64-bit)
- **Other:** A microphone, plus whatever your chosen speech engine
  needs — a free API key for a cloud engine, or nothing at all for a
  local one (setup guide for each included in-app and in the repo).

## Tags (suggested)

Utilities, VR, Social, Voice Chat, Accessibility, Free to Play

## Legal / EULA note

GPL-3.0 licensed — see the repository's `LICENSE` file. Speech
recognition runs through whichever engine you select in Config.
Choosing Azure, Google Cloud, or AWS Transcribe sends your audio to
that provider under your own account with that provider and its own
terms — Ascended STT itself never stores or transmits your audio
anywhere beyond that call. Choosing Whisper, Vosk, or Windows Speech
Recognition keeps everything local; no audio leaves your machine.
Steam's own partner-agreement legal boilerplate applies on top of
this; nothing here overrides what Valve requires on the store-page
legal tab.
