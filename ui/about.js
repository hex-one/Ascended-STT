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

  $("groupBtn").addEventListener("click", () => callBridge("open_group_link"));
  $("discordBtn").addEventListener("click", () => callBridge("open_discord_link"));
  $("donateBtn").addEventListener("click", () => callBridge("open_donation_link"));
  $("closeBtn").addEventListener("click", () => callBridge("close_about_window"));
});
