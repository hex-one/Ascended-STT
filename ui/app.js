let state = {
  active: false,
  restarting: false,
  tiny: false,
  mode: "toggle",
  hydrated: false,
  started: false,
  overlayMode: false,
};

let bridge = null;

// --- QWebChannel bridge helpers -------------------------------------
// QWebChannel calls are callback-based (bridge.method(args, cb)), not
// Promise-based - these wrap that into the async/await style the rest
// of this file already uses. Same conversation, friendlier shape.
function callBridge(method, ...args) {
  return new Promise((resolve) => {
    bridge[method](...args, (result) => resolve(result));
  });
}

async function callBridgeJSON(method, ...args) {
  const raw = await callBridge(method, ...args);
  return JSON.parse(raw);
}

// Every step that must reach "done" before the loading overlay hides.
// Show the work, don't just ask for trust.
const STARTUP_STEPS = [
  "page_loaded", "bridge_connected", "settings_loaded",
  "mic_finding", "azure_connecting", "mic_connecting", "ready",
];
const stepStatus = {};
STARTUP_STEPS.forEach(s => stepStatus[s] = "pending");

function $(id) { return document.getElementById(id); }

function markStep(stepId, status, message) {
  stepStatus[stepId] = status;
  const li = document.querySelector(`#startupChecklist li[data-step="${stepId}"]`);
  if (!li) return;
  li.classList.remove("pending", "active", "done", "error");
  li.classList.add(status);
  const icon = li.querySelector(".step-icon");
  if (icon) {
    icon.textContent = status === "done" ? "\u2713"
      : status === "error" ? "\u2715"
      : status === "active" ? "\u25CF"
      : "\u25CB";
  }
  if (message) {
    let msgEl = li.querySelector(".step-message");
    if (!msgEl) {
      msgEl = document.createElement("span");
      msgEl.className = "step-message";
      li.appendChild(msgEl);
    }
    msgEl.textContent = ` - ${message}`;
  }
  maybeRevealApp();
}

function maybeRevealApp() {
  const allSettled = STARTUP_STEPS.every(s => stepStatus[s] === "done" || stepStatus[s] === "error");
  if (!allSettled) return;
  const hasError = STARTUP_STEPS.some(s => stepStatus[s] === "error");
  const overlay = $("loadingOverlay");
  if (!overlay || overlay.style.display === "none") return;

  if (hasError) {
    setTimeout(() => { overlay.style.display = "none"; }, 1800);
    return;
  }

  const letsGo = $("letsGoText");
  if (letsGo) letsGo.style.display = "block";
  setTimeout(() => { overlay.style.display = "none"; }, 1500);
}

function updateHintText(enabled, hotkey, mode) {
  const el = $("hintText");
  if (!el) return;
  if (!enabled) {
    el.textContent = "";
    return;
  }
  el.textContent = mode === "push_to_talk"
    ? `Hotkey: hold ${hotkey} to talk`
    : `Hotkey: press ${hotkey} to toggle`;
}

function applyTheme(textColor, fontFamily) {
  const root = document.documentElement.style;
  if (textColor) root.setProperty("--text-color", textColor);
  if (fontFamily) root.setProperty("--font-family", `"${fontFamily}", sans-serif`);
}

function setLight(color) {
  $("light").style.backgroundColor = color;
}

// Overlay Mode's whole point is skipping the background image -- a
// flat panel captures far more reliably in XSOverlay/OVR Toolkit's
// generic window capture than a photo does. This is the one place
// that decision actually gets enforced, so every caller routes
// through here instead of setting body.style.backgroundImage itself.
function applyBackground(dataUri) {
  document.body.style.backgroundImage = state.overlayMode ? "none" : `url('${dataUri}')`;
}

function blinkThenSettle(times, finalColor, onDone) {
  let n = times;
  const green = "#00cc00";
  const off = "#333333";
  function step() {
    if (n <= 0) {
      setLight(finalColor);
      if (onDone) onDone();
      return;
    }
    const current = $("light").style.backgroundColor;
    setLight(current === green ? off : green);
    n -= 1;
    setTimeout(step, 220);
  }
  step();
}

function setTalkImage(active) {
  const img = active ? "../assets/stop_button.png" : "../assets/start_button.png";
  $("talkBtn").style.backgroundImage = `url('${img}')`;
}

function setToggleLed(btnId, isOn) {
  const btn = $(btnId);
  btn.classList.toggle("on", !!isOn);
  btn.setAttribute("aria-pressed", String(!!isOn));
}

function appendLog(line) {
  const box = $("logBox");
  box.textContent += line + "\n";
  box.scrollTop = box.scrollHeight;
}

