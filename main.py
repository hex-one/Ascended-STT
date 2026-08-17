"""
Ascended STT - main application (PySide6 / QWebEngineView version)
--------------------------------------------------------------------
Jasper Hex here. Same app as before, rebuilt on a fundamentally
different foundation. The old pywebview-based build routed Windows
rendering through pythonnet's .NET interop layer to reach WebView2,
and that interop layer had a real, unresolved upstream bug (a runaway
recursive property walk on window.native) that caused the intermittent
startup freezes chased at length in earlier work. Qt's WebEngine talks
to its embedded Chromium directly through Qt's own C++ bindings - no
pythonnet, no .NET interop, so that entire bug class structurally
cannot happen here. Sometimes you don't patch the crack, you build on
ground that doesn't crack. That's the actual point of this rewrite:
not new features, a more stable foundation.

Practical effect: no more supervisor/launcher process, no startup
checklist working around an unreliable bridge - just one process that
either works or reports a real error.
"""

import os
import sys
import json
import re
import random
import threading
import time
import webbrowser
import importlib
import functools
import http.server
import socketserver
import traceback
import urllib.request
import urllib.error
import zipfile
import tempfile
import shutil
import ctypes
from datetime import datetime

# --- Dependency check: run BEFORE importing anything third-party, so a
# missing package produces a clear "run this command" message instead of
# a confusing traceback. ---
_REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "sounddevice": "sounddevice",
    "PIL": "pillow",
    "azure.cognitiveservices.speech": "azure-cognitiveservices-speech",
    "pythonosc": "python-osc",
    "pynput": "pynput",
    "dotenv": "python-dotenv",
    "PySide6": "PySide6",
}


def _check_dependencies():
    missing = []
    for module_name, pip_name in _REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)
    return missing


_missing_packages = _check_dependencies()
if _missing_packages:
    print(
        "Missing required package(s): " + ", ".join(_missing_packages) + "\n\n"
        "Run this command, then run this script again:\n\n"
        f"    pip install {' '.join(_missing_packages)}\n"
    )
    sys.exit(1)

import numpy as np
import sounddevice as sd
import azure.cognitiveservices.speech as speechsdk
from PIL import Image
from pythonosc.udp_client import SimpleUDPClient
from pynput import keyboard
from dotenv import load_dotenv

from PySide6.QtCore import QObject, Signal, Slot, QUrl, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel

import speech_engines

try:
    import openvr
    OPENVR_MODULE_AVAILABLE = True
except Exception:
    # Deliberately broad, not just ImportError: openvr loads its native
    # library itself via ctypes at import time, so a packaged build
    # missing/misplacing that DLL raises PyInstaller's own load-error
    # type here, not a plain ImportError -- catching only ImportError
    # let that crash the entire app on startup instead of just leaving
    # the VR controller hotkey option unavailable, which is the whole
    # point of this being wrapped in a try at all.
    OPENVR_MODULE_AVAILABLE = False


