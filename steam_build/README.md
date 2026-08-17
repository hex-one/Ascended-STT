# Publishing Ascended STT to Steam via SteamPipe

The bridge between "built exe" and "live on Steam." Doesn't touch
anything until you actually run it — safe to read through before your
Steamworks account even clears.

## Before you start

You need, in this order:
1. An **approved Steamworks partner account** with Ascended STT's app
   created (Steamworks assigns the real **AppID** here).
2. A **Depot ID** under that app — Steamworks → your app → SteamPipe →
   Depots. It usually offers `AppID + 1` as the default; use whatever
   it actually shows you.
3. **`steamcmd`** installed — Valve's command-line tool for talking to
   SteamPipe. Download from
   [Steamworks' SteamCMD docs](https://partner.steamgames.com/doc/sdk/uploading)
   once you're logged into Steamworks (the exact download link/steps
   are gated behind partner login, so no direct link here).
4. A Steam account with **publish permissions** on this app — usually
   the same account you use for Steamworks itself, but large teams
   sometimes use a dedicated build account. Either way, this is a real
   Steam login, so `steamcmd` will prompt for it (and Steam Guard)
   interactively — nothing about that gets automated or stored here.

## 1. Fill in the real IDs

Open both `.vdf` files in this folder and swap `PLACEHOLDER_APPID` /
`PLACEHOLDER_DEPOTID` for the real numbers from Steamworks. That's the
only editing needed — everything else already points at the right
build output.

## 2. Build Ascended STT

```
cd ..
pyinstaller AscendedSTT.spec
```

Then copy `ui/` and `assets/` into `dist/AscendedSTT/` — same manual
step BUILD.md already documents (not baked into the exe on purpose).
**Do not copy `.env`** into the dist folder; `depot_build_stt.vdf`
excludes it as a second safety net, but the real key never belonging
there in the first place is the actual fix.

This whole build has to happen fresh before every upload — SteamPipe
uploads whatever's sitting in `dist/AscendedSTT/` at the moment you
run the build command below, not some cached idea of what the app is.

## 3. Upload

From this folder:

```
steamcmd +login <your_steam_username> +run_app_build app_build_stt.vdf +quit
```

`steamcmd` will prompt for your password and Steam Guard code right
there in the terminal — this is the one point in the whole pipeline
that's genuinely interactive, on purpose. Nothing in these scripts
stores or automates that login.

If it succeeds, `steamcmd` prints a build ID and the new build shows
up under Steamworks → your app → Builds — sitting there, **not yet
live** on any public branch (that's what `"setlive": ""` in
`app_build_stt.vdf` buys you). Promote it to `default` from the
Builds page in Steamworks once you've actually smoke-tested it —
including checking that a real Azure key still needs to be entered by
whoever downloads it, since none is bundled.

## Iterating

Same three steps, every time: rebuild + copy `ui/`/`assets/`, re-run
the `steamcmd` upload, promote when you're happy. Nothing here needs
to change between releases except the version you're actually
shipping.

## Heads up: this build also has an in-app content-updater

Ascended STT checks GitHub in the background at startup and quietly
refreshes `ui/`, `assets/`, and the setup guides if a newer
`content_version.txt` is published — see `main.py`'s "CONTENT + APP
UPDATE CHECKS" section. That's genuinely useful for the direct-download
build, where Steam isn't in the picture at all, but it's worth thinking
through for a Steam build specifically: SteamPipe already owns getting
players onto the latest files, and having the app *also* silently patch
itself from GitHub means a Steam build could end up running content
that never went through a Steam build/verification pass — and "Verify
integrity of game files" in Steam could then flag those self-patched
files as modified.

Nothing here disables that automatically — there's currently no
reliable way for the app to detect "I'm running under Steam" without
adding real Steamworks SDK integration, which this project doesn't use
today. Worth deciding before this goes live on Steam: either bump
`content_version.txt` in lockstep with every Steam build so the two
sources never actually disagree, or add a real Steam-detection guard
that skips the automatic content check entirely (the manual "Check for
Content Updates" button in Config could stay either way, since that's
an explicit, on-purpose action). Flagging this now so it doesn't get
silently forgotten once Steamworks access actually exists.