// --- Handles events pushed from Python via bridge.pushSignal ---
// The frontend listens; the backend speaks whenever something real
// happens, not on a poll.
function handlePush(event, payload) {
  if (event === "status") {
    if (payload.state === "listening") {
      state.active = true;
      $("statusText").textContent = "Listening...";
      setLight("#00cc00");
      setTalkImage(true);
    } else if (payload.state === "paused") {
      state.active = false;
      $("statusText").textContent = "Paused";
      setLight("#cc0000");
      setTalkImage(false);
    } else if (payload.state === "restarting") {
      $("statusText").textContent = "Restarting...";
      setLight("#cccc00");
      setTalkImage(false);
    } else if (payload.state === "reconnecting") {
      $("statusText").textContent = "Reconnecting...";
      setLight("#cccc00");
      setTalkImage(false);
    } else if (payload.state === "reconnected_blink") {
      const finalColor = payload.resume ? "#00cc00" : "#cc0000";
      blinkThenSettle(6, finalColor, () => {
        $("statusText").textContent = payload.resume ? "Listening..." : "Paused";
        setTalkImage(!!payload.resume);
        state.active = !!payload.resume;
      });
    }
  } else if (event === "log") {
    appendLog(payload);
  } else if (event === "last_text") {
    $("lastText").textContent = payload;
  } else if (event === "theme") {
    if (payload.text_color) applyTheme(payload.text_color, null);
    if (payload.font_family) applyTheme(null, payload.font_family);
  } else if (event === "background") {
    if (payload.which === "main") {
      window._mainBackground = payload.data_uri;
      if (!state.tiny) applyBackground(payload.data_uri);
    } else {
      window._tinyBackground = payload.data_uri;
      if (state.tiny) applyBackground(payload.data_uri);
    }
  } else if (event === "overlay_mode") {
    state.overlayMode = !!payload.enabled;
    document.body.classList.toggle("overlay-mode", state.overlayMode);
    applyBackground(state.tiny ? window._tinyBackground : window._mainBackground);
  } else if (event === "startup_step") {
    markStep(payload.step, payload.status, payload.message);
  } else if (event === "hotkey_settings") {
    updateHintText(payload.hotkey_enabled, payload.hotkey, payload.mode);
  } else if (event === "activity_lights") {
    const txLed = $("txLed");
    const rxLed = $("rxLed");
    if (txLed) txLed.classList.toggle("lit", !!payload.tx);
    if (rxLed) rxLed.classList.toggle("lit", !!payload.rx);
  } else if (event === "keep_alive_heartbeat") {
    updateHeartbeatLed(payload.enabled, payload.connected);
  } else if (event === "speech_service_changed") {
    rebuildLanguageDropdowns(payload);
  } else if (event === "app_update_available") {
    showUpdateBanner(payload.version, payload.url);
  }
}

function showUpdateBanner(version, url) {
  $("updateBannerText").textContent = `Update available: ${version}`;
  $("updateBannerBtn").onclick = () => callBridge("open_app_release_page", url);
  $("updateBanner").style.display = "flex";
}

function rebuildLanguageDropdowns(payload) {
  const inputSel = $("inputLang");
  inputSel.innerHTML = "";
  payload.input_language_groups.forEach(g => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = g.group;
    g.options.forEach(l => optgroup.appendChild(new Option(l, l)));
    inputSel.appendChild(optgroup);
  });
  inputSel.value = payload.input_language;

  const outputSel = $("outputLang");
  outputSel.innerHTML = "";
  payload.output_languages.forEach(l => outputSel.add(new Option(l, l)));
  outputSel.value = payload.output_language;
}

function updateHeartbeatLed(enabled, connected) {
  const led = $("heartbeatLed");
  if (!led) return;
  led.classList.remove("disconnected", "heartbeat-pulse");
  if (!enabled) {
    return; // stays dark - Keep Alive is off, nothing to show
  }
  if (!connected) {
    led.classList.add("disconnected");
    return;
  }
  // Brief flash each heartbeat, proving the periodic check is actually
  // running rather than just being assumed to work.
  led.classList.add("heartbeat-pulse");
  setTimeout(() => led.classList.remove("heartbeat-pulse"), 400);
}

