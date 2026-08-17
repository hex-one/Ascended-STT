"""
speech_engines.py

Six ways to turn a voice into text, behind one shape. main.py's Bridge
never talks to Azure, Google, AWS, Whisper, Vosk, or Windows directly --
it talks to whichever SpeechEngine is currently selected, and every
engine answers the same questions the same way: can you translate, do
you have real dialects or just languages, does "Keep Alive" mean
anything for you. Swapping engines is picking a different subclass,
not rewriting the pipeline underneath it.

--------------------------------------------------------------------------
HONESTY NOTES, since these six are not actually equivalent underneath:

- Azure, Google, and AWS are real cloud streaming services -- a live
  connection that can go idle and needs Keep Alive's proactive refresh
  (see main.py's _keep_alive_tick for why that matters). Only Azure is
  verified against a real account in this codebase; Google and AWS are
  built correctly against their documented SDK shapes, but nobody here
  has tested them against real credentials. Google and AWS also don't
  do inline translation the way Azure does -- that's a genuinely
  separate service on both platforms, out of scope for this pass.

- Whisper isn't a streaming API at all. It transcribes a chunk of
  audio you hand it, once, all at once. WhisperEngine buffers audio and
  uses a simple RMS-energy silence check to decide when a sentence is
  probably over, then transcribes that chunk on a background thread.
  That's a real, working design -- not a hack -- but it's genuinely
  different from "the recognizer tells you the instant it's sure,"
  which is what Azure/Google/AWS actually do. Whisper can translate,
  but only INTO English, never to an arbitrary target language.

- Vosk is a real streaming recognizer (AcceptWaveform), same shape as
  the cloud engines, just entirely local. No translation, and language
  is fixed by whichever model folder you point it at -- not a runtime
  dropdown choice.

- Windows Speech Recognition (SAPI) is the odd one out on purpose: it
  manages its own microphone input through Windows' own audio stack
  rather than accepting audio we captured ourselves, because that's
  the correct way to use SAPI, not a shortcut. See
  manages_own_audio_capture below. Language follows whatever's set as
  the Windows-wide default speech recognition language (Settings ->
  Time & Language -> Speech) -- not independently selectable here.

None of the six change how profanity filtering works from the user's
side: every one of them is configured to return raw, unfiltered text
(Azure already did; Google's profanity_filter is explicitly turned
off; AWS/Whisper/Vosk/Windows have no service-side filter to fight in
the first place). The existing app-level profanity toggle in
_process_and_send is the one place that decision actually gets made,
same as it always was -- consistent, not duplicated six different ways.
--------------------------------------------------------------------------
"""

import os
import time
import queue
import threading

import numpy as np

SAMPLE_RATE = 16000  # matches main.py's SAMPLE_RATE -- every engine gets 16kHz mono PCM16