def get_app_dir():
    """Folder the script/exe actually lives in - works both as a normal
    .py file and when bundled into a standalone .exe. Know where home
    is, regardless of which form you're wearing."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _safe_print(*args, **kwargs):
    """print(), but one that lives through a console=False frozen build
    launched the way most folks actually launch it -- double-click, no
    console trailing along behind. sys.stdout/sys.stderr are flat-out
    None in that world, not just quietly redirected somewhere, so a
    plain print() or sys.stderr.write() goes down swinging the instant
    it fires: "AttributeError: 'NoneType' object has no attribute
    'write'". This was the real cause of a real crash a real person
    hit, not a ghost story -- every page load failing with
    ERR_EMPTY_RESPONSE, traced straight back to the local server's own
    request logging tripping over exactly this. No console to speak
    into just means: stay quiet, instead of taking the whole thing
    down with you."""
    if sys.stdout is None:
        return
    try:
        print(*args, **kwargs)
    except Exception:
        pass


load_dotenv(os.path.join(get_app_dir(), ".env"))

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "")

VRCHAT_IP = "127.0.0.1"
VRCHAT_PORT = 9000

SAMPLE_RATE = 16000

APP_NAME = "Ascended STT"
# Bump this by hand alongside every GitHub Release tag (vX.Y.Z) -- it's
# the only thing the app-update check has to compare against, see
# check_for_app_update() below.
APP_VERSION = "0.2.2"
APP_CREDITS_TEXT = (
    "Made by Jasper Hex and Ryy for the Ascended VRChat community.\n\n"
    "We got tired of every other speech-to-text app randomly dropping "
    "connection and being slooooowww... so we just made our own "
    "instead! Made sure it had free options. Cheers!"
)
DONATE_BLURB = (
    "Running the Group and building tools like this one has been "
    "fully out-of-pocket the whole way -- VRC+ drops, extra services "
    "for the community, all of it, on me. I want to keep it that "
    "way: everything free, forever, and always getting a little "
    "better. Anything you toss in goes straight back into that, "
    "nothing else. Thank you for being here."
)
DONATION_URL = "https://ko-fi.com/jasperhex_vr"
GROUP_URL = "https://vrchat.com/home/group/grp_3de3f36a-8ac6-4fa3-8a39-b366e85ac1c7"
DISCORD_URL = "https://discord.gg/AUNyc6kjcd"
COPYRIGHT_TEXT = "Copyright Ascended VRC Group 2026"

WINDOW_WIDTH = 380
ACTIVITY_LIGHT_CHECK_MS = 250          # how often TX/RX light state is re-evaluated and pushed
KEEP_ALIVE_HEARTBEAT_SECONDS = 15      # how often a heartbeat pulse is pushed to the UI
KEEP_ALIVE_IDLE_REFRESH_SECONDS = 240  # proactively refresh an idle connection after this long,
                                         # before it has a chance to go silently stale on its own
WINDOW_HEIGHT = 640
TINY_WINDOW_HEIGHT = 260

PREFS_FILE = os.path.join(get_app_dir(), "prefs.json")

INPUT_LANGUAGE_GROUPS = [
    ("Afrikaans", {"Afrikaans (South Africa)": "af-ZA"}),
    ("Amharic", {"Amharic (Ethiopia)": "am-ET"}),
    ("Arabic", {
        "Arabic (Algeria)": "ar-DZ", "Arabic (Bahrain)": "ar-BH",
        "Arabic (Egypt)": "ar-EG", "Arabic (Iraq)": "ar-IQ",
        "Arabic (Israel)": "ar-IL", "Arabic (Jordan)": "ar-JO",
        "Arabic (Kuwait)": "ar-KW", "Arabic (Lebanon)": "ar-LB",
        "Arabic (Libya)": "ar-LY", "Arabic (Morocco)": "ar-MA",
        "Arabic (Oman)": "ar-OM", "Arabic (Palestinian Authority)": "ar-PS",
        "Arabic (Qatar)": "ar-QA", "Arabic (Saudi Arabia)": "ar-SA",
        "Arabic (Syria)": "ar-SY", "Arabic (Tunisia)": "ar-TN",
        "Arabic (United Arab Emirates)": "ar-AE", "Arabic (Yemen)": "ar-YE",
    }),
    ("Armenian", {"Armenian (Armenia)": "hy-AM"}),
    ("Assamese", {"Assamese (India)": "as-IN"}),
    ("Azerbaijani", {"Azerbaijani (Latin, Azerbaijan)": "az-AZ"}),
    ("Basque", {"Basque": "eu-ES"}),
    ("Bengali", {"Bengali (India)": "bn-IN"}),
    ("Bhojpuri", {"Bhojpuri (India)": "bho-IN"}),
    ("Bosnian", {"Bosnian (Bosnia and Herzegovina)": "bs-BA"}),
    ("Bulgarian", {"Bulgarian (Bulgaria)": "bg-BG"}),
    ("Burmese", {"Burmese (Myanmar)": "my-MM"}),
    ("Catalan", {"Catalan": "ca-ES"}),
    ("Chinese", {
        "Chinese (Cantonese, Simplified)": "yue-CN",
        "Chinese (Cantonese, Traditional)": "zh-HK",
        "Chinese (Jilu Mandarin, Simplified)": "zh-CN-shandong",
        "Chinese (Mandarin, Simplified)": "zh-CN",
        "Chinese (Southwestern Mandarin, Simplified)": "zh-CN-sichuan",
        "Chinese (Taiwanese Mandarin, Traditional)": "zh-TW",
        "Chinese (Wu, Simplified)": "wuu-CN",
    }),
    ("Croatian", {"Croatian (Croatia)": "hr-HR"}),
    ("Czech", {"Czech (Czechia)": "cs-CZ"}),
    ("Danish", {"Danish (Denmark)": "da-DK"}),
    ("Dutch", {"Dutch (Belgium)": "nl-BE", "Dutch (Netherlands)": "nl-NL"}),
    ("English", {
        "English (Australia)": "en-AU", "English (Canada)": "en-CA",
        "English (Ghana)": "en-GH", "English (Hong Kong SAR)": "en-HK",
        "English (India)": "en-IN", "English (Ireland)": "en-IE",
        "English (Kenya)": "en-KE", "English (New Zealand)": "en-NZ",
        "English (Nigeria)": "en-NG", "English (Philippines)": "en-PH",
        "English (Singapore)": "en-SG", "English (South Africa)": "en-ZA",
        "English (Tanzania)": "en-TZ", "English (UK)": "en-GB",
        "English (US)": "en-US",
    }),
    ("Estonian", {"Estonian (Estonia)": "et-EE"}),
    ("Filipino", {"Filipino (Philippines)": "fil-PH"}),
    ("Finnish", {"Finnish (Finland)": "fi-FI"}),
    ("French", {
        "French (Belgium)": "fr-BE", "French (Canada)": "fr-CA",
        "French (France)": "fr-FR", "French (Switzerland)": "fr-CH",
    }),
    ("Galician", {"Galician": "gl-ES"}),
    ("Georgian", {"Georgian (Georgia)": "ka-GE"}),
    ("German", {
        "German (Austria)": "de-AT", "German (Germany)": "de-DE",
        "German (Switzerland)": "de-CH",
    }),
    ("Greek", {"Greek (Greece)": "el-GR"}),
    ("Gujarati", {"Gujarati (India)": "gu-IN"}),
    ("Hebrew", {"Hebrew (Israel)": "he-IL"}),
    ("Hindi", {"Hindi (India)": "hi-IN"}),
    ("Hungarian", {"Hungarian (Hungary)": "hu-HU"}),
    ("Icelandic", {"Icelandic (Iceland)": "is-IS"}),
    ("Indonesian", {"Indonesian (Indonesia)": "id-ID"}),
    ("Irish", {"Irish (Ireland)": "ga-IE"}),
    ("Italian", {"Italian (Italy)": "it-IT", "Italian (Switzerland)": "it-CH"}),
    ("Japanese", {"Japanese (Japan)": "ja-JP"}),
    ("Javanese", {"Javanese (Latin, Indonesia)": "jv-ID"}),
    ("Kannada", {"Kannada (India)": "kn-IN"}),
    ("Kazakh", {"Kazakh (Kazakhstan)": "kk-KZ"}),
    ("Khmer", {"Khmer (Cambodia)": "km-KH"}),
    ("Kiswahili", {"Kiswahili (Kenya)": "sw-KE", "Kiswahili (Tanzania)": "sw-TZ"}),
    ("Korean", {"Korean (Korea)": "ko-KR"}),
    ("Lao", {"Lao (Laos)": "lo-LA"}),
    ("Latvian", {"Latvian (Latvia)": "lv-LV"}),
    ("Lithuanian", {"Lithuanian (Lithuania)": "lt-LT"}),
    ("Macedonian", {"Macedonian (North Macedonia)": "mk-MK"}),
    ("Malay", {"Malay (Malaysia)": "ms-MY"}),
    ("Malayalam", {"Malayalam (India)": "ml-IN"}),
    ("Maltese", {"Maltese (Malta)": "mt-MT"}),
    ("Marathi", {"Marathi (India)": "mr-IN"}),
    ("Mongolian", {"Mongolian (Mongolia)": "mn-MN"}),
    ("Nepali", {"Nepali (Nepal)": "ne-NP"}),
    ("Norwegian", {"Norwegian Bokmal (Norway)": "nb-NO"}),
    ("Odia", {"Odia (India)": "or-IN"}),
    ("Pashto", {"Pashto (Afghanistan)": "ps-AF"}),
    ("Persian", {"Persian (Iran)": "fa-IR"}),
    ("Polish", {"Polish (Poland)": "pl-PL"}),
    ("Portuguese", {"Portuguese (Brazil)": "pt-BR", "Portuguese (Portugal)": "pt-PT"}),
    ("Punjabi", {"Punjabi (India)": "pa-IN"}),
    ("Romanian", {"Romanian (Romania)": "ro-RO"}),
    ("Russian", {"Russian (Russia)": "ru-RU"}),
    ("Serbian", {
        "Serbian (Cyrillic, Serbia)": "sr-RS", "Serbian (Kosovo)": "sr-XK",
        "Serbian (Montenegro)": "sr-ME",
    }),
    ("Sinhala", {"Sinhala (Sri Lanka)": "si-LK"}),
    ("Slovak", {"Slovak (Slovakia)": "sk-SK"}),
    ("Slovenian", {"Slovenian (Slovenia)": "sl-SI"}),
    ("Somali", {"Somali (Somalia)": "so-SO"}),
    ("Spanish", {
        "Spanish (Argentina)": "es-AR", "Spanish (Bolivia)": "es-BO",
        "Spanish (Chile)": "es-CL", "Spanish (Colombia)": "es-CO",
        "Spanish (Costa Rica)": "es-CR", "Spanish (Cuba)": "es-CU",
        "Spanish (Dominican Republic)": "es-DO", "Spanish (Ecuador)": "es-EC",
        "Spanish (El Salvador)": "es-SV", "Spanish (Equatorial Guinea)": "es-GQ",
        "Spanish (Guatemala)": "es-GT", "Spanish (Honduras)": "es-HN",
        "Spanish (Mexico)": "es-MX", "Spanish (Nicaragua)": "es-NI",
        "Spanish (Panama)": "es-PA", "Spanish (Paraguay)": "es-PY",
        "Spanish (Peru)": "es-PE", "Spanish (Puerto Rico)": "es-PR",
        "Spanish (Spain)": "es-ES", "Spanish (United States)": "es-US",
        "Spanish (Uruguay)": "es-UY", "Spanish (Venezuela)": "es-VE",
    }),
    ("Swedish", {"Swedish (Sweden)": "sv-SE"}),
    ("Tamil", {"Tamil (India)": "ta-IN"}),
    ("Telugu", {"Telugu (India)": "te-IN"}),
    ("Thai", {"Thai (Thailand)": "th-TH"}),
    ("Turkish", {"Turkish (Turkiye)": "tr-TR"}),
    ("Ukrainian", {"Ukrainian (Ukraine)": "uk-UA"}),
    ("Urdu", {"Urdu (India)": "ur-IN"}),
    ("Uzbek", {"Uzbek (Latin, Uzbekistan)": "uz-UZ"}),
    ("Vietnamese", {"Vietnamese (Vietnam)": "vi-VN"}),
    ("Welsh", {"Welsh (United Kingdom)": "cy-GB"}),
    ("Zulu", {"isiZulu (South Africa)": "zu-ZA"}),
]

INPUT_LANGUAGES = {}
for _group_name, _options in INPUT_LANGUAGE_GROUPS:
    INPUT_LANGUAGES.update(_options)

OUTPUT_LANGUAGES = {
    "No translation (send as heard)": "none",
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese (Simplified)": "zh-Hans",
    "Portuguese": "pt",
    "Italian": "it",
    "Russian": "ru",
}

PROFANITY_WORDLIST = [
    "damn", "hell", "shit", "fuck", "fucking", "bitch", "ass", "asshole",
    "crap", "bastard", "dick", "piss",
]

DEFAULT_PREFS = {
    "device_name": None,
    "speech_service": "azure",
    "input_language": "en-US",
    "output_language": "none",
    # Remembers the last language picked FOR EACH service, so switching
    # from Azure to Whisper and back doesn't lose either one's choice --
    # "input_language"/"output_language" above always reflect whichever
    # service is currently active; these two are the per-service memory
    # behind that.
    "input_language_by_service": {},
    "output_language_by_service": {},
    "uwu_enabled": False,
    "profanity_allowed": False,
    "persona_enabled": False,
    "persona_style": "",
    "keep_alive_enabled": True,
    "custom_background_path": "",
    "custom_tiny_background_path": "",
    "text_color": "",
    "text_font_family": "",
    "osc_port": VRCHAT_PORT,
    "custom_endpoint_id": "",
    "hotkey_enabled": False,
    "hotkey_mode": "toggle",
    "hotkey_input_type": "keyboard",
    "hotkey_key": "f9",
    "hotkey_vr_combo": [],
    "overlay_mode_enabled": False,
    # Google Cloud Speech-to-Text
    "google_credentials_path": "",
    # AWS Transcribe
    "aws_access_key": "",
    "aws_secret_key": "",
    "aws_region": "",
    # Whisper (local)
    "whisper_model_size": "base",
    "whisper_device": "cpu",
    # Vosk (local)
    "vosk_model_path": "",
}

# Maps a (service, field) pair from Config's UI straight to its prefs
# key, for save_speech_field below -- raw, untested field values (a
# key half-typed, a path just browsed to) that get remembered the
# instant they're entered rather than only on a successful "Save X
# Settings" test, so switching the Speech Service dropdown away and
# back, or just closing Config, never throws away what you were in the
# middle of filling in. Azure isn't in here on purpose -- its key/
# region live in .env via a different mechanism (save_env_values),
# not prefs.json, and that's an existing, unrelated pattern this isn't
# reaching into.
# Which .md file (living right next to main.py, same as AZURE_SETUP.md
# always has) backs each engine's "View Setup Guide" button in Config,
# and what to title the window it opens in. A dict lookup rather than
# trusting a raw filename from JS -- the six values here are the only
# ones that can ever come back out of get_setup_guide/open_setup_guide.
SETUP_GUIDES = {
    "azure": ("AZURE_SETUP.md", "Azure Setup"),
    "google": ("GOOGLE_SETUP.md", "Google Cloud Setup"),
    "aws": ("AWS_SETUP.md", "AWS Setup"),
    "whisper": ("WHISPER_SETUP.md", "Whisper Setup"),
    "vosk": ("VOSK_SETUP.md", "Vosk Setup"),
    "windows": ("WINDOWS_SPEECH_SETUP.md", "Windows Speech Setup"),
}

SPEECH_FIELD_PREF_KEYS = {
    ("google", "credentials_path"): "google_credentials_path",
    ("aws", "access_key"): "aws_access_key",
    ("aws", "secret_key"): "aws_secret_key",
    ("aws", "region"): "aws_region",
    ("whisper", "model_size"): "whisper_model_size",
    ("whisper", "device"): "whisper_device",
    ("vosk", "model_path"): "vosk_model_path",
}


def load_prefs():
    if os.path.exists(PREFS_FILE):
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = DEFAULT_PREFS.copy()
            merged.update(data)
            return merged
        except Exception:
            pass
    return DEFAULT_PREFS.copy()


def save_prefs(prefs):
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def save_env_values(key, region):
    env_path = os.path.join(get_app_dir(), ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    def set_line(var_name, value):
        prefix = f"{var_name}="
        for i, line in enumerate(lines):
            if line.strip().startswith(prefix):
                lines[i] = f"{prefix}{value}\n"
                return
        lines.append(f"{prefix}{value}\n")

    set_line("AZURE_SPEECH_KEY", key)
    set_line("AZURE_SPEECH_REGION", region)
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def test_azure_credentials(key, region):
    """Quick, real connectivity check against Azure - requests an auth
    token, which fails fast on a bad key/region. Test the door before
    you trust it's unlocked."""
    url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    req = urllib.request.Request(
        url, method="POST",
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                return True, None
            return False, f"Azure returned an unexpected response (HTTP {resp.status})."
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "Azure rejected this key - double check the key and region."
        return False, f"Azure returned an error (HTTP {e.code})."
    except urllib.error.URLError as e:
        return False, f"Couldn't reach Azure: {e.reason}"
    except Exception as e:
        return False, f"Connection test failed: {e}"


def parse_hotkey(key_str):
    """Turns a user-typed key name into a pynput Key or KeyCode object.
    Returns (key_object, error_message) - error_message is None on
    success. Accepts special key names (f1-f24, space, tab, enter, esc,
    shift, ctrl_l, etc. - anything pynput.keyboard.Key knows about) and
    single characters (a, 1, ,, etc)."""
    if key_str is None:
        return None, "Please enter a key."
    key_str = key_str.strip().lower()
    if not key_str:
        return None, "Please enter a key."

    if hasattr(keyboard.Key, key_str):
        return getattr(keyboard.Key, key_str), None

    if len(key_str) == 1:
        return keyboard.KeyCode.from_char(key_str), None

    return None, (
        f"'{key_str}' isn't a recognized key. Try a single character "
        "(a, 1, ,) or a special key name (f9, space, tab, enter, esc)."
    )


def describe_key(key_str):
    """Human-friendly display form of a stored key string, e.g. 'f9' ->
    'F9', 'a' -> 'A', 'space' -> 'Space'."""
    if not key_str:
        return ""
    if len(key_str) == 1:
        return key_str.upper()
    return key_str.replace("_", " ").title()


def label_for_code(mapping, code, default_label):
    for label, value in mapping.items():
        if value == code:
            return label
    return default_label


def flatten_languages(languages):
    """An engine's input_languages() comes back either grouped (Azure/
    Google/AWS -- [(group_name, {label: code})]) or flat (Whisper/Vosk/
    Windows -- {label: code}), since only the dialect-granular services
    actually have groups worth showing. This is the one place that
    difference gets collapsed back into a plain {label: code} lookup,
    for label_for_code() and for turning a picked label into a code."""
    if isinstance(languages, dict):
        return dict(languages)
    flat = {}
    for _group_name, options in languages:
        flat.update(options)
    return flat


def language_groups_for_json(languages):
    """The frontend always renders input-language options as a list of
    {group, options} objects, even for engines with no real groups --
    a flat dict just becomes one group with an empty name, same select
    element either way, no special-casing needed in app.js."""
    if isinstance(languages, dict):
        return [{"group": "", "options": list(languages.keys())}]
    return [{"group": group_name, "options": list(options.keys())} for group_name, options in languages]


# Raw OpenVR button-bit -> display name. Several controllers share the
# same underlying bit for physically different buttons - most notably,
# on Valve Index controllers, "A" and "B" aren't separate bits at all;
# they alias onto Grip (bit 2) and ApplicationMenu (bit 1) respectively
# (confirmed directly against the installed openvr package:
# k_EButton_IndexController_A == k_EButton_Grip == 2). Showing both
# possible names side by side is more honest than confidently picking
# one that might be wrong for the controller actually in someone's hand.
VR_BUTTON_DISPLAY_NAMES = {
    0: "System",
    1: "Menu / B (Index)",
    2: "Grip / A (Index)",
    3: "D-Pad Left",
    4: "D-Pad Up",
    5: "D-Pad Right",
    6: "D-Pad Down",
    7: "A (Touch-style)",
    31: "Proximity Sensor",
    32: "Trackpad",
    33: "Trigger",
    34: "Axis 2",
    35: "Joystick (Index) / Axis 3",
    36: "Axis 4",
}


def vr_identifier_to_label(identifier):
    """'left:33' -> 'Left Trigger'. Falls back to the raw identifier if
    it's not in the expected hand:bit form."""
    try:
        hand, bit_str = identifier.split(":")
        bit = int(bit_str)
    except (ValueError, AttributeError):
        return identifier
    hand_label = {"left": "Left", "right": "Right"}.get(hand, hand.title())
    button_label = VR_BUTTON_DISPLAY_NAMES.get(bit, f"Button {bit}")
    return f"{hand_label} {button_label}"


class VRControllerMonitor:
    """Polls SteamVR (via OpenVR's controller-state API) for button
    presses on both hand controllers. Used both for live hotkey
    detection (is the saved combo currently fully held down?) and for
    the "press your combo now" capture flow in Config. Presence,
    checked by hand -- literally.

    Deliberately uses the older getControllerState() API rather than
    the newer IVRInput action system - IVRInput requires generating
    and registering a JSON action manifest with SteamVR ahead of time,
    which fits a "here's a fixed set of actions my app supports" model
    far worse than a simple "hold down whatever buttons you want and
    we detect them" capture flow.
    """

    def __init__(self):
        self._vr_system = None
        self._initialized = False

    def ensure_initialized(self):
        """Returns (ok, error_message). error_message is None on success."""
        if self._initialized:
            return True, None
        if not OPENVR_MODULE_AVAILABLE:
            return False, ("VR controller support needs the 'openvr' package. "
                            "Run: pip install openvr")
        try:
            self._vr_system = openvr.init(openvr.VRApplication_Background)
            self._initialized = True
            return True, None
        except Exception as e:
            detail = str(e).strip() or type(e).__name__
            return False, f"Couldn't connect to SteamVR ({detail}). Is SteamVR running?"

    def shutdown(self):
        if self._initialized:
            try:
                openvr.shutdown()
            except Exception:
                pass
            self._initialized = False
            self._vr_system = None

    def poll_pressed(self):
        """Returns a set of 'hand:bit' identifiers for every button
        currently held down across both connected controllers. Returns
        an empty set if nothing is pressed or no controllers are
        connected - callers should check ensure_initialized() first to
        distinguish "nothing pressed" from "VR isn't available"."""
        pressed = set()
        if not self._initialized:
            return pressed
        for hand, role in (
            ("left", openvr.TrackedControllerRole_LeftHand),
            ("right", openvr.TrackedControllerRole_RightHand),
        ):
            try:
                device_index = self._vr_system.getTrackedDeviceIndexForControllerRole(role)
                if device_index == openvr.k_unTrackedDeviceIndexInvalid:
                    continue
                if not self._vr_system.isTrackedDeviceConnected(device_index):
                    continue
                success, state = self._vr_system.getControllerState(device_index)
                if not success:
                    continue
                for bit in range(64):
                    if state.ulButtonPressed & (1 << bit):
                        pressed.add(f"{hand}:{bit}")
            except Exception:
                continue
        return pressed


def uwuify(text):
    text = re.sub(r"[rl]", "w", text)
    text = re.sub(r"[RL]", "W", text)
    text = re.sub(r"n([aeiou])", r"ny\1", text)
    text = re.sub(r"N([aeiouAEIOU])", r"Ny\1", text)
    if random.random() < 0.4:
        text += random.choice([" uwu", " owo", " >w<", " ~"])
    return text


def censor_profanity(text):
    pattern = r"\b(" + "|".join(PROFANITY_WORDLIST) + r")\b"

    def _mask(match):
        word = match.group(0)
        if len(word) <= 2:
            return word[0] + "*"
        return word[0] + "*" * (len(word) - 2) + word[-1]

    return re.sub(pattern, _mask, text, flags=re.IGNORECASE)


def _persona_robot(text):
    text = "-".join(text.upper().split())
    if random.random() < 0.5:
        text += ". BEEP BOOP"
    return text


_GLITCH_LEET_MAP = {"A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7"}
_GLITCH_TOKENS = ["#ERR", "//STATIC//", "[SIGNAL LOST]", "0x00", "◈◈◈"]


def _persona_glitch(text):
    text = text.upper()
    text = "".join(
        _GLITCH_LEET_MAP[ch] if ch in _GLITCH_LEET_MAP and random.random() < 0.6 else ch
        for ch in text
    )
    if random.random() < 0.3:
        text += f" {random.choice(_GLITCH_TOKENS)}"
    if random.random() < 0.5:
        text += ". BEEP BOOP"
    return text


def _persona_cat(text):
    text = re.sub(r"\bhello\b", "mrrp", text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text += " meow~"
    elif random.random() < 0.3:
        text += " nya~"
    return text


def _persona_pirate(text):
    replacements = {
        "my": "me", "you": "ye", "your": "yer", "is": "be",
        "hello": "ahoy", "friend": "matey", "yes": "aye", "no": "nay",
    }
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.4:
        text += ", arrr!"
    return text


def _persona_lisp(text):
    text = re.sub(r"s", "th", text)
    text = re.sub(r"S", "Th", text)
    text = re.sub(r"z", "th", text)
    text = re.sub(r"Z", "Th", text)
    if random.random() < 0.3:
        text += ", ith that tho?"
    return text


_SHAKESPEARE_FLOURISHES = [", forsooth!", ", good sir!", ", i say!", ", methinks!"]


def _persona_shakespeare(text):
    replacements = {
        "you": "thou", "your": "thy", "are": "art", "have": "hath",
        "do": "doth", "my": "mine", "hello": "hark", "yes": "aye",
        "no": "nay", "friend": "good friend", "great": "wondrous",
        "very": "most",
    }
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text += random.choice(_SHAKESPEARE_FLOURISHES)
    return text


def _persona_valley_girl(text):
    if random.random() < 0.5:
        text = random.choice(["like ", "um, ", "okay so "]) + text
    if random.random() < 0.4:
        text += ", like, oh my god"
    return text


def _persona_dog(text):
    text = re.sub(r"\bhello\b", "*happy bark*", text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text += " woof!"
    elif random.random() < 0.3:
        text += " *wags tail*"
    return text


def _persona_surfer(text):
    replacements = {
        "very": "totally", "great": "gnarly", "friend": "dude",
        "yes": "totally", "hello": "yo",
    }
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.4:
        text += ", brah"
    return text


def _persona_drill_sergeant(text):
    text = text.upper()
    if not text.endswith(("!", ".")):
        text += "!"
    text += " " + random.choice(["SIR!", "MOVE IT!", "DROP AND GIVE ME TWENTY!"])
    return text


_RADIO_PREFIXES = [
    "Ladies and gentlemen... ", "Live, from wherever you are... ",
    "Coming to you loud and clear... ",
]


def _persona_radio_announcer(text):
    # One random word gets boomed up to full announcer volume.
    words = text.split()
    if words and random.random() < 0.4:
        i = random.randrange(len(words))
        words[i] = words[i].upper()
    text = " ".join(words)
    if random.random() < 0.5:
        text = random.choice(_RADIO_PREFIXES) + text
    if random.random() < 0.3:
        text += "... I say again, " + text.lower()
    return text


def _persona_cowboy(text):
    replacements = {
        "hello": "howdy", "friend": "partner", "you": "y'all",
        "think": "reckon", "yes": "yessiree",
    }
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.4:
        text += ", partner"
    return text


def _persona_wizard(text):
    replacements = {
        "hello": "hark", "yes": "verily", "friend": "apprentice",
        "magic": "arcane magic",
    }
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.3:
        text += " *waves wand*"
    elif random.random() < 0.2:
        text += ", by my beard!"
    return text


def _persona_sleepy(text):
    text = text + "..."
    if random.random() < 0.5:
        text += " *yawn*"
    elif random.random() < 0.3:
        text += " zzz"
    return text


_CONSPIRACY_REPLACEMENTS = {"coincidence": "\"coincidence\"", "government": "THE GOVERNMENT", "they": "THEY"}
_CONSPIRACY_PREFIXES = ["they don't want you to know this, but ", "wake up... ", "open your eyes: "]
_CONSPIRACY_SUFFIXES = [
    "...connect the dots.", "...do your own research.",
    "...they're always watching.", "...it's all connected.",
]


def _persona_conspiracy(text):
    for word, sub in _CONSPIRACY_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    text = random.choice(_CONSPIRACY_PREFIXES) + text
    if random.random() < 0.5:
        text += " " + random.choice(_CONSPIRACY_SUFFIXES)
    return text


def _persona_anime(text):
    text = text.rstrip(".") + "!!"
    if random.random() < 0.4:
        text += " Believe it!"
    elif random.random() < 0.3:
        text += " Nyahaha!"
    return text


_GHOST_MOANS = ["...woooo...", "...I am watching you...", "*rattles chains*", "...boooo..."]


def _persona_ghost(text):
    text = re.sub(r"\bhello\b", "h-e-l-l-o...", text, flags=re.IGNORECASE)
    # Spell out one random word letter-by-letter, like a voice wavering
    # in and out of this plane of existence.
    words = text.split()
    if words and random.random() < 0.4:
        i = random.randrange(len(words))
        words[i] = "-".join(words[i])
    text = " ".join(words)
    if random.random() < 0.3:
        text = "*a chill runs down your spine*... " + text
    if random.random() < 0.6:
        text += " " + random.choice(_GHOST_MOANS)
    return text


_VAMPIRE_FLOURISHES = ["... I vant to drink your blood!", "... bleh bleh bleh!", ", mortal. 🦇"]


def _persona_vampire(text):
    replacements = {"friend": "mortal", "hello": "good evening"}
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    # The classic Dracula-accent swap, worn like a cape.
    text = re.sub(r"w", "v", text)
    text = re.sub(r"W", "V", text)
    # One vowel in a random word gets drawn out long, for the pause.
    words = text.split()
    if words:
        i = random.randrange(len(words))
        words[i] = re.sub(r"([aeiouAEIOU])", r"\1\1", words[i], count=1)
    text = " ".join(words)
    if random.random() < 0.4:
        text += random.choice(_VAMPIRE_FLOURISHES)
    return text


_NOIR_REPLACEMENTS = {"very": "real", "secret": "dirty little secret", "money": "dirty money"}
_NOIR_PREFIXES = [
    "It was a dark and stormy night... ", "The city never sleeps, and neither do I. ",
    "Rain hammered the window as I said, ",
]
_NOIR_SUFFIXES = [", see.", ", and that's the dirty truth.", "... just another case in this rotten city."]


def _persona_noir_detective(text):
    for word, sub in _NOIR_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.35:
        text = random.choice(_NOIR_PREFIXES) + text
    if random.random() < 0.45:
        text += random.choice(_NOIR_SUFFIXES)
    return text


_FAIRY_FLOURISHES = ["*sprinkles fairy dust*", "*flutters wings*", "*tiny giggle*", "~*~"]


def _persona_fairy(text):
    replacements = {"friend": "dear one", "yes": "'tis so", "hello": "well met"}
    for word, sub in replacements.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    # One random word gets wrapped in tildes, a sing-song little lilt.
    words = text.split()
    if words and random.random() < 0.5:
        i = random.randrange(len(words))
        words[i] = f"~{words[i]}~"
    text = " ".join(words)
    if random.random() < 0.3:
        text = "tra-la-la, " + text
    if random.random() < 0.5:
        text += " " + random.choice(_FAIRY_FLOURISHES)
    return text


_GRUMPY_REPLACEMENTS = {
    "phone": "contraption", "internet": "newfangled internet",
    "you": "you whippersnappers", "computer": "confounded machine",
}
_GRUMPY_SUFFIXES = [
    "...bah humbug.", "...kids these days.", "...get off my lawn!",
    "...back in my day we didn't complain.",
]


def _persona_grumpy_old_man(text):
    for word, sub in _GRUMPY_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text = "back in my day, " + text
    if random.random() < 0.5:
        text += " " + random.choice(_GRUMPY_SUFFIXES)
    return text


def _persona_auctioneer(text):
    text = "-".join(text.split())
    text += "-going-once-going-twice-SOLD!"
    return text


_NEWS_REPLACEMENTS = {"said": "reportedly said", "true": "allegedly true"}
_NEWS_PREFIXES = ["This just in: ", "Breaking news: ", "In other news: "]
_NEWS_SUFFIXES = [". Back to you in the studio.", ". More at 11.", ". Stay tuned."]


def _persona_newscaster(text):
    for word, sub in _NEWS_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text = random.choice(_NEWS_PREFIXES) + text
    if random.random() < 0.35:
        text += random.choice(_NEWS_SUFFIXES)
    return text


_VILLAIN_REPLACEMENTS = {
    "friend": "foolish mortal", "hello": "greetings", "plan": "master plan",
    "good": "pathetic good",
}
_VILLAIN_SUFFIXES = ["Mwahaha!", "Soon, all will be MINE!", "Excellent...", "You cannot stop me now!"]


def _persona_villain(text):
    for word, sub in _VILLAIN_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.5:
        text += "... " + random.choice(_VILLAIN_SUFFIXES)
    return text


def _persona_motivational_speaker(text):
    if random.random() < 0.5:
        text = text.upper()
    if random.random() < 0.4:
        text += "! YOU'VE GOT THIS, CHAMPION!"
    return text


_ZOMBIE_SUFFIXES = ["...braaains...", "...must feeeed...", "*shuffles closer*", "...unnngh..."]


def _persona_zombie(text):
    text = re.sub(r"\bhello\b", "braaains", text, flags=re.IGNORECASE)
    # Drag out a vowel in a few random words for a moaning drawl that
    # runs through the whole sentence, not just a tacked-on groan.
    words = text.split()
    for i, word in enumerate(words):
        if random.random() < 0.3:
            words[i] = re.sub(r"([aeiouAEIOU])", r"\1\1\1", word, count=1)
    text = " ".join(words)
    if random.random() < 0.6:
        text += " " + random.choice(_ZOMBIE_SUFFIXES)
    return text


_ALIEN_REPLACEMENTS = {
    "hello": "greetings, Earthling", "friend": "Earth-being",
    "food": "Earth sustenance", "music": "Earth noise-ritual",
}
_ALIEN_PREFIXES = ["*translator device whirs* ", "Greetings, Earthling. "]
_ALIEN_SUFFIXES = [
    "Take me to your leader.", "Resistance is illogical.",
    "*blorp blorp*", "Your primitive customs intrigue me.",
]


def _persona_alien(text):
    for word, sub in _ALIEN_REPLACEMENTS.items():
        text = re.sub(rf"\b{word}\b", sub, text, flags=re.IGNORECASE)
    if random.random() < 0.3:
        text = random.choice(_ALIEN_PREFIXES) + text
    if random.random() < 0.4:
        text += ". " + random.choice(_ALIEN_SUFFIXES)
    return text


PERSONA_STYLES = {
    "robot": _persona_robot, "glitch": _persona_glitch, "cat": _persona_cat, "dog": _persona_dog,
    "pirate": _persona_pirate, "lisp": _persona_lisp,
    "shakespeare": _persona_shakespeare, "valley_girl": _persona_valley_girl,
    "surfer": _persona_surfer, "drill_sergeant": _persona_drill_sergeant,
    "radio_announcer": _persona_radio_announcer, "cowboy": _persona_cowboy,
    "wizard": _persona_wizard, "sleepy": _persona_sleepy,
    "conspiracy": _persona_conspiracy, "anime": _persona_anime,
    "ghost": _persona_ghost, "vampire": _persona_vampire,
    "noir_detective": _persona_noir_detective, "fairy": _persona_fairy,
    "grumpy_old_man": _persona_grumpy_old_man, "auctioneer": _persona_auctioneer,
    "newscaster": _persona_newscaster, "villain": _persona_villain,
    "motivational_speaker": _persona_motivational_speaker, "zombie": _persona_zombie,
    "alien": _persona_alien,
}

PERSONA_LABELS = {
    "None": "", "Robot": "robot", "GL17CH": "glitch", "Cat": "cat", "Dog": "dog", "Pirate": "pirate",
    "Lisp": "lisp", "Shakespeare": "shakespeare", "Valley Girl": "valley_girl",
    "Surfer": "surfer", "Drill Sergeant": "drill_sergeant",
    "Radio Announcer": "radio_announcer", "Cowboy": "cowboy", "Wizard": "wizard",
    "Sleepy": "sleepy", "Conspiracy Theorist": "conspiracy",
    "Anime Protagonist": "anime", "Ghost": "ghost", "Vampire": "vampire",
    "Noir Detective": "noir_detective", "Fairy": "fairy",
    "Grumpy Old Man": "grumpy_old_man", "Auctioneer": "auctioneer",
    "Newscaster": "newscaster", "Villain": "villain",
    "Motivational Speaker": "motivational_speaker", "Zombie": "zombie",
    "Alien": "alien",
}


def resample_pcm16(data_bytes, orig_sr, target_sr):
    if orig_sr == target_sr or len(data_bytes) == 0:
        return data_bytes
    audio = np.frombuffer(data_bytes, dtype=np.int16)
    duration = len(audio) / orig_sr
    target_len = max(1, int(duration * target_sr))
    orig_idx = np.linspace(0, len(audio) - 1, num=len(audio))
    target_idx = np.linspace(0, len(audio) - 1, num=target_len)
    resampled = np.interp(target_idx, orig_idx, audio).astype(np.int16)
    return resampled.tobytes()


def open_mic_stream(device_index, callback):
    device_info = sd.query_devices(device_index)
    preferred_rate = int(device_info["default_samplerate"]) or 48000
    attempts = [
        (preferred_rate, 1),
        (preferred_rate, min(2, device_info["max_input_channels"])),
        (44100, 1),
        (48000, 1),
    ]
    last_error = None
    for samplerate, channels in attempts:
        if channels < 1:
            continue
        try:
            stream = sd.RawInputStream(
                samplerate=samplerate, blocksize=0, device=device_index,
                channels=channels, dtype="int16", callback=callback,
            )
            return stream, samplerate, channels
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Couldn't open this microphone with any known settings: {last_error}")


def start_local_server(root_dir):
    """Serves the app's own folder over plain HTTP on localhost, so
    relative asset paths and background-image URLs behave exactly the
    same way they would on a real website - same approach as before,
    unrelated to the pywebview-specific bug this rewrite fixes. A
    small, quiet room the app can always find its own way back to."""
    class QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            # THE real bug behind the "ERR_EMPTY_RESPONSE on every
            # single page load" report, once the trail was finally
            # followed all the way down: the default implementation
            # writes straight to sys.stderr, which is flat-out None in
            # a console=False build launched by double-click. That
            # raised AttributeError on EVERY request, before a single
            # byte of the response ever went out -- exactly what an
            # empty response looks like from the browser's side of the
            # window. _safe_print instead of sys.stderr.write directly.
            _safe_print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

    handler = functools.partial(QuietRequestHandler, directory=root_dir)

    class QuietServer(socketserver.TCPServer):
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            # "Quiet" used to mean "swallow the traceback entirely" (this
            # printed to a console window that a console=False build
            # doesn't even have, so it was never actually reaching
            # anyone) -- now it means "handle it without crashing the
            # server thread AND leave a real trail," since a page load
            # failing with no clue why is worse than a log file existing.
            try:
                log_path = os.path.join(root_dir, "server_error.log")
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} "
                            f"from {client_address} ---\n")
                    traceback.print_exc(file=f)
            except OSError:
                pass  # can't write the log either -- nothing more to do about it

    httpd = QuietServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return port, httpd


class Bridge(QObject):
    """Exposed to JS via QWebChannel as `bridge`. Owns all app state and
    the Azure/mic/OSC pipeline. Pushes updates to the UI via pushSignal,
    which the JS side listens to directly - Qt handles the actual
    message transport, no manual evaluate_js string-building needed.
    The heart of the whole thing, quietly doing the work underneath."""

    pushSignal = Signal(str, str)  # event name, JSON-encoded payload

    def __init__(self):
        super().__init__()
        self.prefs = load_prefs()
        self.main_window = None
        self.config_window = None
        self.about_window = None
        self.guide_window = None
        self.base_url = None
        self.httpd = None
        self.pipeline = {}
        self.state = {
            "active": False, "restarting": False, "expect_disconnect": False,
            "shutting_down": False, "tiny_mode": False, "connected": False,
        }
        self.uwu_enabled = self.prefs["uwu_enabled"]
        self.profanity_allowed = self.prefs["profanity_allowed"]
        self.persona_enabled = self.prefs["persona_enabled"]
        self.persona_style_key = self.prefs["persona_style"]
        self.keep_alive_enabled = self.prefs["keep_alive_enabled"]
        self.overlay_mode_enabled = self.prefs["overlay_mode_enabled"]
        self.speech_service = self.prefs.get("speech_service", "azure")
        self._engines = self._build_engines()
        self.device_index = None
        self.device_name = None
        self.osc_client = SimpleUDPClient(VRCHAT_IP, self.prefs.get("osc_port", VRCHAT_PORT))
        self._toggle_key_down = False
        self._hotkey_listener = None
        self._vr_monitor = VRControllerMonitor()
        self._vr_hotkey_stop_event = None
        self._vr_capture_active = False
        self._last_tx_time = 0.0
        self._last_rx_time = 0.0
        self._last_connection_refresh_time = 0.0
        self._last_heartbeat_push_time = 0.0
        self._keep_alive_timer = QTimer()
        self._keep_alive_timer.timeout.connect(self._keep_alive_tick)
        self._keep_alive_timer.start(ACTIVITY_LIGHT_CHECK_MS)

    def _build_engines(self):
        """One instance of every engine, built once at startup. Cheap --
        constructing an engine object doesn't load a model or open a
        connection, that only happens in start()/test_connection().
        Every getter closure below reads self.prefs fresh each call
        rather than capturing a value, so a Config change takes effect
        immediately without rebuilding this dict."""
        return {
            "azure": speech_engines.AzureEngine(
                get_key_region=lambda: (AZURE_SPEECH_KEY, AZURE_SPEECH_REGION),
                input_language_groups=INPUT_LANGUAGE_GROUPS,
                output_languages=OUTPUT_LANGUAGES,
            ),
            "google": speech_engines.GoogleEngine(
                get_credentials_path=lambda: self.prefs.get("google_credentials_path", ""),
            ),
            "aws": speech_engines.AWSEngine(
                get_credentials=lambda: (
                    self.prefs.get("aws_access_key", ""),
                    self.prefs.get("aws_secret_key", ""),
                    self.prefs.get("aws_region", ""),
                ),
            ),
            "whisper": speech_engines.WhisperEngine(
                get_config=lambda: {
                    "model_size": self.prefs.get("whisper_model_size", "base"),
                    "device": self.prefs.get("whisper_device", "cpu"),
                },
            ),
            "vosk": speech_engines.VoskEngine(
                get_model_path=lambda: self.prefs.get("vosk_model_path", ""),
            ),
            "windows": speech_engines.WindowsEngine(),
        }

    def _current_engine(self):
        return self._engines[self.speech_service]

    # ---- pushing state to the UI ----
    def push(self, event, payload=None):
        try:
            self.pushSignal.emit(event, json.dumps(payload))
        except Exception:
            pass

    def log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        _safe_print(line)
        self.push("log", line)

    # ---- initial state for the UI to hydrate itself with ----
    @Slot(result=str)
    def get_state(self):
        engine = self._current_engine()
        input_map = flatten_languages(engine.input_languages())
        output_map = engine.output_languages()
        state = {
            "app_name": APP_NAME,
            "speech_service": self.speech_service,
            "input_language_groups": language_groups_for_json(engine.input_languages()),
            "output_languages": list(output_map.keys()),
            "persona_labels": list(PERSONA_LABELS.keys()),
            "input_language": label_for_code(input_map, self.prefs["input_language"], ""),
            "output_language": label_for_code(
                output_map, self.prefs["output_language"], "No translation (send as heard)"
            ),
            "supports_translation": engine.supports_translation,
            "supports_keep_alive": engine.supports_keep_alive,
            "persona_style": label_for_code(PERSONA_LABELS, self.persona_style_key, "None"),
            "uwu_enabled": self.uwu_enabled,
            "profanity_allowed": self.profanity_allowed,
            "persona_enabled": self.persona_enabled,
            "keep_alive_enabled": self.keep_alive_enabled,
            "overlay_mode_enabled": self.overlay_mode_enabled,
            "hotkey_enabled": self.prefs.get("hotkey_enabled", False),
            "hotkey": (
                " + ".join(vr_identifier_to_label(b) for b in sorted(self.prefs.get("hotkey_vr_combo", [])))
                if self.prefs.get("hotkey_input_type") == "vr_controller"
                else describe_key(self.prefs.get("hotkey_key", "f9"))
            ),
            "mode": self.prefs.get("hotkey_mode", "toggle"),
            "copyright_text": COPYRIGHT_TEXT,
            "text_color": self.prefs.get("text_color") or "",
            "text_font_family": self.prefs.get("text_font_family") or "",
            "main_background": self._background_data_uri(self.prefs.get("custom_background_path") or self._default_asset("background.png")),
            "tiny_background": self._background_data_uri(self.prefs.get("custom_tiny_background_path") or self._default_asset("tiny_background.png")),
        }
        return json.dumps(state)

    def _default_asset(self, name):
        return os.path.join(get_app_dir(), "assets", name)

    def _background_data_uri(self, path):
        if not path or not os.path.exists(path):
            return ""
        try:
            import base64
            ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return f"data:image/{ext};base64,{b64}"
        except Exception as e:
            self.log(f"Couldn't load image ({path}): {e}")
            return ""

    def _get_devices_list(self):
        try:
            return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        except Exception as e:
            self.log(f"Couldn't list input devices: {e}")
            return []

    @Slot(result=str)
    def get_devices(self):
        return json.dumps(self._get_devices_list())

    # ---- mic + speech-engine pipeline ----
    def _shared_audio_callback(self, indata, frames, time_info, status):
        if not self.state["active"]:
            return
        data = np.frombuffer(bytes(indata), dtype=np.int16)
        mf = self.pipeline["mic_format"]
        if mf["channels"] > 1:
            data = data.reshape(-1, mf["channels"]).mean(axis=1).astype(np.int16)
        resampled = resample_pcm16(data.tobytes(), mf["samplerate"], SAMPLE_RATE)
        # Never called for engines that manage their own mic input
        # (Windows Speech Recognition) -- this callback only exists at
        # all when we're the ones who opened the mic stream in the
        # first place. See _build_pipeline.
        self.pipeline["engine"].feed_audio(self.pipeline["engine_session"], resampled)
        self._last_tx_time = time.time()

    def _process_and_send(self, text):
        self._last_rx_time = time.time()
        if not self.profanity_allowed:
            text = censor_profanity(text)
        if self.persona_enabled:
            fn = PERSONA_STYLES.get(self.persona_style_key)
            if fn:
                text = fn(text)
        if self.uwu_enabled:
            text = uwuify(text)
        self.osc_client.send_message("/chatbox/input", [text, True])
        self.log(f"Sent to chatbox: {text}")
        self.push("last_text", text)

    def _keep_alive_tick(self):
        """Runs every ACTIVITY_LIGHT_CHECK_MS. Three separate jobs share
        this one timer: updating the TX/RX activity lights, pushing a
        periodic heartbeat so Keep Alive's status is actually visible
        instead of just assumed, and - the actual fix for the "goes
        silent after sitting idle" bug - proactively refreshing the
        Azure connection before it has a chance to go stale on its own.

        The bug: the recognizer session stays open continuously from
        startup, whether or not anyone is actively listening. Keep
        Alive as it existed before only reacted to canceled/
        session_stopped events - but a connection that's simply sat
        idle for a long time (very commonly killed by a NAT/firewall's
        idle timeout, without a clean close) can go dead without Azure's
        SDK ever firing either event. Nothing then tells the app to
        reconnect, so the very next attempt to actually use it goes
        nowhere. Refreshing proactively during idle periods - well
        before that can happen - closes the gap. Presence maintained
        on purpose, not just hoped for.
        """
        now = time.time()

        tx_active = (now - self._last_tx_time) < 0.3
        rx_active = (now - self._last_rx_time) < 0.6
        self.push("activity_lights", {"tx": tx_active, "rx": rx_active})

        if now - self._last_heartbeat_push_time >= KEEP_ALIVE_HEARTBEAT_SECONDS:
            self._last_heartbeat_push_time = now
            self.push("keep_alive_heartbeat", {
                "enabled": self.keep_alive_enabled,
                "connected": self.state.get("connected", False),
            })

        if not self.keep_alive_enabled:
            return
        if not self._current_engine().supports_keep_alive:
            return  # a loaded local model has no connection to go stale -- nothing to refresh
        if self.state.get("restarting") or self.state.get("shutting_down"):
            return
        if not self.state.get("connected"):
            return  # already known-disconnected - the reactive path handles this
        if self.state["active"]:
            return  # real audio is flowing right now, which already keeps this alive

        idle_seconds = now - self._last_connection_refresh_time
        if idle_seconds >= KEEP_ALIVE_IDLE_REFRESH_SECONDS:
            self.log("Keep Alive: proactively refreshing an idle connection before it can go stale...")
            self._perform_reset(resume_listening=False, is_auto_reconnect=True)

    def _handle_disconnect(self, reason):
        """Engine-agnostic now -- every cloud engine's on_disconnect
        callback lands here with a plain string, not an SDK-specific
        event object. Local engines never call this at all; there's no
        connection for them to lose."""
        self.log(f"{self._current_engine().label} connection ended: {reason}")

        if self.state["expect_disconnect"] or self.state["restarting"]:
            return

        self.state["connected"] = False

        if not self.keep_alive_enabled:
            self.log("Connection lost. Keep Alive is off - turn it on to "
                      "reconnect (that also works as a manual reconnect button).")
            return

        self.log("Keep Alive: connection lost unexpectedly, reconnecting...")
        self.push("status", {"state": "reconnecting"})
        was_active = self.state["active"]
        self.state["active"] = False
        self._perform_reset(resume_listening=was_active, is_auto_reconnect=True)

    def _build_pipeline(self, device_idx, input_language, output_language, on_progress=None):
        # Everything engine-specific now lives in speech_engines.py --
        # this function's own job shrank to two things every engine
        # shares: mic capture (for the five that need us to feed them
        # audio) and the on_progress startup-checklist bookkeeping. The
        # step id stays "azure_connecting" even for other engines --
        # renaming it would mean touching the JS startup list and every
        # on_progress call site for a purely cosmetic id; the visible
        # label text is what actually needed to stop being Azure-only
        # (see ui/index.html).
        engine = self._current_engine()

        if on_progress:
            on_progress("azure_connecting", "active")

        session = engine.start(
            device_idx, input_language, output_language,
            on_recognized=self._process_and_send,
            on_disconnect=self._handle_disconnect,
            on_partial=lambda: setattr(self, "_last_rx_time", time.time()),
        )

        if on_progress:
            on_progress("azure_connecting", "done")
            on_progress("mic_connecting", "active")

        new_pipeline = {
            "engine": engine,
            "engine_session": session,
            "mic_format": {"samplerate": SAMPLE_RATE, "channels": 1},
            "device_index": device_idx,
        }
        self.pipeline.update(new_pipeline)

        if engine.manages_own_audio_capture:
            # Windows Speech Recognition opens the mic itself through
            # its own platform APIs -- we never touch sounddevice for
            # it at all. See speech_engines.py's module docstring.
            self.log(f"{engine.label} is managing its own microphone input.")
        else:
            mic_stream, actual_sr, actual_ch = open_mic_stream(device_idx, self._shared_audio_callback)
            self.pipeline["mic_format"]["samplerate"] = actual_sr
            self.pipeline["mic_format"]["channels"] = actual_ch
            mic_stream.start()
            new_pipeline["mic_stream"] = mic_stream
            self.log(f"Mic opened at {actual_sr}Hz, {actual_ch} channel(s) "
                      f"(converting to {SAMPLE_RATE}Hz mono for {engine.label}).")

        if on_progress:
            on_progress("mic_connecting", "done")
        return new_pipeline

    def _teardown_pipeline(self, p):
        self.state["expect_disconnect"] = True
        self.state["connected"] = False
        if "mic_stream" in p:
            try:
                p["mic_stream"].stop()
                p["mic_stream"].close()
            except Exception:
                pass
        try:
            p["engine"].stop(p["engine_session"])
        except Exception:
            pass

    def _perform_reset(self, resume_listening=False, is_auto_reconnect=False):
        if self.state.get("shutting_down"):
            return
        self.state["restarting"] = True
        self.state["active"] = False
        self.push("status", {"state": "restarting" if not is_auto_reconnect else "reconnecting"})

        def do_reset():
            self._teardown_pipeline(self.pipeline)
            try:
                fresh = self._build_pipeline(
                    self.pipeline.get("device_index", self.device_index),
                    self.prefs["input_language"], self.prefs["output_language"],
                )
            except Exception as e:
                label = "Keep Alive reconnect" if is_auto_reconnect else "Reset"
                self.log(f"{label} failed: {e}")
                self.state["restarting"] = False
                self.push("status", {"state": "paused"})
                if is_auto_reconnect and self.keep_alive_enabled:
                    self.log("Keep Alive: will try again in 5 seconds...")
                    retry_timer = threading.Timer(5.0, lambda: self._perform_reset(
                        resume_listening=resume_listening, is_auto_reconnect=True))
                    retry_timer.daemon = True
                    retry_timer.start()
                return

            self.state["expect_disconnect"] = False
            self.state["connected"] = True
            self._last_connection_refresh_time = time.time()
            self.pipeline.clear()
            self.pipeline.update(fresh)

            if is_auto_reconnect:
                self.log("Keep Alive: reconnected successfully.")
            else:
                self.log("Reset complete.")
            self.state["restarting"] = False
            self.push("status", {"state": "reconnected_blink", "resume": resume_listening})
            if resume_listening:
                time.sleep(1.5)
                self.toggle_listening(force_on=True)

        threading.Thread(target=do_reset, daemon=True).start()

    # ---- listening control ----
    @Slot()
    def toggle_listening(self, force_on=None):
        if self.state["restarting"]:
            return
        new_active = (not self.state["active"]) if force_on is None else force_on
        if new_active == self.state["active"]:
            return

        if new_active and not self.state.get("connected"):
            self.log("No active Azure connection - reconnecting before starting...")
            self._perform_reset(resume_listening=True, is_auto_reconnect=True)
            return

        self.state["active"] = new_active
        self.push("status", {"state": "listening" if new_active else "paused"})

    # ---- language ----
    @Slot(str, str)
    def set_language(self, input_label, output_label):
        if self.state["restarting"]:
            return
        engine = self._current_engine()
        input_map = flatten_languages(engine.input_languages())
        output_map = engine.output_languages()
        new_input = input_map.get(input_label, self.prefs["input_language"])
        new_output = output_map.get(output_label, self.prefs["output_language"])
        if new_input == self.prefs["input_language"] and new_output == self.prefs["output_language"]:
            return
        self.prefs["input_language"] = new_input
        self.prefs["output_language"] = new_output
        # Remembered per-service, so switching to a different engine and
        # back doesn't lose this choice -- see DEFAULT_PREFS.
        self.prefs["input_language_by_service"][self.speech_service] = new_input
        self.prefs["output_language_by_service"][self.speech_service] = new_output
        save_prefs(self.prefs)
        self.log(f"Language changed to {input_label} -> {output_label}. Reconnecting...")
        self._perform_reset(resume_listening=False, is_auto_reconnect=False)

    # ---- speech service ----
    @Slot(str, result=str)
    def set_speech_service(self, service_key):
        if service_key not in self._engines:
            return json.dumps({"ok": False, "error": f"Unknown speech service: {service_key}"})
        if self.state["restarting"]:
            return json.dumps({"ok": False, "error": "Busy reconnecting -- try again in a moment."})
        if service_key == self.speech_service:
            return json.dumps({"ok": True})

        self.speech_service = service_key
        self.prefs["speech_service"] = service_key

        # Restore whatever language this service was last set to, or
        # fall back to its first available option -- a code left over
        # from a DIFFERENT engine (Azure's "en-US" landing on Whisper,
        # which wants bare "en") would be silently wrong otherwise.
        engine = self._current_engine()
        input_map = flatten_languages(engine.input_languages())
        output_map = engine.output_languages()
        remembered_input = self.prefs["input_language_by_service"].get(service_key)
        remembered_output = self.prefs["output_language_by_service"].get(service_key)
        self.prefs["input_language"] = (
            remembered_input if remembered_input in input_map.values()
            else next(iter(input_map.values()), "")
        )
        self.prefs["output_language"] = (
            remembered_output if remembered_output in output_map.values() else "none"
        )
        save_prefs(self.prefs)

        self.log(f"Speech service switched to: {engine.label}. Reconnecting...")
        self.push("speech_service_changed", {
            "service": service_key,
            "input_language_groups": language_groups_for_json(input_map),
            "output_languages": list(output_map.keys()),
            "input_language": label_for_code(input_map, self.prefs["input_language"], ""),
            "output_language": label_for_code(
                output_map, self.prefs["output_language"], "No translation (send as heard)"
            ),
            "supports_translation": engine.supports_translation,
            "supports_keep_alive": engine.supports_keep_alive,
        })
        self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    # ---- device ----
    @Slot(str)
    def set_device(self, selected_name):
        if self.state["restarting"]:
            return
        if selected_name == self.prefs.get("device_name"):
            return
        new_index = None
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["name"] == selected_name:
                new_index = i
                break
        if new_index is None:
            return
        old_mic = self.pipeline.get("mic_stream")
        try:
            if old_mic:
                old_mic.stop()
                old_mic.close()
        except Exception:
            pass
        try:
            new_mic_stream, sr, ch = open_mic_stream(new_index, self._shared_audio_callback)
        except RuntimeError as e:
            self.log(f"Microphone error: {e}")
            return
        self.pipeline["mic_stream"] = new_mic_stream
        self.pipeline["mic_format"]["samplerate"] = sr
        self.pipeline["mic_format"]["channels"] = ch
        self.pipeline["device_index"] = new_index
        new_mic_stream.start()
        self.device_index = new_index
        self.device_name = selected_name
        self.prefs["device_name"] = selected_name
        save_prefs(self.prefs)
        self.log(f"Switched microphone to: {selected_name} ({sr}Hz, {ch} channel(s))")

    @Slot(str, result=str)
    def save_osc_port(self, port):
        try:
            port = int(port)
        except (TypeError, ValueError):
            self.log(f"Ignored invalid OSC port: {port!r}")
            return json.dumps({"ok": False, "error": "Port must be a number.", "port": self.prefs.get("osc_port", VRCHAT_PORT)})

        if not (1 <= port <= 65535):
            self.log(f"Ignored out-of-range OSC port: {port}")
            return json.dumps({"ok": False, "error": "Port must be between 1 and 65535.", "port": self.prefs.get("osc_port", VRCHAT_PORT)})

        if port == self.prefs.get("osc_port", VRCHAT_PORT):
            return json.dumps({"ok": True, "port": port})

        self.prefs["osc_port"] = port
        save_prefs(self.prefs)
        self.osc_client = SimpleUDPClient(VRCHAT_IP, port)
        self.log(f"VRChat OSC port changed to {port}.")
        return json.dumps({"ok": True, "port": port})

    @Slot(str)
    def save_custom_endpoint(self, endpoint_id):
        endpoint_id = (endpoint_id or "").strip()
        if endpoint_id == self.prefs.get("custom_endpoint_id", ""):
            return
        self.prefs["custom_endpoint_id"] = endpoint_id
        save_prefs(self.prefs)
        if endpoint_id:
            self.log(f"Custom Speech endpoint set: {endpoint_id}. Reconnecting...")
        else:
            self.log("Custom Speech endpoint cleared - back to the standard model. Reconnecting...")
        self._perform_reset(resume_listening=False, is_auto_reconnect=False)

    @Slot(bool, str, str, str, str, result=str)
    def save_hotkey_settings(self, enabled, mode, input_type, key_str, vr_combo_json):
        key_str = (key_str or "").strip().lower()
        mode = mode if mode in ("toggle", "push_to_talk") else "toggle"
        input_type = input_type if input_type in ("keyboard", "vr_controller") else "keyboard"
        try:
            vr_combo = json.loads(vr_combo_json) if vr_combo_json else []
        except (ValueError, TypeError):
            vr_combo = []

        if enabled:
            if input_type == "keyboard":
                _, err = parse_hotkey(key_str)
                if err:
                    return json.dumps({"ok": False, "error": err})
            elif input_type == "vr_controller" and not vr_combo:
                return json.dumps({"ok": False, "error": "Capture a controller combo first."})

        self.prefs["hotkey_enabled"] = enabled
        self.prefs["hotkey_mode"] = mode
        self.prefs["hotkey_input_type"] = input_type
        self.prefs["hotkey_key"] = key_str
        self.prefs["hotkey_vr_combo"] = vr_combo
        save_prefs(self.prefs)
        self._setup_hotkey()

        if input_type == "vr_controller":
            display = " + ".join(vr_identifier_to_label(b) for b in sorted(vr_combo)) if vr_combo else ""
        else:
            display = describe_key(key_str)
        self.push("hotkey_settings", {
            "hotkey_enabled": enabled,
            "hotkey": display,
            "mode": mode,
        })
        return json.dumps({"ok": True})

    # ---- toggles ----
    @Slot(result=bool)
    def toggle_uwu(self):
        self.uwu_enabled = not self.uwu_enabled
        self.prefs["uwu_enabled"] = self.uwu_enabled
        save_prefs(self.prefs)
        return self.uwu_enabled

    @Slot(result=bool)
    def toggle_profanity(self):
        self.profanity_allowed = not self.profanity_allowed
        self.prefs["profanity_allowed"] = self.profanity_allowed
        save_prefs(self.prefs)
        return self.profanity_allowed

    @Slot(result=bool)
    def toggle_persona(self):
        self.persona_enabled = not self.persona_enabled
        self.prefs["persona_enabled"] = self.persona_enabled
        save_prefs(self.prefs)
        return self.persona_enabled

    @Slot(str)
    def set_persona_style(self, label):
        key = PERSONA_LABELS.get(label, "")
        self.persona_style_key = key
        self.prefs["persona_style"] = key
        save_prefs(self.prefs)
        self.log(f"Persona style set to: {label}")

    @Slot(result=bool)
    def toggle_keep_alive(self):
        self.keep_alive_enabled = not self.keep_alive_enabled
        self.prefs["keep_alive_enabled"] = self.keep_alive_enabled
        save_prefs(self.prefs)
        self.log(f"Keep Alive turned {'on' if self.keep_alive_enabled else 'off'}.")
        if self.keep_alive_enabled and not self.state["restarting"]:
            self._perform_reset(resume_listening=self.state["active"], is_auto_reconnect=True)
        return self.keep_alive_enabled

    @Slot(result=bool)
    def toggle_overlay_mode(self):
        """Skips the background image and switches decorative outlines
        (dropdown/modal borders) over to the user's text color -- built
        for pinning the window in VR via XSOverlay/OVR Toolkit's generic
        desktop-capture, where a photographic background is more likely
        to capture badly than a flat, high-contrast panel. The saved
        background path itself is untouched -- turning this back off
        restores whatever was there before, nothing lost in between."""
        self.overlay_mode_enabled = not self.overlay_mode_enabled
        self.prefs["overlay_mode_enabled"] = self.overlay_mode_enabled
        save_prefs(self.prefs)
        self.log(f"Overlay Mode turned {'on' if self.overlay_mode_enabled else 'off'}.")
        self.push("overlay_mode", {"enabled": self.overlay_mode_enabled})
        return self.overlay_mode_enabled

    # ---- Azure config ----
    @Slot(str, str, result=str)
    def save_azure_config(self, key, region):
        global AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
        key = (key or "").strip()
        region = (region or "").strip()
        if not key or not region:
            return json.dumps({"ok": False, "error": "Both fields are required."})

        self.log("Testing Azure connection...")
        ok, err = test_azure_credentials(key, region)
        if not ok:
            self.log(f"Azure connection test failed: {err}")
            return json.dumps({"ok": False, "error": err})

        save_env_values(key, region)
        AZURE_SPEECH_KEY = key
        AZURE_SPEECH_REGION = region
        self.log("Azure connection verified. Reconnecting...")
        self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    @Slot(result=str)
    def get_azure_config(self):
        return json.dumps({"key": AZURE_SPEECH_KEY, "region": AZURE_SPEECH_REGION})

    # ---- raw field autosave (see SPEECH_FIELD_PREF_KEYS) ----
    @Slot(str, str, str)
    def save_speech_field(self, service, field, value):
        pref_key = SPEECH_FIELD_PREF_KEYS.get((service, field))
        if not pref_key:
            return
        self.prefs[pref_key] = value
        save_prefs(self.prefs)

    # ---- Google Cloud Speech-to-Text config ----
    @Slot(result=str)
    def browse_google_credentials(self):
        parent = self.config_window or self.main_window
        path, _ = QFileDialog.getOpenFileName(
            parent, "Choose Google Cloud service account key", "",
            "JSON files (*.json);;All files (*.*)",
        )
        return json.dumps(path or None)

    @Slot(str, result=str)
    def save_google_config(self, credentials_path):
        credentials_path = (credentials_path or "").strip()
        if not credentials_path:
            return json.dumps({"ok": False, "error": "Choose a service account key file first."})
        if not os.path.exists(credentials_path):
            return json.dumps({"ok": False, "error": f"File not found: {credentials_path}"})

        previous = self.prefs.get("google_credentials_path", "")
        self.prefs["google_credentials_path"] = credentials_path
        self.log("Testing Google Cloud connection...")
        ok, err = self._engines["google"].test_connection()
        if not ok:
            self.prefs["google_credentials_path"] = previous
            self.log(f"Google Cloud connection test failed: {err}")
            return json.dumps({"ok": False, "error": err})

        save_prefs(self.prefs)
        self.log("Google Cloud connection verified.")
        if self.speech_service == "google":
            self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    # ---- AWS Transcribe config ----
    @Slot(str, str, str, result=str)
    def save_aws_config(self, access_key, secret_key, region):
        access_key = (access_key or "").strip()
        secret_key = (secret_key or "").strip()
        region = (region or "").strip()
        if not access_key or not secret_key or not region:
            return json.dumps({
                "ok": False,
                "error": "Access Key ID, Secret Access Key, and Region are all required.",
            })

        previous = (
            self.prefs.get("aws_access_key", ""),
            self.prefs.get("aws_secret_key", ""),
            self.prefs.get("aws_region", ""),
        )
        self.prefs["aws_access_key"] = access_key
        self.prefs["aws_secret_key"] = secret_key
        self.prefs["aws_region"] = region
        self.log("Testing AWS connection...")
        ok, err = self._engines["aws"].test_connection()
        if not ok:
            self.prefs["aws_access_key"], self.prefs["aws_secret_key"], self.prefs["aws_region"] = previous
            self.log(f"AWS connection test failed: {err}")
            return json.dumps({"ok": False, "error": err})

        save_prefs(self.prefs)
        self.log("AWS connection verified.")
        if self.speech_service == "aws":
            self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    # ---- Whisper config (local) ----
    @Slot(str, str, result=str)
    def save_whisper_config(self, model_size, device):
        model_size = model_size if model_size in speech_engines.WHISPER_MODEL_SIZES else "base"
        device = device if device in ("cpu", "cuda") else "cpu"

        previous = (self.prefs.get("whisper_model_size", "base"), self.prefs.get("whisper_device", "cpu"))
        self.prefs["whisper_model_size"] = model_size
        self.prefs["whisper_device"] = device
        self.log(f"Loading Whisper model ({model_size}, {device})... "
                 f"first load can take a moment while it downloads.")
        ok, err = self._engines["whisper"].test_connection()
        if not ok:
            self.prefs["whisper_model_size"], self.prefs["whisper_device"] = previous
            self.log(f"Whisper setup failed: {err}")
            return json.dumps({"ok": False, "error": err})

        save_prefs(self.prefs)
        self.log("Whisper model loaded.")
        if self.speech_service == "whisper":
            self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    # ---- Vosk config (local) ----
    @Slot(result=str)
    def browse_vosk_model(self):
        parent = self.config_window or self.main_window
        path = QFileDialog.getExistingDirectory(parent, "Choose Vosk model folder")
        return json.dumps(path or None)

    @Slot(str, result=str)
    def save_vosk_config(self, model_path):
        model_path = (model_path or "").strip()
        if not model_path:
            return json.dumps({"ok": False, "error": "Choose a Vosk model folder first."})
        if not os.path.isdir(model_path):
            return json.dumps({"ok": False, "error": f"Folder not found: {model_path}"})

        previous = self.prefs.get("vosk_model_path", "")
        self.prefs["vosk_model_path"] = model_path
        self.log("Loading Vosk model...")
        ok, err = self._engines["vosk"].test_connection()
        if not ok:
            self.prefs["vosk_model_path"] = previous
            self.log(f"Vosk setup failed: {err}")
            return json.dumps({"ok": False, "error": err})

        save_prefs(self.prefs)
        self.log("Vosk model loaded.")
        if self.speech_service == "vosk":
            self._perform_reset(resume_listening=False, is_auto_reconnect=False)
        return json.dumps({"ok": True})

    # ---- Windows Speech Recognition (local, nothing to configure) ----
    @Slot(result=str)
    def test_windows_speech(self):
        self.log("Testing Windows Speech Recognition...")
        ok, err = self._engines["windows"].test_connection()
        if not ok:
            self.log(f"Windows Speech Recognition test failed: {err}")
            return json.dumps({"ok": False, "error": err})
        self.log("Windows Speech Recognition is available.")
        return json.dumps({"ok": True})

    @Slot(result=str)
    def get_config_state(self):
        return json.dumps({
            "speech_service": self.speech_service,
            "speech_services": [
                {"key": key, "label": self._engines[key].label} for key in speech_engines.ENGINE_ORDER
            ],
            "azure_key": AZURE_SPEECH_KEY,
            "azure_region": AZURE_SPEECH_REGION,
            "google_credentials_path": self.prefs.get("google_credentials_path", ""),
            "aws_access_key": self.prefs.get("aws_access_key", ""),
            "aws_secret_key": self.prefs.get("aws_secret_key", ""),
            "aws_region": self.prefs.get("aws_region", ""),
            "whisper_model_size": self.prefs.get("whisper_model_size", "base"),
            "whisper_model_sizes": speech_engines.WHISPER_MODEL_SIZES,
            "whisper_device": self.prefs.get("whisper_device", "cpu"),
            "vosk_model_path": self.prefs.get("vosk_model_path", ""),
            "text_color": self.prefs.get("text_color") or "#ffffff",
            "text_font_family": self.prefs.get("text_font_family") or "Segoe UI",
            "devices": self._get_devices_list(),
            "device_name": self.prefs.get("device_name") or self.device_name or "",
            "main_bg_path": self.prefs.get("custom_background_path") or "(default)",
            "tiny_bg_path": self.prefs.get("custom_tiny_background_path") or "(default)",
            "overlay_mode_enabled": self.overlay_mode_enabled,
            "osc_port": self.prefs.get("osc_port", VRCHAT_PORT),
            "custom_endpoint_id": self.prefs.get("custom_endpoint_id", ""),
            "hotkey_enabled": self.prefs.get("hotkey_enabled", False),
            "hotkey_mode": self.prefs.get("hotkey_mode", "toggle"),
            "hotkey_input_type": self.prefs.get("hotkey_input_type", "keyboard"),
            "hotkey_key": self.prefs.get("hotkey_key", "f9"),
            "hotkey_vr_combo": self.prefs.get("hotkey_vr_combo", []),
            "hotkey_vr_combo_labels": [
                vr_identifier_to_label(b) for b in sorted(self.prefs.get("hotkey_vr_combo", []))
            ],
            "openvr_available": OPENVR_MODULE_AVAILABLE,
        })

    # ---- backgrounds ----
    @Slot(str, result=str)
    def browse_background(self, which):
        parent = self.config_window or self.main_window
        path, _ = QFileDialog.getOpenFileName(
            parent, "Choose an image", "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.gif);;All files (*.*)",
        )
        if not path:
            return json.dumps(None)
        key = "custom_background_path" if which == "main" else "custom_tiny_background_path"
        self.prefs[key] = path
        save_prefs(self.prefs)
        self.log(f"{'Main window' if which == 'main' else 'Tiny Mode'} background set to: {path}")
        data_uri = self._background_data_uri(path)
        self.push("background", {"which": which, "data_uri": data_uri})
        return json.dumps({"data_uri": data_uri, "path": path})

    @Slot(str, result=str)
    def reset_background(self, which):
        key = "custom_background_path" if which == "main" else "custom_tiny_background_path"
        self.prefs[key] = ""
        save_prefs(self.prefs)
        default_name = "background.png" if which == "main" else "tiny_background.png"
        self.log(f"{'Main window' if which == 'main' else 'Tiny Mode'} background reset to default.")
        data_uri = self._background_data_uri(self._default_asset(default_name))
        self.push("background", {"which": which, "data_uri": data_uri})
        return json.dumps({"data_uri": data_uri, "path": "(default)"})

    # ---- appearance ----
    @Slot(str)
    def set_text_color(self, hex_color):
        self.prefs["text_color"] = hex_color
        save_prefs(self.prefs)
        self.push("theme", {"text_color": hex_color, "font_family": None})

    @Slot(str)
    def set_text_font(self, family):
        self.prefs["text_font_family"] = family
        save_prefs(self.prefs)
        self.push("theme", {"text_color": None, "font_family": family})

    # ---- tiny mode ----
    @Slot()
    def enter_tiny_mode(self):
        self.state["tiny_mode"] = True
        if self.main_window:
            self.main_window.resize(WINDOW_WIDTH, TINY_WINDOW_HEIGHT)

    @Slot()
    def enter_full_mode(self):
        self.state["tiny_mode"] = False
        if self.main_window:
            self.main_window.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

    # ---- about / donation ----
    @Slot()
    def open_donation_link(self):
        webbrowser.open(DONATION_URL)

    @Slot()
    def open_group_link(self):
        webbrowser.open(GROUP_URL)

    @Slot()
    def open_discord_link(self):
        webbrowser.open(DISCORD_URL)

    @Slot(result=str)
    def get_about_info(self):
        return json.dumps({
            "app_name": APP_NAME,
            "credits": APP_CREDITS_TEXT,
            "donate_blurb": DONATE_BLURB,
        })

    # ---- shutdown ----
    @Slot()
    def shutdown(self):
        if self.state.get("shutting_down"):
            return
        self.state["shutting_down"] = True
        self.keep_alive_enabled = False

        try:
            if self._hotkey_listener:
                self._hotkey_listener.stop()
        except Exception:
            pass

        if self._vr_hotkey_stop_event is not None:
            self._vr_hotkey_stop_event.set()
        self._vr_capture_active = False
        self._vr_monitor.shutdown()

        self._teardown_pipeline(self.pipeline)

        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass

        QApplication.instance().quit()

    # ---- secondary windows ----
    @Slot()
    def open_config_window(self):
        if self.config_window is not None:
            self.config_window.show()
            self.config_window.raise_()
            self.config_window.activateWindow()
            return
        self.config_window = make_secondary_window(
            self, "Config", "config.html", 420, 760,
            on_closed=lambda: setattr(self, "config_window", None),
        )
        self.config_window.show()

    @Slot()
    def open_about_window(self):
        if self.about_window is not None:
            self.about_window.show()
            self.about_window.raise_()
            self.about_window.activateWindow()
            return
        self.about_window = make_secondary_window(
            self, "About / Support", "about.html", 360, 540,
            on_closed=lambda: setattr(self, "about_window", None),
        )
        self.about_window.show()

    @Slot()
    def close_config_window(self):
        if self.config_window is not None:
            self.config_window.close()

    @Slot()
    def close_about_window(self):
        if self.about_window is not None:
            self.about_window.close()

    @Slot(str)
    def open_setup_guide(self, name):
        entry = SETUP_GUIDES.get(name)
        if not entry:
            return
        _, title = entry
        # One shared guide window, retargeted to whichever guide was
        # just clicked, rather than a window per engine -- opening
        # Google's guide then AWS's shouldn't leave a stack of windows
        # behind, just the one you're actually reading now.
        if self.guide_window is not None:
            self.guide_window.setWindowTitle(title)
            self.guide_window._view.load(QUrl(f"{self.base_url}/ui/guide.html?name={name}"))
            self.guide_window.show()
            self.guide_window.raise_()
            self.guide_window.activateWindow()
            return
        self.guide_window = make_secondary_window(
            self, title, f"guide.html?name={name}", 600, 680,
            on_closed=lambda: setattr(self, "guide_window", None),
        )
        self.guide_window.show()

    @Slot()
    def close_setup_guide_window(self):
        if self.guide_window is not None:
            self.guide_window.close()

    @Slot(str, result=str)
    def get_setup_guide(self, name):
        entry = SETUP_GUIDES.get(name)
        if not entry:
            return json.dumps({"ok": False, "error": f"Unknown setup guide: {name}"})
        filename, title = entry
        path = os.path.join(get_app_dir(), filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                markdown = f.read()
        except OSError as e:
            return json.dumps({"ok": False, "error": f"Couldn't read {filename}: {e}"})
        return json.dumps({"ok": True, "title": title, "markdown": markdown})

    @Slot(str)
    def open_external_link(self, url):
        # Guide content is our own six .md files, but the links inside
        # them point out to Azure/Google/AWS/Vosk's own sites -- open
        # those in the user's real browser, never navigate the embedded
        # guide window itself there. Scheme-checked, not just trusted,
        # since this is reachable from rendered Markdown content.
        if url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)

    # ---- content + app update checks ----
    @Slot(result=str)
    def check_for_content_update(self):
        app_dir = get_app_dir()
        local_version = read_local_content_version(app_dir)
        remote_version = fetch_remote_content_version()
        if remote_version is None:
            return json.dumps({"ok": False, "error": "Couldn't reach GitHub to check for a content update."})
        if remote_version <= local_version:
            return json.dumps({"ok": True, "updated": False, "version": local_version})

        self.log(f"Content update available (v{local_version} -> v{remote_version}), downloading...")
        ok, new_version, error = download_and_apply_content_update(app_dir, log=self.log)
        if not ok:
            return json.dumps({"ok": False, "error": error})
        return json.dumps({"ok": True, "updated": True, "version": new_version})

    @Slot(result=str)
    def check_for_app_update(self):
        tag, url = fetch_latest_release()
        if not tag:
            return json.dumps({"ok": False, "error": "Couldn't reach GitHub to check for an app update."})
        return json.dumps({
            "ok": True,
            "current_version": APP_VERSION,
            "latest_version": tag,
            "newer_available": is_newer_version(tag, APP_VERSION),
            "url": url,
        })

    @Slot(str)
    def open_app_release_page(self, url):
        if url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)

    def _run_update_checks(self):
        # Runs on its own background thread from frontend_ready, fully
        # independent of start_backend's mic/engine pipeline -- a slow
        # or failed GitHub request here should never delay or break
        # actually getting the app talking.
        app_dir = get_app_dir()
        local_version = read_local_content_version(app_dir)
        remote_version = fetch_remote_content_version()
        if remote_version is not None and remote_version > local_version:
            self.log(f"Content update available (v{local_version} -> v{remote_version}), downloading...")
            ok, new_version, error = download_and_apply_content_update(app_dir, log=self.log)
            if ok:
                self.log(f"Content updated to v{new_version}. Some changes need a restart to show up.")
            else:
                self.log(f"Content update check failed: {error}")

        tag, url = fetch_latest_release()
        if tag and url and is_newer_version(tag, APP_VERSION):
            self.log(f"A newer version of {APP_NAME} is available: {tag} (currently on v{APP_VERSION}).")
            self.push("app_update_available", {"version": tag, "url": url})

    # ---- startup ----
    def _resolve_device(self):
        prefs_device = self.prefs.get("device_name")
        all_devices = sd.query_devices()
        if prefs_device:
            for i, d in enumerate(all_devices):
                if d["max_input_channels"] > 0 and d["name"] == prefs_device:
                    return i, prefs_device
        default_idx = sd.default.device[0] if sd.default.device[0] is not None and sd.default.device[0] >= 0 else None
        if default_idx is None:
            for i, d in enumerate(all_devices):
                if d["max_input_channels"] > 0:
                    default_idx = i
                    break
        if default_idx is None:
            return None, None
        name = all_devices[default_idx]["name"]
        self.prefs["device_name"] = name
        save_prefs(self.prefs)
        return default_idx, name

    def _setup_hotkey(self):
        """Stops any existing listener (keyboard or VR) and, if hotkeys
        are enabled, starts a fresh one using the current prefs. Safe
        to call repeatedly - e.g. whenever the user changes the hotkey
        settings in Config, not just once at startup."""
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None
        if self._vr_hotkey_stop_event is not None:
            self._vr_hotkey_stop_event.set()
            self._vr_hotkey_stop_event = None
        self._toggle_key_down = False

        if not self.prefs.get("hotkey_enabled", False):
            return

        if self.prefs.get("hotkey_input_type", "keyboard") == "vr_controller":
            self._setup_vr_hotkey()
        else:
            self._setup_keyboard_hotkey()

    def _setup_keyboard_hotkey(self):
        key_str = self.prefs.get("hotkey_key", "f9")
        target_key, err = parse_hotkey(key_str)
        if err:
            self.log(f"Hotkey not active: {err}")
            return
        mode = self.prefs.get("hotkey_mode", "toggle")

        def on_press(key):
            if key != target_key:
                return
            if mode == "push_to_talk":
                self.toggle_listening(force_on=True)
            elif mode == "toggle" and not self._toggle_key_down:
                self._toggle_key_down = True
                self.toggle_listening()

        def on_release(key):
            if key != target_key:
                return
            if mode == "push_to_talk":
                self.toggle_listening(force_on=False)
            elif mode == "toggle":
                self._toggle_key_down = False

        self._hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._hotkey_listener.start()
        self.log(f"Hotkey enabled: {describe_key(key_str)} "
                 f"({'Push-to-Talk' if mode == 'push_to_talk' else 'Toggle'}).")

    def _setup_vr_hotkey(self):
        combo = set(self.prefs.get("hotkey_vr_combo", []))
        if not combo:
            self.log("VR hotkey not active: no combo has been captured yet.")
            return

        ok, err = self._vr_monitor.ensure_initialized()
        if not ok:
            self.log(f"VR hotkey not active: {err}")
            return

        mode = self.prefs.get("hotkey_mode", "toggle")
        stop_event = threading.Event()
        self._vr_hotkey_stop_event = stop_event

        def loop():
            was_down = False
            while not stop_event.is_set():
                pressed = self._vr_monitor.poll_pressed()
                is_down = combo.issubset(pressed)
                if is_down and not was_down:
                    if mode == "push_to_talk":
                        self.toggle_listening(force_on=True)
                    elif mode == "toggle":
                        self.toggle_listening()
                elif not is_down and was_down:
                    if mode == "push_to_talk":
                        self.toggle_listening(force_on=False)
                was_down = is_down
                time.sleep(0.03)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        labels = " + ".join(vr_identifier_to_label(b) for b in sorted(combo))
        self.log(f"VR hotkey enabled: {labels} "
                 f"({'Push-to-Talk' if mode == 'push_to_talk' else 'Toggle'}).")

    @Slot()
    def start_vr_capture(self):
        """Begins listening for a VR controller combo - holds whatever
        buttons get pressed, and auto-finalizes once everything is
        released again, pushing live feedback the whole time so Config
        can show what's currently held."""
        if self._vr_capture_active:
            return
        ok, err = self._vr_monitor.ensure_initialized()
        if not ok:
            self.push("vr_capture_error", err)
            return
        self._vr_capture_active = True

        def loop():
            best = set()
            seen_any = False
            while self._vr_capture_active:
                pressed = self._vr_monitor.poll_pressed()
                if pressed:
                    seen_any = True
                    if len(pressed) >= len(best):
                        best = pressed
                    self.push("vr_capture_update", {
                        "pressed": [vr_identifier_to_label(b) for b in sorted(pressed)],
                    })
                elif seen_any:
                    self._vr_capture_active = False
                    self.push("vr_capture_done", {
                        "combo": sorted(best),
                        "labels": [vr_identifier_to_label(b) for b in sorted(best)],
                    })
                    return
                time.sleep(0.03)

        threading.Thread(target=loop, daemon=True).start()

    @Slot()
    def cancel_vr_capture(self):
        self._vr_capture_active = False

    def start_backend(self):
        """Called once the main window is up - wires up the mic/Azure
        pipeline and the global hotkey. Runs on a background thread so
        it never blocks the Qt event loop. The window opens its eyes
        first; the machinery wakes up right after."""
        if not AZURE_SPEECH_KEY or not AZURE_SPEECH_REGION:
            msg = "Azure key/region not found - open Config (gear icon) to set them."
            self.log(f"ERROR: {msg}")
            self.push("startup_step", {"step": "mic_finding", "status": "error"})
            self.push("startup_step", {"step": "azure_connecting", "status": "error", "message": msg})
            self.push("startup_step", {"step": "mic_connecting", "status": "error"})
            self.push("startup_step", {"step": "ready", "status": "error"})
            return

        self.push("startup_step", {"step": "mic_finding", "status": "active"})
        self.device_index, self.device_name = self._resolve_device()
        if self.device_index is None:
            msg = "No microphone found on this system."
            self.log(msg)
            self.push("startup_step", {"step": "mic_finding", "status": "error", "message": msg})
            self.push("startup_step", {"step": "azure_connecting", "status": "error"})
            self.push("startup_step", {"step": "mic_connecting", "status": "error"})
            self.push("startup_step", {"step": "ready", "status": "error"})
            return
        self.push("startup_step", {"step": "mic_finding", "status": "done"})

        def on_progress(step, status):
            self.push("startup_step", {"step": step, "status": status})

        try:
            self.pipeline.update(self._build_pipeline(
                self.device_index, self.prefs["input_language"], self.prefs["output_language"],
                on_progress=on_progress,
            ))
        except Exception as e:
            msg = str(e)
            self.log(f"Startup error: {msg}")
            self.push("startup_step", {"step": "azure_connecting", "status": "error", "message": msg})
            self.push("startup_step", {"step": "mic_connecting", "status": "error"})
            self.push("startup_step", {"step": "ready", "status": "error"})
            return

        self.state["connected"] = True
        self._last_connection_refresh_time = time.time()
        self._setup_hotkey()
        self.log(f"Ready. Mic: {self.device_name}")
        self.push("startup_step", {"step": "ready", "status": "done"})

    @Slot()
    def frontend_ready(self):
        """Called by app.js once the page has fully loaded and hydrated.
        Starting the backend from here (rather than as soon as the
        window exists) avoids racing the page's own startup - same
        reasoning as before, just less fragile now since there's no
        pythonnet bridge in the middle to deadlock. Don't rush the
        greeting before the room's actually ready."""
        threading.Thread(target=self.start_backend, daemon=True).start()
        threading.Thread(target=self._run_update_checks, daemon=True).start()


