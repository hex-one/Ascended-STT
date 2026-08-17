let bridge = null;
let capturedVrCombo = [];
let openvrAvailable = true;

function callBridge(method, ...args) {
  return new Promise((resolve) => {
    bridge[method](...args, (result) => resolve(result));
  });
}

async function callBridgeJSON(method, ...args) {
  const raw = await callBridge(method, ...args);
  return JSON.parse(raw);
}

function $(id) { return document.getElementById(id); }

function updateVrAvailabilityNotice() {
  const el = $("vrAvailability");
  const btn = $("vrCaptureBtn");
  if (!el || !btn) return;
  if (!openvrAvailable) {
    el.className = "vr-availability missing";
    el.textContent = "Missing the 'openvr' package - run: pip install openvr, "
      + "then restart the app to use a VR controller as the hotkey.";
    btn.disabled = true;
  } else {
    el.className = "vr-availability ok";
    el.textContent = "openvr package found - SteamVR still needs to be running to capture.";
    btn.disabled = false;
  }
}

function updateServiceSectionVisibility() {
  const selected = $("speechService").value;
  ["azure", "google", "aws", "whisper", "vosk", "windows"].forEach(key => {
    $(key + "Section").style.display = key === selected ? "block" : "none";
  });
}

function updateHotkeyInputVisibility() {
  const isVR = $("hotkeyInputVR").checked;
  $("keyboardHotkeySection").style.display = isVR ? "none" : "block";
  $("vrHotkeySection").style.display = isVR ? "block" : "none";
  if (isVR) updateVrAvailabilityNotice();
}

function handleVRCapturePush(event, payload) {
  if (event === "vr_capture_update") {
    $("vrCaptureStatus").textContent = "Currently held: " + payload.pressed.join(" + ");
  } else if (event === "vr_capture_done") {
    capturedVrCombo = payload.combo;
    $("vrCaptureStatus").textContent = "";
    $("vrSavedCombo").textContent = "Saved combo: " + payload.labels.join(" + ");
    $("vrCaptureBtn").textContent = "Start Capture";
    $("vrCaptureBtn").disabled = false;
    saveHotkeySettings();
  } else if (event === "vr_capture_error") {
    $("vrCaptureStatus").textContent = "";
    $("hotkeyError").textContent = payload;
    $("vrCaptureBtn").textContent = "Start Capture";
    $("vrCaptureBtn").disabled = false;
  }
}

async function hydrate() {
  const s = await callBridgeJSON("get_config_state");

  const serviceSel = $("speechService");
  serviceSel.innerHTML = "";
  s.speech_services.forEach(svc => serviceSel.add(new Option(svc.label, svc.key)));
  serviceSel.value = s.speech_service;
  updateServiceSectionVisibility();

  $("azureKey").value = s.azure_key;
  $("azureRegion").value = s.azure_region;
  $("googleCredPath").textContent = s.google_credentials_path || "(none selected)";
  $("awsAccessKey").value = s.aws_access_key;
  $("awsSecretKey").value = s.aws_secret_key;
  $("awsRegion").value = s.aws_region;

  const whisperSizeSel = $("whisperModelSize");
  whisperSizeSel.innerHTML = "";
  s.whisper_model_sizes.forEach(size => whisperSizeSel.add(new Option(size, size)));
  whisperSizeSel.value = s.whisper_model_size;
  $("whisperDevice").value = s.whisper_device;

  $("voskModelPath").textContent = s.vosk_model_path || "(none selected)";

  $("textColor").value = s.text_color;
  $("fontFamily").value = s.text_font_family;
  $("mainBgPath").textContent = s.main_bg_path;
  $("tinyBgPath").textContent = s.tiny_bg_path;
  $("overlayMode").checked = s.overlay_mode_enabled;
  $("oscPort").value = s.osc_port;
  $("customEndpoint").value = s.custom_endpoint_id;
  $("hotkeyEnabled").checked = s.hotkey_enabled;
  $("hotkeyKey").value = s.hotkey_key;
  (s.hotkey_mode === "push_to_talk" ? $("hotkeyModePTT") : $("hotkeyModeToggle")).checked = true;
  (s.hotkey_input_type === "vr_controller" ? $("hotkeyInputVR") : $("hotkeyInputKeyboard")).checked = true;
  capturedVrCombo = s.hotkey_vr_combo || [];
  if (capturedVrCombo.length) {
    $("vrSavedCombo").textContent = "Saved combo: " + s.hotkey_vr_combo_labels.join(" + ");
  }
  openvrAvailable = s.openvr_available;
  updateVrAvailabilityNotice();
  updateHotkeyInputVisibility();

  await populateDevices(s.devices, s.device_name);
}