class SpeechEngine:
    """Base shape every engine implements. See the module docstring for
    what's genuinely different between them and why."""

    key = "override-me"
    label = "Override Me"

    # Can this engine translate speech into a DIFFERENT output language
    # than what was spoken? If True, output_languages() returns more
    # than just "no translation."
    supports_translation = False

    # Does the input-language list have real regional dialects (Azure's
    # "English (US)" vs "English (UK)"), or just plain languages?
    dialect_granular = True

    # Is there a live connection here that can go idle and needs
    # Keep Alive's proactive refresh? False for anything local -- a
    # loaded model in memory has no connection to go stale.
    supports_keep_alive = True

    # If True, this engine opens and manages the microphone itself
    # (through its own platform APIs) rather than receiving audio
    # Bridge captured via sounddevice. Only Windows Speech Recognition
    # sets this -- see the module docstring for why.
    manages_own_audio_capture = False

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        """Begins a recognition session. on_recognized(text) fires for
        every finalized utterance; on_partial() fires (no argument) on
        any interim activity, purely to drive the RX activity light --
        nothing reads its return value or displays partial text.
        on_disconnect(reason: str) fires if a live connection drops
        unexpectedly -- only the three cloud engines ever call it; the
        three local ones have no connection to drop, so it's simply
        never invoked for them. This is what main.py's Keep Alive
        reconnect logic actually listens for. Returns an opaque session
        object this engine's own feed_audio()/stop() know how to use."""
        raise NotImplementedError

    def feed_audio(self, session, pcm16_bytes):
        """Push one chunk of 16kHz mono PCM16 audio into the session.
        Never called for manages_own_audio_capture engines."""
        raise NotImplementedError

    def stop(self, session):
        raise NotImplementedError

    def test_connection(self):
        """(ok, error_message) -- error_message is None on success."""
        raise NotImplementedError

    def input_languages(self):
        """Either {label: code} (flat) or [(group_name, {label: code})]
        (grouped, Azure-style) depending on dialect_granular."""
        raise NotImplementedError

    def output_languages(self):
        """{label: code}. Always includes a "no translation" entry."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Azure Speech Services
# ---------------------------------------------------------------------------

class AzureEngine(SpeechEngine):
    """The original engine, moved here unchanged in behavior -- see
    main.py's INPUT_LANGUAGE_GROUPS/OUTPUT_LANGUAGES for the actual
    language data, still owned there since Bridge already had it built
    and tested. This class just wraps the same Azure SDK calls that
    used to live directly in Bridge._build_pipeline."""

    key = "azure"
    label = "Azure Speech Services"
    supports_translation = True
    dialect_granular = True
    supports_keep_alive = True

    def __init__(self, get_key_region, input_language_groups, output_languages):
        # get_key_region is a callable returning (key, region) fresh
        # each time, since Config can update these live -- never cache
        # a stale key/region across calls.
        self._get_key_region = get_key_region
        self._input_language_groups = input_language_groups
        self._output_languages = output_languages

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        import azure.cognitiveservices.speech as speechsdk

        key, region = self._get_key_region()
        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=SAMPLE_RATE, bits_per_sample=16, channels=1
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format=stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        is_translation = output_language != "none"

        if is_translation:
            translation_config = speechsdk.translation.SpeechTranslationConfig(
                subscription=key, region=region
            )
            translation_config.speech_recognition_language = input_language
            translation_config.add_target_language(output_language)
            translation_config.set_profanity(speechsdk.ProfanityOption.Raw)
            recognizer = speechsdk.translation.TranslationRecognizer(
                translation_config=translation_config, audio_config=audio_config
            )

            def _on_recognized(evt):
                try:
                    translated = evt.result.translations[output_language]
                except (KeyError, TypeError):
                    translated = None
                if translated:
                    on_recognized(translated)

            recognizer.recognized.connect(_on_recognized)
        else:
            speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
            speech_config.speech_recognition_language = input_language
            speech_config.set_profanity(speechsdk.ProfanityOption.Raw)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, audio_config=audio_config
            )
            recognizer.recognized.connect(
                lambda evt: evt.result.text and on_recognized(evt.result.text)
            )

        if on_partial:
            recognizer.recognizing.connect(lambda evt: on_partial())

        if on_disconnect:
            recognizer.canceled.connect(
                lambda evt: on_disconnect(f"canceled: {evt.reason}"
                                           + (f" -- {evt.error_details}"
                                              if evt.reason == speechsdk.CancellationReason.Error else ""))
            )
            recognizer.session_stopped.connect(lambda evt: on_disconnect("session_stopped"))

        recognizer.start_continuous_recognition()
        return {"push_stream": push_stream, "recognizer": recognizer}

    def feed_audio(self, session, pcm16_bytes):
        session["push_stream"].write(pcm16_bytes)

    def stop(self, session):
        try:
            session["recognizer"].stop_continuous_recognition()
        except Exception:
            pass
        try:
            session["push_stream"].close()
        except Exception:
            pass

    def test_connection(self):
        import urllib.request
        import urllib.error

        key, region = self._get_key_region()
        if not key or not region:
            return False, "Azure key/region not set."
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
                return False, "Azure rejected this key -- double check the key and region."
            return False, f"Azure returned an error (HTTP {e.code})."
        except urllib.error.URLError as e:
            return False, f"Couldn't reach Azure: {e.reason}"
        except Exception as e:
            return False, f"Connection test failed: {e}"

    def input_languages(self):
        return self._input_language_groups

    def output_languages(self):
        return self._output_languages


# ---------------------------------------------------------------------------
# Google Cloud Speech-to-Text
# ---------------------------------------------------------------------------

# A practical, non-exhaustive subset of Google Cloud Speech-to-Text's
# supported locales -- the major languages and their most common
# regional variants. Google's actual list is considerably longer and
# does shift over time; check cloud.google.com/speech-to-text/docs/languages
# for the current, complete one. Adding more here is just adding dict
# entries -- nothing else needs to change.
GOOGLE_INPUT_LANGUAGE_GROUPS = [
    ("Arabic", {"Arabic (Egypt)": "ar-EG", "Arabic (Saudi Arabia)": "ar-SA"}),
    ("Chinese", {"Chinese (Mandarin, Simplified)": "cmn-Hans-CN", "Chinese (Cantonese)": "yue-Hant-HK"}),
    ("Dutch", {"Dutch (Netherlands)": "nl-NL"}),
    ("English", {
        "English (US)": "en-US", "English (UK)": "en-GB", "English (Australia)": "en-AU",
        "English (Canada)": "en-CA", "English (India)": "en-IN",
    }),
    ("French", {"French (France)": "fr-FR", "French (Canada)": "fr-CA"}),
    ("German", {"German (Germany)": "de-DE"}),
    ("Hindi", {"Hindi (India)": "hi-IN"}),
    ("Italian", {"Italian (Italy)": "it-IT"}),
    ("Japanese", {"Japanese (Japan)": "ja-JP"}),
    ("Korean", {"Korean (Korea)": "ko-KR"}),
    ("Polish", {"Polish (Poland)": "pl-PL"}),
    ("Portuguese", {"Portuguese (Brazil)": "pt-BR", "Portuguese (Portugal)": "pt-PT"}),
    ("Russian", {"Russian (Russia)": "ru-RU"}),
    ("Spanish", {
        "Spanish (Spain)": "es-ES", "Spanish (Mexico)": "es-MX", "Spanish (US)": "es-US",
    }),
    ("Swedish", {"Swedish (Sweden)": "sv-SE"}),
    ("Turkish", {"Turkish (Turkey)": "tr-TR"}),
    ("Ukrainian", {"Ukrainian (Ukraine)": "uk-UA"}),
    ("Vietnamese", {"Vietnamese (Vietnam)": "vi-VN"}),
]


class GoogleEngine(SpeechEngine):
    """Google Cloud Speech-to-Text, streaming mode. Auth is a service
    account JSON key file -- the standard way a desktop app talks to
    Google Cloud APIs (see GOOGLE_SETUP.md). Translation isn't
    supported here on purpose: Google Cloud's translation is a
    genuinely separate API (Cloud Translation), and chaining two
    different Google services together was more scope than this pass
    needed -- output is transcription only, same language you spoke.

    Built correctly against google-cloud-speech's documented streaming
    shape. Not verified against a real Google Cloud account -- nobody
    building this had credentials to test with. If something's off,
    it's the untested edge, not a guess at the wrong API entirely.
    """

    key = "google"
    label = "Google Cloud Speech-to-Text"
    supports_translation = False
    dialect_granular = True
    supports_keep_alive = True

    def __init__(self, get_credentials_path):
        self._get_credentials_path = get_credentials_path

    def _make_client(self):
        from google.cloud import speech
        from google.oauth2 import service_account

        path = self._get_credentials_path()
        if not path or not os.path.exists(path):
            raise RuntimeError("No Google Cloud service account key file set.")
        credentials = service_account.Credentials.from_service_account_file(path)
        return speech.SpeechClient(credentials=credentials), speech

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        client, speech = self._make_client()

        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE,
            language_code=input_language,
            profanity_filter=False,  # raw output -- the app's own toggle handles censoring
        )
        streaming_config = speech.StreamingRecognitionConfig(config=config, interim_results=True)

        audio_queue = queue.Queue()
        stop_event = threading.Event()

        def request_generator():
            yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
            while not stop_event.is_set():
                chunk = audio_queue.get()
                if chunk is None:
                    return
                yield speech.StreamingRecognizeRequest(audio_content=chunk)

        def response_loop():
            try:
                responses = client.streaming_recognize(requests=request_generator())
                for response in responses:
                    if stop_event.is_set():
                        return
                    for result in response.results:
                        if not result.alternatives:
                            continue
                        if result.is_final:
                            on_recognized(result.alternatives[0].transcript)
                        elif on_partial:
                            on_partial()
                # The generator ending on its own (not via stop_event) is
                # itself a disconnect -- Google's own streaming API caps
                # a single stream at a few minutes regardless of activity,
                # so this is an EXPECTED, not exceptional, way for a
                # session to end. Same reconnect path either way.
                if not stop_event.is_set() and on_disconnect:
                    on_disconnect("stream ended")
            except Exception as e:
                if not stop_event.is_set() and on_disconnect:
                    on_disconnect(f"stream error: {e}")

        thread = threading.Thread(target=response_loop, daemon=True)
        thread.start()
        return {"queue": audio_queue, "stop_event": stop_event, "thread": thread}

    def feed_audio(self, session, pcm16_bytes):
        session["queue"].put(pcm16_bytes)

    def stop(self, session):
        session["stop_event"].set()
        session["queue"].put(None)

    def test_connection(self):
        path = self._get_credentials_path()
        if not path:
            return False, "No service account key file selected."
        if not os.path.exists(path):
            return False, f"File not found: {path}"
        try:
            client, speech = self._make_client()
            # A minimal real call against the API -- list of supported
            # recognizers/models isn't a thing to check cheaply, so this
            # runs a trivial synchronous recognize against a silent,
            # near-empty audio buffer. It costs effectively nothing and
            # fails immediately (and informatively) on bad credentials,
            # a disabled API, or billing not enabled -- all real,
            # distinct failure modes worth surfacing separately from a
            # generic exception.
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=SAMPLE_RATE,
                language_code="en-US",
            )
            silence = b"\x00\x00" * 1600  # 0.1s of silence at 16kHz mono
            audio = speech.RecognitionAudio(content=silence)
            client.recognize(config=config, audio=audio, timeout=8)
            return True, None
        except Exception as e:
            return False, f"Google Cloud connection test failed: {e}"

    def input_languages(self):
        return GOOGLE_INPUT_LANGUAGE_GROUPS

    def output_languages(self):
        return {"No translation (send as heard)": "none"}


# ---------------------------------------------------------------------------
# AWS Transcribe
# ---------------------------------------------------------------------------

# Same honesty as Google's list above -- a practical subset of AWS
# Transcribe's supported streaming language codes, not a guaranteed
# exhaustive/current one. Check docs.aws.amazon.com/transcribe for the
# full, current list.
AWS_INPUT_LANGUAGE_GROUPS = [
    ("English", {
        "English (US)": "en-US", "English (UK)": "en-GB", "English (Australia)": "en-AU",
        "English (India)": "en-IN",
    }),
    ("French", {"French (France)": "fr-FR", "French (Canada)": "fr-CA"}),
    ("German", {"German (Germany)": "de-DE"}),
    ("Italian", {"Italian (Italy)": "it-IT"}),
    ("Japanese", {"Japanese (Japan)": "ja-JP"}),
    ("Korean", {"Korean (Korea)": "ko-KR"}),
    ("Portuguese", {"Portuguese (Brazil)": "pt-BR"}),
    ("Spanish", {"Spanish (Spain)": "es-ES", "Spanish (US)": "es-US"}),
    ("Chinese", {"Chinese (Mandarin, Simplified)": "zh-CN"}),
    ("Hindi", {"Hindi (India)": "hi-IN"}),
]


class AWSEngine(SpeechEngine):
    """AWS Transcribe, real-time streaming via the `amazon-transcribe`
    SDK -- deliberately not boto3's `transcribe` client, which only
    does batch jobs against files already sitting in S3, the wrong
    shape entirely for a live mic. No translation: AWS Transcribe is
    transcription-only, same as Google -- Amazon Translate is a
    separate service, out of scope here for the same reason chaining
    Google's two services was.

    Built correctly against amazon-transcribe's documented streaming
    shape. Not verified against a real AWS account -- nobody building
    this had credentials to test with.
    """

    key = "aws"
    label = "AWS Transcribe"
    supports_translation = False
    dialect_granular = True
    supports_keep_alive = True

    def __init__(self, get_credentials):
        # get_credentials() -> (access_key, secret_key, region)
        self._get_credentials = get_credentials

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        access_key, secret_key, region = self._get_credentials()
        audio_queue = queue.Queue()
        stop_event = threading.Event()
        loop_holder = {}

        def thread_main():
            import asyncio

            async def run():
                from amazon_transcribe.client import TranscribeStreamingClient
                from amazon_transcribe.handlers import TranscriptResultStreamHandler

                # amazon-transcribe reads credentials the same way the
                # rest of the AWS SDK ecosystem does -- process
                # environment variables, set fresh right before this
                # client is created rather than trusting whatever an
                # earlier session might have left behind.
                os.environ["AWS_ACCESS_KEY_ID"] = access_key
                os.environ["AWS_SECRET_ACCESS_KEY"] = secret_key

                client = TranscribeStreamingClient(region=region)
                stream = await client.start_stream_transcription(
                    language_code=input_language,
                    media_sample_rate_hz=SAMPLE_RATE,
                    media_encoding="pcm",
                )

                class Handler(TranscriptResultStreamHandler):
                    async def handle_transcript_event(self, transcript_event):
                        for result in transcript_event.transcript.results:
                            if not result.alternatives:
                                continue
                            if not result.is_partial:
                                on_recognized(result.alternatives[0].transcript)
                            elif on_partial:
                                on_partial()

                handler = Handler(stream.output_stream)

                async def write_chunks():
                    loop = asyncio.get_event_loop()
                    while not stop_event.is_set():
                        chunk = await loop.run_in_executor(None, audio_queue.get)
                        if chunk is None:
                            break
                        await stream.input_stream.send_audio_event(audio_chunk=chunk)
                    await stream.input_stream.end_stream()

                await asyncio.gather(write_chunks(), handler.handle_events())

            loop = asyncio.new_event_loop()
            loop_holder["loop"] = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run())
                if not stop_event.is_set() and on_disconnect:
                    on_disconnect("stream ended")
            except Exception as e:
                if not stop_event.is_set() and on_disconnect:
                    on_disconnect(f"stream error: {e}")

        thread = threading.Thread(target=thread_main, daemon=True)
        thread.start()
        return {"queue": audio_queue, "stop_event": stop_event, "thread": thread}

    def feed_audio(self, session, pcm16_bytes):
        session["queue"].put(pcm16_bytes)

    def stop(self, session):
        session["stop_event"].set()
        session["queue"].put(None)

    def test_connection(self):
        access_key, secret_key, region = self._get_credentials()
        if not access_key or not secret_key or not region:
            return False, "Access Key ID, Secret Access Key, and Region are all required."
        try:
            import boto3
            # STS's get_caller_identity is the standard lightweight
            # "are these credentials real" check -- doesn't touch
            # Transcribe itself, doesn't cost anything meaningful, and
            # works against any valid IAM credentials regardless of
            # which specific services they're allowed to use.
            client = boto3.client(
                "sts", region_name=region,
                aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            )
            client.get_caller_identity()
            return True, None
        except Exception as e:
            return False, f"AWS connection test failed: {e}"

    def input_languages(self):
        return AWS_INPUT_LANGUAGE_GROUPS

    def output_languages(self):
        return {"No translation (send as heard)": "none"}


# ---------------------------------------------------------------------------
# Whisper (local, via faster-whisper)
# ---------------------------------------------------------------------------

# Whisper's real, stable language set -- unlike the cloud services'
# locale lists, this one doesn't drift over time the way a hosted API's
# supported-region list can, so it's listed in full rather than as a
# "practical subset." Flat, not grouped -- Whisper works at the
# language level (bare "en"), it doesn't distinguish "English (US)"
# from "English (UK)" the way the cloud dialect-granular services do.
WHISPER_LANGUAGES = {
    "Auto-detect": "auto",
    "Afrikaans": "af", "Albanian": "sq", "Amharic": "am", "Arabic": "ar", "Armenian": "hy",
    "Assamese": "as", "Azerbaijani": "az", "Bashkir": "ba", "Basque": "eu", "Belarusian": "be",
    "Bengali": "bn", "Bosnian": "bs", "Breton": "br", "Bulgarian": "bg", "Burmese": "my",
    "Catalan": "ca", "Chinese": "zh", "Croatian": "hr", "Czech": "cs", "Danish": "da",
    "Dutch": "nl", "English": "en", "Estonian": "et", "Faroese": "fo", "Finnish": "fi",
    "French": "fr", "Galician": "gl", "Georgian": "ka", "German": "de", "Greek": "el",
    "Gujarati": "gu", "Haitian Creole": "ht", "Hausa": "ha", "Hawaiian": "haw", "Hebrew": "he",
    "Hindi": "hi", "Hungarian": "hu", "Icelandic": "is", "Indonesian": "id", "Italian": "it",
    "Japanese": "ja", "Javanese": "jw", "Kannada": "kn", "Kazakh": "kk", "Khmer": "km",
    "Korean": "ko", "Lao": "lo", "Latin": "la", "Latvian": "lv", "Lingala": "ln",
    "Lithuanian": "lt", "Luxembourgish": "lb", "Macedonian": "mk", "Malagasy": "mg",
    "Malay": "ms", "Malayalam": "ml", "Maltese": "mt", "Maori": "mi", "Marathi": "mr",
    "Mongolian": "mn", "Nepali": "ne", "Norwegian": "no", "Nynorsk": "nn", "Occitan": "oc",
    "Pashto": "ps", "Persian": "fa", "Polish": "pl", "Portuguese": "pt", "Punjabi": "pa",
    "Romanian": "ro", "Russian": "ru", "Sanskrit": "sa", "Serbian": "sr", "Shona": "sn",
    "Sindhi": "sd", "Sinhala": "si", "Slovak": "sk", "Slovenian": "sl", "Somali": "so",
    "Spanish": "es", "Sundanese": "su", "Swahili": "sw", "Swedish": "sv", "Tagalog": "tl",
    "Tajik": "tg", "Tamil": "ta", "Tatar": "tt", "Telugu": "te", "Thai": "th",
    "Tibetan": "bo", "Turkish": "tr", "Turkmen": "tk", "Ukrainian": "uk", "Urdu": "ur",
    "Uzbek": "uz", "Vietnamese": "vi", "Welsh": "cy", "Yiddish": "yi", "Yoruba": "yo",
}

WHISPER_MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


class WhisperEngine(SpeechEngine):
    """Local, offline, via faster-whisper -- no account, no cloud, no
    key. See the module docstring for the honest picture: this isn't a
    streaming recognizer, it's a chunk-and-transcribe pipeline with a
    simple energy-based silence detector deciding where one utterance
    ends and the next begins. Good accuracy, real latency trade-off
    versus the cloud engines' "recognized the instant you paused."

    Can translate, but only speech -> English (task="translate" is
    Whisper's own built-in mode) -- never an arbitrary target language.
    """

    key = "whisper"
    label = "Whisper (local)"
    supports_translation = True  # English-only, see output_languages()
    dialect_granular = False
    supports_keep_alive = False  # a loaded model has no connection to go stale

    # Simple RMS-energy silence heuristic -- not a trained voice
    # activity detector, just "is this chunk louder than ambient
    # noise." Good enough for deciding utterance boundaries in a quiet
    # room; a noisy mic environment may need retuning these constants.
    SILENCE_RMS_THRESHOLD = 400
    SILENCE_HANGOVER_MS = 700       # how long a pause has to last before we call the utterance done
    MIN_UTTERANCE_MS = 300          # ignore anything shorter than this -- avoids transcribing noise blips
    MAX_UTTERANCE_MS = 30_000       # hard cap so a stuck-open mic can't buffer forever

    def __init__(self, get_config):
        # get_config() -> {"model_size": str, "device": "cpu"|"cuda"}
        self._get_config = get_config
        self._model = None
        self._model_key = None

    def _ensure_model(self):
        config = self._get_config()
        model_size = config.get("model_size", "base")
        device = config.get("device", "cpu")
        model_key = (model_size, device)
        if self._model is None or self._model_key != model_key:
            from faster_whisper import WhisperModel
            compute_type = "int8" if device == "cpu" else "float16"
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self._model_key = model_key
        return self._model

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        # on_disconnect is accepted for interface consistency but never
        # called here -- a loaded local model has no connection to drop.
        model = self._ensure_model()
        session = {
            "model": model,
            "buffer": bytearray(),
            "silence_ms": 0.0,
            "speaking": False,
            "utterance_ms": 0.0,
            "lock": threading.Lock(),
            "language": None if input_language in (None, "auto") else input_language,
            "task": "translate" if output_language == "en" else "transcribe",
            "on_recognized": on_recognized,
            "on_partial": on_partial,
        }
        return session

    def feed_audio(self, session, pcm16_bytes):
        audio = np.frombuffer(pcm16_bytes, dtype=np.int16)
        if len(audio) == 0:
            return
        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
        chunk_ms = (len(audio) / SAMPLE_RATE) * 1000.0
        is_silent = rms < self.SILENCE_RMS_THRESHOLD

        with session["lock"]:
            session["buffer"].extend(pcm16_bytes)
            session["utterance_ms"] += chunk_ms

            if is_silent:
                session["silence_ms"] += chunk_ms
            else:
                session["silence_ms"] = 0.0
                session["speaking"] = True
                if session["on_partial"]:
                    session["on_partial"]()

            boundary_hit = (
                session["speaking"]
                and session["silence_ms"] >= self.SILENCE_HANGOVER_MS
                and session["utterance_ms"] >= self.MIN_UTTERANCE_MS
            )
            overflow = session["utterance_ms"] >= self.MAX_UTTERANCE_MS

            if boundary_hit or overflow:
                chunk = bytes(session["buffer"])
                session["buffer"] = bytearray()
                session["speaking"] = False
                session["silence_ms"] = 0.0
                session["utterance_ms"] = 0.0
            else:
                chunk = None

        if chunk:
            threading.Thread(
                target=self._transcribe_chunk, args=(session, chunk), daemon=True
            ).start()

    def _transcribe_chunk(self, session, pcm_bytes):
        audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            segments, _info = session["model"].transcribe(
                audio_np, language=session["language"], task=session["task"],
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                session["on_recognized"](text)
        except Exception:
            pass  # a single failed chunk shouldn't take down the whole session

    def stop(self, session):
        pass  # nothing to close -- the model stays loaded for next time, buffer just gets dropped

    def test_connection(self):
        try:
            self._ensure_model()
            return True, None
        except Exception as e:
            return False, f"Couldn't load the Whisper model: {e}"

    def input_languages(self):
        return WHISPER_LANGUAGES

    def output_languages(self):
        return {"No translation (send as heard)": "none", "English (translate)": "en"}


# ---------------------------------------------------------------------------
# Vosk (local)
# ---------------------------------------------------------------------------

class VoskEngine(SpeechEngine):
    """Local, offline, genuinely streaming (AcceptWaveform is the real
    thing, same shape as the cloud engines' incremental recognition --
    not a chunk-and-transcribe workaround like Whisper needed). Trades
    some accuracy for that: lighter weight, real-time-friendly, runs
    fine on modest hardware. Language is fixed by whichever model
    folder you point it at -- see VOSK_SETUP.md -- not a runtime
    dropdown, since a Vosk model IS a specific language.
    """

    key = "vosk"
    label = "Vosk (local)"
    supports_translation = False
    dialect_granular = False
    supports_keep_alive = False

    def __init__(self, get_model_path):
        self._get_model_path = get_model_path
        self._model = None
        self._model_path = None

    def _ensure_model(self):
        path = self._get_model_path()
        if not path or not os.path.isdir(path):
            raise RuntimeError("No valid Vosk model folder set.")
        if self._model is None or self._model_path != path:
            import vosk
            vosk.SetLogLevel(-1)  # Kaldi's own logging is noisy by default -- silence it
            self._model = vosk.Model(path)
            self._model_path = path
        return self._model

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        # on_disconnect is accepted for interface consistency but never
        # called here -- a loaded local model has no connection to drop.
        import json as jsonlib
        from vosk import KaldiRecognizer

        model = self._ensure_model()
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        recognizer.SetWords(False)
        return {
            "recognizer": recognizer, "json": jsonlib,
            "on_recognized": on_recognized, "on_partial": on_partial,
        }

    def feed_audio(self, session, pcm16_bytes):
        recognizer = session["recognizer"]
        if recognizer.AcceptWaveform(pcm16_bytes):
            result = session["json"].loads(recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                session["on_recognized"](text)
        elif session["on_partial"]:
            partial = session["json"].loads(recognizer.PartialResult())
            if partial.get("partial", "").strip():
                session["on_partial"]()

    def stop(self, session):
        pass  # nothing to close -- the model stays loaded for next time

    def test_connection(self):
        try:
            self._ensure_model()
            return True, None
        except Exception as e:
            return False, f"Couldn't load the Vosk model: {e}"

    def input_languages(self):
        return {"Determined by the model folder you selected below": "model_determined"}

    def output_languages(self):
        return {"No translation (send as heard)": "none"}


# ---------------------------------------------------------------------------
# Windows Speech Recognition (SAPI)
# ---------------------------------------------------------------------------

class WindowsEngine(SpeechEngine):
    """Local, offline, already sitting on every Windows 10/11 install --
    no download, no model, no account. Uses SAPI (via pywin32's
    win32com), which manages its own microphone input directly through
    Windows' own audio stack -- see manages_own_audio_capture and the
    module docstring for why this one doesn't take fed audio like the
    other five. Language follows whatever's set as the Windows-wide
    default speech recognition language (Settings -> Time & Language ->
    Speech) -- there's no per-session language override here.
    """

    key = "windows"
    label = "Windows Speech Recognition"
    supports_translation = False
    dialect_granular = False
    supports_keep_alive = False
    manages_own_audio_capture = True

    def start(self, device_index, input_language, output_language, on_recognized,
              on_disconnect=None, on_partial=None):
        # on_disconnect is accepted for interface consistency but never
        # called here -- a loaded local model has no connection to drop.
        stop_event = threading.Event()
        ready_event = threading.Event()
        state = {"error": None}

        thread = threading.Thread(
            target=self._thread_main, args=(stop_event, ready_event, state, on_recognized), daemon=True
        )
        thread.start()
        ready_event.wait(timeout=10)
        if state["error"]:
            raise RuntimeError(state["error"])

        return {"stop_event": stop_event, "thread": thread}

    def _thread_main(self, stop_event, ready_event, state, on_recognized):
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                context = win32com.client.Dispatch("SAPI.SpSharedRecoContext")
                grammar = context.CreateGrammar()
                grammar.DictationSetState(1)  # SGDSActive

                class _Events:
                    def OnRecognition(self, StreamNumber, StreamPosition, RecognitionType, Result):
                        try:
                            result = win32com.client.Dispatch(Result)
                            text = result.PhraseInfo.GetText()
                        except Exception:
                            text = None
                        if text:
                            on_recognized(text)

                handler = win32com.client.WithEvents(context, _Events)
                ready_event.set()

                while not stop_event.is_set():
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.05)

                grammar.DictationSetState(0)  # SGDSInactive
            finally:
                pythoncom.CoUninitialize()
        except Exception as e:
            state["error"] = str(e)
            ready_event.set()

    def feed_audio(self, session, pcm16_bytes):
        pass  # never called -- manages_own_audio_capture is True

    def stop(self, session):
        session["stop_event"].set()

    def test_connection(self):
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                context = win32com.client.Dispatch("SAPI.SpSharedRecoContext")
                grammar = context.CreateGrammar()
                grammar.DictationSetState(1)
                grammar.DictationSetState(0)
                return True, None
            finally:
                pythoncom.CoUninitialize()
        except Exception as e:
            return False, (
                "Couldn't reach Windows Speech Recognition. Make sure it's set up "
                f"under Settings -> Time & Language -> Speech. ({e})"
            )

    def input_languages(self):
        return {"System default (set in Windows Settings)": "system_default"}

    def output_languages(self):
        return {"No translation (send as heard)": "none"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ENGINE_ORDER = ["azure", "google", "aws", "whisper", "vosk", "windows"]