class MainWindow(QMainWindow):
    """The main app window. Overrides closeEvent so that closing via the
    native titlebar X runs the exact same cleanup as the power-icon
    shutdown - both paths need to release the mic, Azure connection,
    and hotkey hook properly. Leave the room the same way, however you
    choose to leave it."""

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge
        self.setWindowTitle("Ascended STT")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setFixedWidth(WINDOW_WIDTH)

        self.view = QWebEngineView()
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(self.view)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.channel)

    def closeEvent(self, event):
        self.bridge.shutdown()
        event.accept()


def make_secondary_window(bridge, title, html_file, width, height, on_closed):
    """Config and About are both plain windows sharing the SAME bridge
    object as the main window, so calls from either one talk to the
    same live app state (prefs, Azure config, etc) rather than a
    separate copy of it. One truth, no matter which door you walked
    in through."""
    window = QMainWindow()
    window.setWindowTitle(title)
    window.resize(width, height)
    window.setFixedWidth(width)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    view = QWebEngineView()
    view.page().setBackgroundColor(Qt.GlobalColor.white)
    window.setCentralWidget(view)

    channel = QWebChannel(window)
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)
    view.load(QUrl(f"{bridge.base_url}/ui/{html_file}"))

    # Keep a strong Python reference to view/channel for as long as the
    # window lives. Neither has an explicit Qt parent tying its
    # lifetime to the window (setCentralWidget re-parents the view's
    # underlying widget, but the QWebChannel has no parent at all), so
    # without this, Python's own garbage collector can - and does -
    # collect them once this function returns. The HTML/CSS keeps
    # rendering fine either way (that part doesn't need the channel),
    # but every button that calls into Python silently stops working,
    # which is exactly the bug this fixes.
    window._view = view
    window._channel = channel

    def handle_closed():
        on_closed()

    window.destroyed.connect(handle_closed)
    return window