async function hydrate() {
  markStep("settings_loaded", "active");
  const s = await callBridgeJSON("get_state");
  if (state.hydrated) return;
  state.hydrated = true;
  state.mode = s.mode;
  state.overlayMode = !!s.overlay_mode_enabled;
  document.body.classList.toggle("overlay-mode", state.overlayMode);

  applyBackground(s.main_background);
  applyTheme(s.text_color, s.text_font_family);
  $("copyrightText").textContent = s.copyright_text;
  updateHintText(s.hotkey_enabled, s.hotkey, s.mode);

  const inputSel = $("inputLang");
  s.input_language_groups.forEach(g => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = g.group;
    g.options.forEach(l => optgroup.appendChild(new Option(l, l)));
    inputSel.appendChild(optgroup);
  });
  inputSel.value = s.input_language;

  const outputSel = $("outputLang");
  s.output_languages.forEach(l => outputSel.add(new Option(l, l)));
  outputSel.value = s.output_language;

  const personaSel = $("personaSelect");
  s.persona_labels.forEach(l => personaSel.add(new Option(l, l)));
  personaSel.value = s.persona_style;

  setToggleLed("uwuBtn", s.uwu_enabled);
  setToggleLed("profanityBtn", s.profanity_allowed);
  setToggleLed("personaBtn", s.persona_enabled);
  setToggleLed("keepAliveBtn", s.keep_alive_enabled);
  setToggleLed("tinyBtn", false);

  window._tinyBackground = s.tiny_background;
  window._mainBackground = s.main_background;

  markStep("settings_loaded", "done");
  completeStartup();
}

function completeStartup() {
  if (state.started) return;
  state.started = true;
  wireEvents();
  callBridge("frontend_ready");
}

function wireEvents() {
  $("talkBtn").addEventListener("click", () => callBridge("toggle_listening"));

  $("updateBannerDismiss").addEventListener("click", () => {
    $("updateBanner").style.display = "none";
  });

  $("inputLang").addEventListener("change", () => {
    callBridge("set_language", $("inputLang").value, $("outputLang").value);
  });
  $("outputLang").addEventListener("change", () => {
    callBridge("set_language", $("inputLang").value, $("outputLang").value);
  });

  $("uwuBtn").addEventListener("click", async () => {
    const on = await callBridge("toggle_uwu");
    setToggleLed("uwuBtn", on);
  });
  $("profanityBtn").addEventListener("click", async () => {
    const on = await callBridge("toggle_profanity");
    setToggleLed("profanityBtn", on);
  });
  $("personaBtn").addEventListener("click", async () => {
    const on = await callBridge("toggle_persona");
    setToggleLed("personaBtn", on);
  });
  $("personaSelect").addEventListener("change", () => {
    callBridge("set_persona_style", $("personaSelect").value);
  });
  $("keepAliveBtn").addEventListener("click", async () => {
    const on = await callBridge("toggle_keep_alive");
    setToggleLed("keepAliveBtn", on);
  });

  $("tinyBtn").addEventListener("click", async () => {
    state.tiny = !state.tiny;
    document.body.classList.toggle("tiny-mode", state.tiny);
    setToggleLed("tinyBtn", state.tiny);
    if (state.tiny) {
      applyBackground(window._tinyBackground);
      await callBridge("enter_tiny_mode");
    } else {
      applyBackground(window._mainBackground);
      await callBridge("enter_full_mode");
    }
  });

  $("powerIcon").addEventListener("click", () => {
    $("shutdownModal").classList.add("visible");
  });
  $("shutdownCancelBtn").addEventListener("click", () => {
    $("shutdownModal").classList.remove("visible");
  });
  $("shutdownOkBtn").addEventListener("click", async () => {
    $("shutdownModal").classList.remove("visible");
    await callBridge("shutdown");
  });
  $("gearIcon").addEventListener("click", () => callBridge("open_config_window"));
  $("heartIcon").addEventListener("click", () => callBridge("open_about_window"));
}

async function attemptStartup() {
  try {
    await Promise.race([
      hydrate(),
      new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 8000)),
    ]);
  } catch (e) {
    const retryBtn = $("loadingRetryBtn");
    if (retryBtn) retryBtn.style.display = "inline-block";
  }
}

function initBridge() {
  new QWebChannel(qt.webChannelTransport, function (channel) {
    bridge = channel.objects.bridge;
    bridge.pushSignal.connect(function (event, payloadJson) {
      const payload = payloadJson && payloadJson !== "null" ? JSON.parse(payloadJson) : null;
      handlePush(event, payload);
    });

    markStep("bridge_connected", "done");
    attemptStartup();

    const retryBtn = $("loadingRetryBtn");
    if (retryBtn) {
      retryBtn.addEventListener("click", () => {
        retryBtn.style.display = "none";
        attemptStartup();
      });
    }
  });
}

markStep("page_loaded", "done");
markStep("bridge_connected", "active");
initBridge();
