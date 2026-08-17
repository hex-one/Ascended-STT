# Whisper Setup (local)

No account, no key, no internet connection required once it's running.
Whisper runs entirely on this PC via `faster-whisper` — a real speed-up
implementation of OpenAI's Whisper model, not a cloud proxy for it.
Nothing you say leaves your machine.

## 1. Install the package

```
pip install faster-whisper
```

That's the only setup step. There's no account to create and no key to
paste — everything else happens automatically the first time you use
it.

## 2. Pick a model size and device in Config

Launch the app, click the gear icon → **Config**, choose **Whisper
(local)** from the Speech Service dropdown, and pick:

- **Model size**: `tiny`, `base`, `small`, `medium`, or `large-v3`.
  Bigger models are more accurate and slower; smaller ones are faster
  and less accurate. `base` is a reasonable starting point on most
  hardware — try `small` if accuracy matters more than latency and
  your PC can keep up, or `tiny` if you're on weaker hardware and want
  faster turnaround over perfect wording.
- **Device**: `CPU` works everywhere. `GPU (CUDA)` is dramatically
  faster if you have an NVIDIA GPU with CUDA set up, but does nothing
  useful (and may just fail) without one — stick to CPU unless you
  know you have a working CUDA setup.

Click **Save Whisper Settings**. The first time you pick a given
model/device combination, it downloads that model automatically — this
can take anywhere from a few seconds (`tiny`) to a couple of minutes
(`large-v3`) depending on your connection, and only happens once per
model. After that, switching back to a previously-downloaded model
loads instantly from disk.

## How this engine actually behaves

Worth knowing going in: Whisper isn't a live streaming recognizer the
way Azure/Google/AWS are. It listens for a pause in your speech (a
short silence after you stop talking), then transcribes that whole
utterance in one shot. That means slightly more latency than the cloud
engines — you'll see text appear after you finish a sentence, not
word-by-word as you speak. In exchange, it's completely private and
completely free, forever, with no usage limit.

Whisper can also translate speech directly into English (pick "English
(translate)" as the output in the main window) — but only into
English. It can't translate into other target languages the way
Azure's translation feature can.

## Troubleshooting

- **"Couldn't load the Whisper model"** — usually a first-download
  network hiccup, or `faster-whisper` isn't actually installed (rerun
  `pip install faster-whisper`). Retry Save once your connection is
  stable.
- **GPU device selected but it's slow or errors out** — you likely
  don't have a working CUDA install. Switch Device back to CPU in
  Config.
- **Transcription feels delayed** — that's the pause-then-transcribe
  design, not a bug. A smaller model (`tiny`/`base`) transcribes faster
  once triggered if the delay bothers you.