# ---------------------------------------------------------------------------
# CONTENT + APP UPDATE CHECKS
#
# Two genuinely different things, deliberately not conflated:
#
# - "Content" is ui/, assets/, and the six *_SETUP.md guides -- loose
#   files sitting next to the exe, not baked in. Since they're just
#   data, they can be safely fetched and overwritten at any time
#   (including while the app is already running), so this is fully
#   automatic: check content_version.txt against GitHub, and if
#   there's a newer one, download and apply it. No separate updater
#   process needed, no restart required to be SAFE (though UI changes
#   won't show up in an already-open window until relaunch).
#
# - The app itself (the exe and its bundled PySide6/Chromium runtime)
#   is a different story -- Windows won't let a running process
#   overwrite its own exe, so actually replacing it needs a separate
#   helper process watching for this one to exit. That's real
#   engineering this pass doesn't attempt. Instead: check GitHub's
#   latest release tag against APP_VERSION, and if newer, just tell
#   the user and link to the release page -- same download-and-swap
#   step they'd already do today, just not left to chance.
# ---------------------------------------------------------------------------
CONTENT_REPO = "hex-vr/Ascended-STT"
CONTENT_BRANCH = "main"
CONTENT_PATHS = [
    "ui", "assets",
    "AZURE_SETUP.md", "GOOGLE_SETUP.md", "AWS_SETUP.md",
    "WHISPER_SETUP.md", "VOSK_SETUP.md", "WINDOWS_SPEECH_SETUP.md",
]
CONTENT_VERSION_URL = (
    f"https://raw.githubusercontent.com/{CONTENT_REPO}/{CONTENT_BRANCH}/content_version.txt"
)
CONTENT_ZIP_URL = f"https://codeload.github.com/{CONTENT_REPO}/zip/refs/heads/{CONTENT_BRANCH}"
RELEASES_API_URL = f"https://api.github.com/repos/{CONTENT_REPO}/releases/latest"


