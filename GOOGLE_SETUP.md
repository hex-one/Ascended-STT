# Google Cloud Speech-to-Text Setup

Ascended STT needs one thing from Google Cloud to run this engine: a
**service account key file** (a `.json` you download once and point
Config at). Google Cloud's free trial gives you $300 in credit for 90
days, and Speech-to-Text itself has its own small always-free monthly
allowance on top of that — enough to try this engine without paying
anything up front.

**Before you start:** this engine transcribes only — it doesn't
translate. Google Cloud's translation is a separate product
(Cloud Translation) this app doesn't chain into, so the output-language
dropdown for this engine only offers "No translation."

## 1. Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
   and sign in with any Google account.
2. Click the project dropdown at the top → **New Project**. Name it
   whatever you like, e.g. `ascended-stt`.
3. First time here, Google will ask you to start (or skip) the free
   trial. You don't need it for the always-free Speech-to-Text
   allowance, but it doesn't hurt to have the extra credit either.

## 2. Enable the Speech-to-Text API

1. With your project selected, use the search bar at the top and type
   **Speech-to-Text API**.
2. Click it, then click **Enable**. Give it a few seconds.

Nothing works until this is on — a disabled API is the single most
common reason the connection test in Config fails.

## 3. Create a service account and download its key

1. Search for **Service Accounts** and select it (under IAM & Admin).
2. Click **+ Create Service Account**. Name it something like
   `ascended-stt`, click **Create and Continue**.
3. Grant it the role **Cloud Speech Client** (search for "Speech" in
   the role picker) — that's all this app needs, nothing broader.
   Click **Continue**, then **Done**.
4. Click into the service account you just made → **Keys** tab →
   **Add Key** → **Create new key** → **JSON** → **Create**. A `.json`
   file downloads to your computer.

Treat that file like a password — anyone who has it can use it against
your project. Don't commit it to a public repo.

## 4. Plug it into Ascended STT

Launch the app, click the gear icon → **Config**, choose **Google
Cloud Speech-to-Text** from the Speech Service dropdown, click
**Browse...**, and select the `.json` file you just downloaded. Click
**Save Google Settings** — it runs a real, minimal test call against
your project before saving, so a disabled API or bad key gets caught
immediately instead of surfacing later mid-conversation.

## Staying inside the free allowance

- Speech-to-Text has its own always-free monthly quota (currently
  measured in minutes of audio) separate from the $300 trial credit —
  check
  [cloud.google.com/speech-to-text/pricing](https://cloud.google.com/speech-to-text/pricing)
  for the exact current number, since Google does adjust these figures
  over time.
- Going over the free allowance starts billing your project directly —
  unlike Azure's Free F0 tier, Google Cloud doesn't just stop working
  at the limit. Keep an eye on **Billing → Reports** in the console if
  you're using this a lot.

## Honesty note

This engine is built correctly against Google Cloud's documented
streaming API shape, but it hasn't been tested against a real account
by whoever built it. If the connection test fails in a way that looks
like a bug rather than a credentials/permissions problem, that's the
most likely explanation — an untested edge, not a guess at the wrong
API entirely.

## Troubleshooting

- **"PERMISSION_DENIED" or "API not enabled"** — go back to step 2 and
  confirm the Speech-to-Text API shows as **Enabled** for the correct
  project (the one your service account belongs to).
- **"File not found"** — the `.json` key got moved or renamed after you
  browsed to it in Config. Re-browse to wherever it actually lives now.
- **Works in Config's test but nothing transcribes** — check that the
  language you picked in the app's main window is one this engine
  actually lists; Google's short language codes (like `cmn-Hans-CN`)
  are specific, and a typo'd custom code elsewhere won't fall back
  quietly.
