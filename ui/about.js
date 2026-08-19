let bridge = null;

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

new QWebChannel(qt.webChannelTransport, async function (channel) {
  bridge = channel.objects.bridge;

  const info = await callBridgeJSON("get_about_info");
  $("appName").textContent = info.app_name;
  $("credits").textContent = info.credits;
  $("donateBlurb").textContent = info.donate_blurb;

  // Tells the Python side how tall the text actually turned out to be,
  // so the window can size itself to fit -- rather than a fixed height
  // someone has to remember to bump by hand every time this text grows.
  // Read one frame later (requestAnimationFrame) so the browser's
  // already laid out the text we just set, not whatever it measured
  // before that.
  requestAnimationFrame(() => {
    callBridge("report_about_content_height", document.body.scrollHeight);
  });

  $("groupBtn").addEventListener("click", () => callBridge("open_group_link"));
  $("discordBtn").addEventListener("click", () => callBridge("open_discord_link"));
  $("donateBtn").addEventListener("click", () => callBridge("open_donation_link"));
  $("closeBtn").addEventListener("click", () => callBridge("close_about_window"));
});