def _http_get_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "AscendedSTT"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def read_local_content_version(app_dir):
    """Whatever content_version.txt currently says on disk -- 0 if it's
    missing entirely, same as a fresh checkout that's never been
    stamped. This file is itself one of the things a content update
    overwrites, so local and remote naturally converge after applying
    one; nothing extra needs tracking in prefs.json for this."""
    path = os.path.join(app_dir, "content_version.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def fetch_remote_content_version():
    try:
        return int(_http_get_bytes(CONTENT_VERSION_URL, timeout=10).decode("utf-8").strip())
    except Exception:
        return None


def download_and_apply_content_update(app_dir, log=_safe_print):
    """Pulls the whole repo as a zip (simplest way to get a consistent
    snapshot of ui/ + assets/ + the guides in one request, rather than
    walking GitHub's Contents API file by file) and copies just
    CONTENT_PATHS out of it into app_dir, overwriting what's there and
    creating folders that don't exist yet. Returns (ok, new_version,
    error) -- never raises, since this runs both at startup before any
    UI exists and from a background thread once the app is up."""
    try:
        log("Downloading latest app content from GitHub...")
        zip_bytes = _http_get_bytes(CONTENT_ZIP_URL, timeout=60)
    except Exception as e:
        return False, None, f"Couldn't download content update: {e}"

    tmp_dir = tempfile.mkdtemp(prefix="ascendedstt_content_")
    try:
        zip_path = os.path.join(tmp_dir, "content.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        # GitHub's codeload zips wrap everything in one top-level
        # "<repo>-<branch>/" folder -- whatever that folder happens to
        # be named, it's the only entry sitting directly in tmp_dir
        # besides the zip itself.
        extracted_root = next(
            os.path.join(tmp_dir, name) for name in os.listdir(tmp_dir)
            if os.path.isdir(os.path.join(tmp_dir, name))
        )

        for rel_path in CONTENT_PATHS + ["content_version.txt"]:
            src = os.path.join(extracted_root, rel_path)
            dst = os.path.join(app_dir, rel_path)
            if not os.path.exists(src):
                continue
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

        new_version = read_local_content_version(app_dir)
        log(f"Content updated to v{new_version}.")
        return True, new_version, None
    except Exception as e:
        return False, None, f"Couldn't apply content update: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def fetch_latest_release():
    """(tag, html_url) for the newest GitHub Release, or (None, None)
    on any failure -- network hiccups here should never be louder than
    a quiet log line, this app already runs fine without an internet
    connection to spare."""
    try:
        data = json.loads(_http_get_bytes(RELEASES_API_URL, timeout=10).decode("utf-8"))
        return data.get("tag_name"), data.get("html_url")
    except Exception:
        return None, None


def _version_tuple(v):
    v = (v or "").lstrip("vV")
    parts = []
    for piece in v.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(remote, local):
    return _version_tuple(remote) > _version_tuple(local)


def check_required_files(app_dir):
    required = [
        os.path.join(app_dir, "ui", "index.html"),
        os.path.join(app_dir, "ui", "style.css"),
        os.path.join(app_dir, "ui", "app.js"),
        os.path.join(app_dir, "assets", "start_button.png"),
    ]
    missing = [p for p in required if not os.path.exists(p)]

    # A missing ui/assets folder gets treated exactly like an available
    # content update showed up -- fetch it, put it where it belongs,
    # raise whatever folders need raising, same path either way. This
    # only ever runs before any UI exists at all -- _safe_print for the
    # rare case a console happens to be listening (running from source,
    # or launched with output redirected somewhere), a real message box
    # for the truly fatal case below, since that's the only voice
    # guaranteed to actually reach someone who double-clicked the exe
    # with no console and no window standing by yet to speak through.
    if missing:
        _safe_print(f"Required files missing under {app_dir} -- fetching current content from GitHub...")
        ok, _version, error = download_and_apply_content_update(app_dir, log=_safe_print)
        if ok:
            missing = [p for p in required if not os.path.exists(p)]

    if missing:
        message = (
            "Some required files are missing, and fetching them from GitHub "
            "didn't fix it (no internet connection, or GitHub unreachable). This app "
            "expects a specific folder layout - main.py needs 'ui' and 'assets' as "
            "SUBFOLDERS right next to it, not everything dumped in one flat folder.\n\n"
            f"Looking in: {app_dir}\n\n"
            "Missing:\n" + "\n".join(f"  - {p}" for p in missing) + "\n\n"
            "Expected layout:\n"
            f"  {app_dir}\\main.py\n"
            f"  {app_dir}\\ui\\index.html (+ style.css, app.js, config.*, about.*)\n"
            f"  {app_dir}\\assets\\start_button.png (+ all the other .png files)\n\n"
            "Fix this by connecting to the internet and relaunching, or by manually "
            f"copying ui/ and assets/ from the {CONTENT_REPO} repo next to main.py."
        )
        _safe_print("ERROR: " + message)
        try:
            # No console, no Qt window, nothing standing here yet at all
            # -- a native message box is the one voice guaranteed to
            # actually reach someone who just double-clicked the exe.
            # MB_ICONERROR = 0x10.
            ctypes.windll.user32.MessageBoxW(0, message, "Ascended STT - Missing Files", 0x10)
        except Exception:
            pass
        sys.exit(1)


def main():
    app_dir = get_app_dir()
    check_required_files(app_dir)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing Config/About shouldn't quit the app

    icon_path = os.path.join(app_dir, "assets", "app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    bridge = Bridge()
    port, httpd = start_local_server(app_dir)
    bridge.base_url = f"http://127.0.0.1:{port}"
    bridge.httpd = httpd

    window = MainWindow(bridge)
    bridge.main_window = window
    window.view.load(QUrl(f"{bridge.base_url}/ui/index.html"))
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
