# Vosk Setup (local)

No account, no key, no internet connection required once it's running.
Vosk runs entirely on this PC and, unlike Whisper, is genuinely
streaming — it recognizes speech incrementally, the same "the instant
it's sure" feel as the cloud engines, just without a network round
trip. It trades a bit of accuracy for that speed and for running
comfortably on modest hardware.

## 1. Install the package

```
pip install vosk
```

## 2. Download a model for your language

A Vosk model IS a specific language — there's no runtime language
dropdown for this engine, because switching languages means switching
which model folder you point the app at.

1. Go to
   [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models)
   and find your language.
2. Each language usually offers a **small** model (tens of MB, fast,
   less accurate) and sometimes a bigger one (hundreds of MB to a few
   GB, slower to load, more accurate). The small model is the right
   starting point for most people — it's specifically designed for
   real-time use like this.
3. Download the `.zip` for your chosen model and **extract it
   somewhere permanent** (not a temp folder — Config needs to keep
   pointing at this location). The extracted folder should directly
   contain files like `am`, `conf`, `graph` — if you see a single
   nested folder inside instead, point Config at that inner folder.

## 3. Plug it into Ascended STT

Launch the app, click the gear icon → **Config**, choose **Vosk
(local)** from the Speech Service dropdown, click **Browse...**, and
select the extracted model folder from step 2. Click **Save Vosk
Settings** — it loads the model for real before saving, so a wrong
folder or corrupted download gets caught immediately.

Model loading can take a few seconds the first time (longer for bigger
models) — that's normal, not a hang.

## Troubleshooting

- **"No valid Vosk model folder set" / "Couldn't load the Vosk
  model"** — double check you pointed Config at the folder that
  directly contains `am`/`conf`/`graph`, not the parent folder the zip
  extracted into, and not a folder one level too deep.
- **Recognition feels less accurate than Azure/Google** — expected
  trade-off for running fully offline on modest hardware. Try a bigger
  model for your language if one's available and your PC can handle
  the extra load time.
- **Wrong language recognized** — you're pointed at the wrong model
  folder. Download and switch to the correct language's model.