async function populateDevices(devices, deviceName, attempt = 1) {
  if (devices.length === 0 && attempt <= 3) {
    await new Promise(r => setTimeout(r, 400 * attempt));
    const fresh = await callBridgeJSON("get_config_state");
    await populateDevices(fresh.devices, fresh.device_name, attempt + 1);
    return;
  }

  const deviceSel = $("deviceSelect");
  deviceSel.innerHTML = "";
  if (devices.length === 0) {
    deviceSel.add(new Option("No microphones found - try reopening Config", ""));
    return;
  }
  devices.forEach(name => deviceSel.add(new Option(name, name)));
  if (devices.includes(deviceName)) {
    deviceSel.value = deviceName;
  }
}

async function testAndSave(btn, errEl, method, args) {
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Testing connection...";
  errEl.style.color = "";
  errEl.textContent = "";

  const result = await callBridgeJSON(method, ...args);

  btn.disabled = false;
  btn.textContent = originalText;
  if (!result.ok) {
    errEl.textContent = result.error;
  } else {
    errEl.style.color = "green";
    errEl.textContent = "Connected and saved.";
  }
  return result;
}

function wireEvents() {
  $("speechService").addEventListener("change", async () => {
    updateServiceSectionVisibility();
    $("speechServiceError").textContent = "";
    const result = await callBridgeJSON("set_speech_service", $("speechService").value);
    if (!result.ok) $("speechServiceError").textContent = result.error;
  });

  $("showKey").addEventListener("change", () => {
    $("azureKey").type = $("showKey").checked ? "text" : "password";
  });

  $("azureGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "azure"));
  $("googleGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "google"));
  $("awsGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "aws"));
  $("whisperGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "whisper"));
  $("voskGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "vosk"));
  $("windowsGuideBtn").addEventListener("click", () => callBridge("open_setup_guide", "windows"));

  $("saveAzure").addEventListener("click", () => {
    testAndSave($("saveAzure"), $("azureError"), "save_azure_config",
      [$("azureKey").value, $("azureRegion").value]);
  });

  $("browseGoogleCred").addEventListener("click", async () => {
    const path = await callBridgeJSON("browse_google_credentials");
    if (path) {
      $("googleCredPath").textContent = path;
      // Remembered immediately, not just after a successful test below --
      // switching the Speech Service dropdown away and back (or just
      // closing Config) shouldn't lose a path you already picked.
      callBridge("save_speech_field", "google", "credentials_path", path);
    }
  });
  $("saveGoogle").addEventListener("click", () => {
    const path = $("googleCredPath").textContent;
    testAndSave($("saveGoogle"), $("googleError"), "save_google_config",
      [path === "(none selected)" ? "" : path]);
  });

  $("showAwsSecret").addEventListener("change", () => {
    $("awsSecretKey").type = $("showAwsSecret").checked ? "text" : "password";
  });
  $("awsAccessKey").addEventListener("change", () => {
    callBridge("save_speech_field", "aws", "access_key", $("awsAccessKey").value);
  });
  $("awsSecretKey").addEventListener("change", () => {
    callBridge("save_speech_field", "aws", "secret_key", $("awsSecretKey").value);
  });
  $("awsRegion").addEventListener("change", () => {
    callBridge("save_speech_field", "aws", "region", $("awsRegion").value);
  });
  $("saveAws").addEventListener("click", () => {
    testAndSave($("saveAws"), $("awsError"), "save_aws_config",
      [$("awsAccessKey").value, $("awsSecretKey").value, $("awsRegion").value]);
  });

  $("whisperModelSize").addEventListener("change", () => {
    callBridge("save_speech_field", "whisper", "model_size", $("whisperModelSize").value);
  });
  $("whisperDevice").addEventListener("change", () => {
    callBridge("save_speech_field", "whisper", "device", $("whisperDevice").value);
  });
  $("saveWhisper").addEventListener("click", () => {
    testAndSave($("saveWhisper"), $("whisperError"), "save_whisper_config",
      [$("whisperModelSize").value, $("whisperDevice").value]);
  });

  $("browseVoskModel").addEventListener("click", async () => {
    const path = await callBridgeJSON("browse_vosk_model");
    if (path) {
      $("voskModelPath").textContent = path;
      callBridge("save_speech_field", "vosk", "model_path", path);
    }
  });
  $("saveVosk").addEventListener("click", () => {
    const path = $("voskModelPath").textContent;
    testAndSave($("saveVosk"), $("voskError"), "save_vosk_config",
      [path === "(none selected)" ? "" : path]);
  });

  $("testWindows").addEventListener("click", () => {
    testAndSave($("testWindows"), $("windowsError"), "test_windows_speech", []);
  });

  $("textColor").addEventListener("input", () => {
    callBridge("set_text_color", $("textColor").value);
  });
  $("resetTextColor").addEventListener("click", () => {
    $("textColor").value = "#ffffff";
    callBridge("set_text_color", "#ffffff");
  });

  $("fontFamily").addEventListener("change", () => {
    callBridge("set_text_font", $("fontFamily").value);
  });

  $("deviceSelect").addEventListener("change", () => {
    callBridge("set_device", $("deviceSelect").value);
  });

  $("oscPort").addEventListener("change", () => saveOscPort());
  $("customEndpoint").addEventListener("change", () => {
    callBridge("save_custom_endpoint", $("customEndpoint").value);
  });

  $("hotkeyEnabled").addEventListener("change", () => saveHotkeySettings());
  $("hotkeyModeToggle").addEventListener("change", () => saveHotkeySettings());
  $("hotkeyModePTT").addEventListener("change", () => saveHotkeySettings());
  $("hotkeyKey").addEventListener("change", () => saveHotkeySettings());
  $("hotkeyInputKeyboard").addEventListener("change", () => {
    updateHotkeyInputVisibility();
    saveHotkeySettings();
  });
  $("hotkeyInputVR").addEventListener("change", () => {
    updateHotkeyInputVisibility();
    saveHotkeySettings();
  });
  $("vrCaptureBtn").addEventListener("click", () => {
    $("hotkeyError").textContent = "";
    $("vrCaptureStatus").textContent = "Capturing... hold your combo now.";
    $("vrCaptureBtn").textContent = "Capturing...";
    $("vrCaptureBtn").disabled = true;
    callBridge("start_vr_capture");
  });

  $("browseMainBg").addEventListener("click", async () => {
    const result = await callBridgeJSON("browse_background", "main");
    if (result) $("mainBgPath").textContent = result.path;
  });
  $("resetMainBg").addEventListener("click", async () => {
    const result = await callBridgeJSON("reset_background", "main");
    $("mainBgPath").textContent = result.path;
  });

  $("browseTinyBg").addEventListener("click", async () => {
    const result = await callBridgeJSON("browse_background", "tiny");
    if (result) $("tinyBgPath").textContent = result.path;
  });

  $("overlayMode").addEventListener("change", () => callBridge("toggle_overlay_mode"));
  $("resetTinyBg").addEventListener("click", async () => {
    const result = await callBridgeJSON("reset_background", "tiny");
    $("tinyBgPath").textContent = result.path;
  });

  $("checkContentUpdateBtn").addEventListener("click", async () => {
    const btn = $("checkContentUpdateBtn");
    const statusEl = $("updateStatus");
    btn.disabled = true;
    statusEl.textContent = "Checking...";
    const result = await callBridgeJSON("check_for_content_update");
    btn.disabled = false;
    if (!result.ok) {
      statusEl.textContent = result.error;
    } else if (result.updated) {
      statusEl.textContent = `Updated to content v${result.version}. Restart to see everything.`;
    } else {
      statusEl.textContent = `Already up to date (v${result.version}).`;
    }
  });

  $("checkAppUpdateBtn").addEventListener("click", async () => {
    const btn = $("checkAppUpdateBtn");
    const statusEl = $("updateStatus");
    btn.disabled = true;
    statusEl.textContent = "Checking...";
    const result = await callBridgeJSON("check_for_app_update");
    btn.disabled = false;
    if (!result.ok) {
      statusEl.textContent = result.error;
      return;
    }
    if (result.newer_available) {
      statusEl.innerHTML = `v${result.latest_version} is available (you're on v${result.current_version}). `;
      const link = document.createElement("a");
      link.href = "#";
      link.textContent = "Get it";
      link.addEventListener("click", (e) => {
        e.preventDefault();
        callBridge("open_app_release_page", result.url);
      });
      statusEl.appendChild(link);
    } else {
      statusEl.textContent = `Up to date (v${result.current_version}).`;
    }
  });

  $("closeBtn").addEventListener("click", () => {
    // The OSC port field already saves itself on "change" (fires when
    // it loses focus, which happens before this click handler runs -
    // clicking this button moves focus away from whatever was focused
    // first). Re-saving it here too was redundant and, when tested,
    // measurably flaky - chaining two sequential bridge round-trips
    // before actually closing sometimes left the window not closing.
    // A single direct call is simpler and reliable. Don't do a thing
    // twice just because it feels thorough.
    callBridge("close_config_window");
  });
}

async function saveOscPort() {
  const value = $("oscPort").value;
  const result = await callBridgeJSON("save_osc_port", value);
  const errEl = $("oscPortError");
  if (!result.ok) {
    errEl.textContent = result.error;
    $("oscPort").value = result.port;
  } else {
    errEl.textContent = "";
    $("oscPort").value = result.port;
  }
}

async function saveHotkeySettings() {
  const enabled = $("hotkeyEnabled").checked;
  const mode = $("hotkeyModePTT").checked ? "push_to_talk" : "toggle";
  const inputType = $("hotkeyInputVR").checked ? "vr_controller" : "keyboard";
  const key = $("hotkeyKey").value;
  const result = await callBridgeJSON(
    "save_hotkey_settings", enabled, mode, inputType, key, JSON.stringify(capturedVrCombo)
  );
  $("hotkeyError").textContent = result.ok ? "" : result.error;
}

new QWebChannel(qt.webChannelTransport, async function (channel) {
  bridge = channel.objects.bridge;
  bridge.pushSignal.connect(function (event, payloadJson) {
    const payload = payloadJson && payloadJson !== "null" ? JSON.parse(payloadJson) : null;
    handleVRCapturePush(event, payload);
  });
  await hydrate();
  wireEvents();
});
