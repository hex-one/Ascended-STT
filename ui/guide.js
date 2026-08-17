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

// A small, dependency-free renderer for exactly the Markdown these six
// setup guides actually use -- headers, bold, inline code, fenced code
// blocks, links, and ordered/unordered lists. Not meant to handle
// arbitrary Markdown from anywhere else; this only ever renders our
// own bundled .md files, never anything from the network.
function renderMarkdown(md) {
  const escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const renderInline = (text) => {
    text = escapeHtml(text);
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
      (_m, label, url) => `<a href="#" data-url="${url}">${label}</a>`);
    return text;
  };

  const lines = md.replace(/\r\n/g, "\n").split("\n");
  let html = "";
  let listType = null; // "ul" | "ol" | null
  let i = 0;

  const closeList = () => {
    if (listType) {
      html += `</${listType}>`;
      listType = null;
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      closeList();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
      i++; // skip the closing ```
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html += `<h${level}>${renderInline(heading[2])}</h${level}>`;
      i++;
      continue;
    }

    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+\.\s+(.*)$/);
    if (bullet || numbered) {
      const wantType = bullet ? "ul" : "ol";
      if (listType !== wantType) {
        closeList();
        html += `<${wantType}>`;
        listType = wantType;
      }
      html += `<li>${renderInline((bullet || numbered)[1])}</li>`;
      i++;
      continue;
    }

    closeList();

    if (line.trim() === "") {
      i++;
      continue;
    }
    if (line.trim() === "---") {
      html += "<hr>";
      i++;
      continue;
    }

    // Plain paragraph -- keep consuming lines until a blank line or
    // the start of a different block, so wrapped prose in the source
    // file becomes one flowing <p>, not one per source line.
    const paraLines = [line];
    i++;
    while (
      i < lines.length && lines[i].trim() !== "" &&
      !lines[i].match(/^#{1,4}\s/) && !lines[i].startsWith("```") &&
      !lines[i].match(/^\s*[-*]\s/) && !lines[i].match(/^\s*\d+\.\s/)
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    html += `<p>${renderInline(paraLines.join(" "))}</p>`;
  }
  closeList();
  return html;
}

new QWebChannel(qt.webChannelTransport, async function (channel) {
  bridge = channel.objects.bridge;

  const params = new URLSearchParams(window.location.search);
  const name = params.get("name") || "";

  const result = await callBridgeJSON("get_setup_guide", name);
  if (!result.ok) {
    $("guideError").textContent = result.error;
  } else {
    document.title = result.title;
    $("guideTitle").textContent = result.title;
    $("guideContent").innerHTML = renderMarkdown(result.markdown);
    $("guideContent").addEventListener("click", (event) => {
      const link = event.target.closest("a[data-url]");
      if (link) {
        event.preventDefault();
        callBridge("open_external_link", link.dataset.url);
      }
    });
  }

  $("closeBtn").addEventListener("click", () => callBridge("close_setup_guide_window"));
});
