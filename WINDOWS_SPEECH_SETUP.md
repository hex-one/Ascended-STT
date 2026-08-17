# Windows Speech Recognition Setup (local)

No account, no key, no download inside the app — this engine rides on
speech recognition Windows already ships with. If it's set up on your
PC, there's genuinely nothing to configure here beyond installing one
package.

## 1. Install the package

```
pip install pywin32
```

This gives the app access to Windows' own speech recognition engine
(SAPI) the same way any other desktop app on Windows would.

## 2. Make sure Windows Speech Recognition itself works

This engine manages its own microphone input directly through Windows'
audio stack — it's not fed audio the way the other five engines are,
which is also why it doesn't appear in the app's input-device picker
when selected. That means the language and recognition quality are
entirely controlled by Windows itself, not by this app:

1. Open **Settings → Time & Language → Speech**.
2. Under **Speech language**, make sure it's set to the language you
   want to speak in. If your language isn't installed, click it and
   follow the prompt to download it.
3. Windows may prompt you to run its one-time speech recognition setup
   / microphone calibration the first time you use dictation anywhere
   on the system — if you've never used Windows dictation before
   (Win+H), it's worth doing that once so the engine has a baseline.

There's no language dropdown for this engine inside Ascended STT
itself — whatever's set as the Windows-wide default is what gets used.
Change it in Settings, not in Config.

## 3. Plug it into Ascended STT

Launch the app, click the gear icon → **Config**, choose **Windows
Speech Recognition** from the Speech Service dropdown, and click
**Test Windows Speech** — it opens a real SAPI recognition context to
confirm Windows' speech engine is actually available before you rely
on it. There's nothing to save here since there's no key or path to
enter; the test button is the whole interaction.

## Troubleshooting

- **Test fails / SAPI unavailable** — confirm `pywin32` installed
  cleanly (`pip show pywin32`), and that Windows Speech Recognition
  hasn't been disabled by Group Policy on a managed PC.
- **Recognizes the wrong language** — that's Windows' default speech
  language, not an app setting. Fix it in Settings → Time & Language →
  Speech, not in Ascended STT's Config.
- **No microphone picker for this engine** — expected. Windows Speech
  Recognition picks its own input device through Windows' own audio
  settings (Settings → System → Sound), independent of the device
  picker Ascended STT uses for the other five engines.
