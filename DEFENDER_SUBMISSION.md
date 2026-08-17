# Submitting a false-positive report to Microsoft Defender

A repeatable checklist to run **every time you cut a new release**, not
a one-time setup step — same discipline as backing up a save file
before every big fight, not just the first one. Microsoft's review
applies to one specific file hash — a rebuild from identical source
still produces a different hash (timestamps, library versions, etc.
all bleed into the output), so a prior "cleared" verdict doesn't carry
over to the next build.

There's no public API for this — Microsoft's submission tool is a
plain web form, and it asks for your contact email, so this stays a
manual, human step on purpose. Nothing in this repo automates clicking
Submit for you. Some doors you open yourself.

## 1. Confirm it's actually a false positive first

Before submitting anything, upload the built package to
[virustotal.com](https://www.virustotal.com) and see which of the ~70
engines flag it, and as what.

- **Only Defender, or a handful of low-reputation heuristic engines,
  flagging an unsigned PyInstaller exe** — the expected pattern, safe
  to submit as a false positive.
- **Most/all engines agree, or a named, specific malware family is
  called out** — stop. Something is actually wrong; don't submit a
  build that might genuinely be flagged for cause (a supply-chain
  compromise in a dependency, an infected build machine, etc.). Read
  the room before you argue with it.

## 2. Hash the exact file you're submitting

```
.\scripts\hash_release.ps1 dist\AscendedSTT-v0.1.0-win64.zip
```

Record the hash — you'll want it in both the release notes and the log
at the bottom of this file, so "has this build been submitted yet" is
never a guess.

## 3. Submit to Microsoft

Go to
[microsoft.com/en-us/wdsi/filesubmission](https://www.microsoft.com/en-us/wdsi/filesubmission):

- **Submission type:** Software developer
- **File:** the exact build from step 2 (the zip or the raw `.exe`)
- **Detection category:** whatever Defender/SmartScreen actually
  flagged it as — check Windows Security → Protection history on the
  machine that flagged it. "Incorrect detection" is the right general
  bucket if you're not sure.
- **Comments:** the single most useful thing you can include is a
  direct link to this public GitHub repo, plus the exact commit/tag the
  build came from, and the build command
  (`pyinstaller AscendedSTT.spec`). That lets a human reviewer actually
  verify what the file does instead of taking your word for it —
  proof beats promises. Mention the known
  "looks-like-malware-behaviorally" factor specific to this app too —
  see the "Windows Defender / antivirus flagging" section in
  `BUILD.md` for what that actually is here (the global keyboard hook
  used for the hotkey, specifically).
- Submit, and save the confirmation/submission ID.

## 4. After submitting

There's no published SLA — this is reactive, not preventative, and can
take a while. Patience is part of the craft. Log it below regardless of
outcome, so a future release doesn't get resubmitted blind or skipped
by mistake.

## Submission log

| Date | Version | SHA256 (short) | Submission ID | Outcome |
|------|---------|-----------------|----------------|---------|
| | | | | |
