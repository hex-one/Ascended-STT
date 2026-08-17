# -*- mode: python ; coding: utf-8 -*-
#
# The forge that turns source into something someone else can just run.
# Build with (on Windows, inside this folder, with requirements.txt
# already installed): pyinstaller AscendedSTT.spec
#
# ui/ and assets/ ship as plain folders next to the exe, not baked in -
# same reasoning as the earlier pywebview build: get_app_dir() already
# resolves correctly either way, and this avoids a whole class of
# PyInstaller data-bundling edge cases for arbitrary HTML/CSS/JS/PNGs.
#
# No launcher/supervisor needed this time - main.py is the entry point
# directly. That whole pattern only existed to work around a pywebview
# bug that can't happen with this Qt-based architecture.
#
# --- Antivirus / Windows Defender false positives ---
# Unsigned PyInstaller executables get flagged fairly often - this is a
# known, common issue, not specific to this app. Two real mitigations
# are applied below (upx=False, exclude_binaries/COLLECT for a onedir
# layout) - see BUILD.md for the full picture, including what these
# can and can't fix on their own. Honesty first, even about the parts
# that aren't fully solved yet.

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

hidden_imports = [
    'azure.cognitiveservices.speech',
    'sounddevice',
    '_sounddevice_data',
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'pynput._util.win32',
    'pynput._util.win32_vks',
]

# Azure Speech SDK loads its native library manually at runtime rather
# than as a normal linked dependency, so PyInstaller's default analysis
# doesn't detect and bundle it on its own - confirmed by testing the
# earlier pywebview build the same way.
azure_speech_binaries = collect_dynamic_libs('azure.cognitiveservices.speech')
azure_speech_datas = collect_data_files('azure.cognitiveservices.speech')

# openvr (optional -- only needed for the VR Controller hotkey option)
# has the exact same problem: it ctypes-loads its own native library at
# import time, invisible to PyInstaller's normal dependency analysis.
# Confirmed the hard way: without this, the packaged exe bundled
# openvr's pure-Python __init__.py but not the .dll it immediately
# tries to load, so it crashed on startup for EVERYONE, not just people
# without SteamVR (main.py's `except Exception` around the import is a
# second, independent safety net for this same class of failure -- this
# fixes the actual cause). Only collected if openvr is installed in the
# build environment at all, since it's genuinely optional per
# requirements.txt -- building without it just ships without VR hotkey
# support, same as before this existed.
try:
    openvr_binaries = collect_dynamic_libs('openvr')
except Exception:
    openvr_binaries = []  # optional means optional, even at build time

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=azure_speech_binaries + openvr_binaries,
    datas=azure_speech_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AscendedSTT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-compressed executables are frequently flagged by AV heuristics,
    # since UPX is heavily used by actual malware packers too, not just
    # legitimate small utilities. Leaving this off is a real, free
    # mitigation - the trade-off is a larger file size.
    upx=False,
    console=False,
    icon='assets/app_icon.ico',
)

# onedir (a folder with the exe + supporting files) rather than onefile
# (a single exe that self-extracts to a temp folder at runtime) -
# onefile's runtime self-extraction is a behavioral pattern that heuristic
# AV engines often flag on its own, on top of everything else. Arrive as
# you are, nothing hidden in a temp folder.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AscendedSTT',
)
