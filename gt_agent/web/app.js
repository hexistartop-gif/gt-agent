const problemEl = document.getElementById("problem");
const contextEl = document.getElementById("context");
const baseUrlEl = document.getElementById("baseUrl");
const modelEl = document.getElementById("model");
const apiKeyEl = document.getElementById("apiKey");
const temperatureEl = document.getElementById("temperature");
const maxTokensEl = document.getElementById("maxTokens");
const newChatBtn = document.getElementById("newChatBtn");
const renameChatBtn = document.getElementById("renameChatBtn");
const deleteChatBtn = document.getElementById("deleteChatBtn");
const chatList = document.getElementById("chatList");
const activeChatTitle = document.getElementById("activeChatTitle");
const exportFormatEl = document.getElementById("exportFormat");
const exportBtn = document.getElementById("exportBtn");
const sendBtn = document.getElementById("sendBtn");
const runBtn = document.getElementById("runBtn");
const statusText = document.getElementById("statusText");
const conversation = document.getElementById("conversation");
const toolsStatus = document.getElementById("toolsStatus");
const toolsList = document.getElementById("toolsList");
const enableAllToolsBtn = document.getElementById("enableAllToolsBtn");
const disableAllToolsBtn = document.getElementById("disableAllToolsBtn");
const resetToolsBtn = document.getElementById("resetToolsBtn");
const pendingMathElements = new Set();
const CHAT_STORAGE_KEY = "gt_agent_conversations_v1";
const ACTIVE_CHAT_STORAGE_KEY = "gt_agent_active_conversation_v1";
let toolMetadata = [];
let conversations = [];
let activeConversationId = "";

function loadConversations() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) || "[]");
    conversations = Array.isArray(parsed) ? parsed.filter(isConversation) : [];
  } catch (_error) {
    conversations = [];
  }
  if (!conversations.length) {
    conversations = [createConversation("Untitled")];
  }
  const savedActiveId = localStorage.getItem(ACTIVE_CHAT_STORAGE_KEY);
  activeConversationId = conversations.some((conversationItem) => conversationItem.id === savedActiveId)
    ? savedActiveId
    : conversations[0].id;
  saveConversations();
  renderChatList();
  renderActiveConversation();
}

function createConversation(title = "Untitled") {
  const now = new Date().toISOString();
  return {
    id: `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title,
    created_at: now,
    updated_at: now,
    messages: [],
  };
}

function isConversation(value) {
  return (
    value &&
    typeof value.id === "string" &&
    typeof value.title === "string" &&
    Array.isArray(value.messages)
  );
}

function getActiveConversation() {
  let active = conversations.find((conversationItem) => conversationItem.id === activeConversationId);
  if (!active) {
    active = conversations[0] || createConversation("Untitled");
    if (!conversations.length) {
      conversations.push(active);
    }
    activeConversationId = active.id;
  }
  return active;
}

function saveConversations() {
  localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(conversations));
  localStorage.setItem(ACTIVE_CHAT_STORAGE_KEY, activeConversationId);
}

function touchConversation(conversationItem) {
  conversationItem.updated_at = new Date().toISOString();
}

function createNewConversation() {
  const conversationItem = createConversation("New conversation");
  conversations.unshift(conversationItem);
  activeConversationId = conversationItem.id;
  saveConversations();
  renderChatList();
  renderActiveConversation();
  problemEl.focus();
}

function selectConversation(conversationId) {
  activeConversationId = conversationId;
  saveConversations();
  renderChatList();
  renderActiveConversation();
}

function renameActiveConversation() {
  const active = getActiveConversation();
  const title = window.prompt("Conversation title", active.title);
  if (!title?.trim()) {
    return;
  }
  active.title = title.trim();
  touchConversation(active);
  saveConversations();
  renderChatList();
  renderActiveConversation();
}

function deleteActiveConversation() {
  const active = getActiveConversation();
  if (active.messages.length && !window.confirm(`Delete conversation "${active.title}"?`)) {
    return;
  }
  if (conversations.length <= 1) {
    active.title = "Untitled";
    active.messages = [];
    touchConversation(active);
  } else {
    conversations = conversations.filter((conversationItem) => conversationItem.id !== active.id);
    activeConversationId = conversations[0].id;
  }
  saveConversations();
  renderChatList();
  renderActiveConversation();
}

function renderChatList() {
  conversations.sort((left, right) => new Date(right.updated_at || 0) - new Date(left.updated_at || 0));
  chatList.replaceChildren();
  for (const conversationItem of conversations) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chat-item ${conversationItem.id === activeConversationId ? "active" : ""}`;
    button.title = conversationItem.title;
    button.addEventListener("click", () => selectConversation(conversationItem.id));

    const title = document.createElement("span");
    title.className = "chat-title";
    title.textContent = conversationItem.title;

    const meta = document.createElement("span");
    meta.className = "chat-meta";
    meta.textContent = formatChatMeta(conversationItem);

    button.appendChild(title);
    button.appendChild(meta);
    chatList.appendChild(button);
  }
}

function formatChatMeta(conversationItem) {
  const count = conversationItem.messages?.length || 0;
  const date = conversationItem.updated_at ? new Date(conversationItem.updated_at) : new Date();
  return `${count} messages · ${date.toLocaleDateString()}`;
}

function renderActiveConversation() {
  const active = getActiveConversation();
  activeChatTitle.textContent = active.title || "Research Console";
  conversation.replaceChildren();
  if (!active.messages.length) {
    appendDomMessage({
      role: "assistant",
      title: "Ready.",
      text: "State a problem with its definitions, hypotheses, and allowed references.",
      meta: "",
    });
  } else {
    for (const message of active.messages) {
      appendDomMessage(message);
    }
  }
  conversation.scrollTop = conversation.scrollHeight;
}

function appendConversationMessage(role, title, text, meta = "") {
  const active = getActiveConversation();
  const message = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    title,
    text: String(text || ""),
    meta: String(meta || ""),
    created_at: new Date().toISOString(),
  };
  active.messages.push(message);
  if (role === "user" && (!active.title || active.title === "Untitled" || active.title === "New conversation")) {
    active.title = deriveTitle(message.text);
  }
  touchConversation(active);
  saveConversations();
  renderChatList();
  appendDomMessage(message);
}

function deriveTitle(text) {
  const compact = String(text || "").replace(/\s+/g, " ").trim();
  if (!compact) {
    return "Untitled";
  }
  return compact.length > 34 ? `${compact.slice(0, 34)}...` : compact;
}

async function loadConfig() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) {
      return;
    }
    const config = await response.json();
    if (config.base_url) {
      baseUrlEl.value = config.base_url;
    }
    if (config.model) {
      modelEl.value = config.model;
    }
    if (config.temperature !== undefined && config.temperature !== null) {
      temperatureEl.value = config.temperature;
    }
    if (config.max_tokens !== undefined && config.max_tokens !== null) {
      maxTokensEl.value = config.max_tokens;
    }
    if (config.has_api_key) {
      apiKeyEl.placeholder = "Using environment API key";
    }
  } catch (_error) {
    // The UI still works with its built-in defaults if config discovery fails.
  }
}

async function loadTools() {
  try {
    const response = await fetch("/api/tools");
    if (!response.ok) {
      throw new Error("Tool config unavailable");
    }
    renderTools(await response.json());
  } catch (error) {
    toolsStatus.textContent = "Unavailable";
    toolsList.textContent = String(error);
  }
}

function renderTools(payload) {
  toolMetadata = payload.metadata || [];
  const enabledCount = toolMetadata.filter((tool) => tool.enabled).length;
  toolsStatus.textContent = `${enabledCount}/${toolMetadata.length} on`;
  toolsList.replaceChildren();

  for (const [category, tools] of groupToolsByCategory(toolMetadata)) {
    const group = document.createElement("section");
    group.className = "tool-group";

    const heading = document.createElement("h3");
    heading.textContent = formatCategory(category);
    group.appendChild(heading);

    for (const tool of tools) {
      group.appendChild(renderToolRow(tool));
    }
    toolsList.appendChild(group);
  }
}

function renderToolRow(tool) {
  const row = document.createElement("label");
  row.className = `tool-row ${tool.id === "web_search" ? "priority-tool" : ""}`;

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(tool.enabled);
  checkbox.addEventListener("change", () => toggleTool(tool.id, checkbox.checked));

  const text = document.createElement("span");
  text.className = "tool-copy";

  const name = document.createElement("span");
  name.className = "tool-name";
  name.textContent = tool.display_name || tool.id;

  const description = document.createElement("span");
  description.className = "tool-description";
  description.textContent = tool.description || tool.note || "";

  text.appendChild(name);
  text.appendChild(description);

  const status = document.createElement("span");
  status.className = `tool-badge ${tool.available ? "ready" : "muted"}`;
  status.title = tool.note || tool.status || "";
  status.textContent = tool.available ? "Ready" : "Setup";

  row.appendChild(checkbox);
  row.appendChild(text);
  row.appendChild(status);
  return row;
}

function groupToolsByCategory(tools) {
  const groups = new Map();
  for (const tool of tools) {
    const category = tool.category || "general";
    if (!groups.has(category)) {
      groups.set(category, []);
    }
    groups.get(category).push(tool);
  }
  return groups;
}

function formatCategory(category) {
  return String(category)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

async function toggleTool(toolId, enabled) {
  toolsStatus.textContent = "Saving";
  const response = await fetch(`/api/tools/${encodeURIComponent(toolId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    toolsStatus.textContent = "Error";
    await loadTools();
    return;
  }
  renderTools(await response.json());
}

async function setAllTools(enabled) {
  const updates = Object.fromEntries(toolMetadata.map((tool) => [tool.id, enabled]));
  toolsStatus.textContent = "Saving";
  const response = await fetch("/api/tools", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tools: updates }),
  });
  if (!response.ok) {
    toolsStatus.textContent = "Error";
    return;
  }
  renderTools(await response.json());
}

async function resetTools() {
  toolsStatus.textContent = "Resetting";
  const response = await fetch("/api/tools/reset", { method: "POST" });
  if (!response.ok) {
    toolsStatus.textContent = "Error";
    return;
  }
  renderTools(await response.json());
}

function appendDomMessage(message) {
  const { role, title, text, meta = "" } = message;
  const article = document.createElement("article");
  article.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "YOU" : "GT";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const strong = document.createElement("strong");
  strong.textContent = title;
  bubble.appendChild(strong);

  const body = document.createElement("div");
  body.className = "message-body";
  body.innerHTML = renderMarkdown(balanceMathDelimiters(text));
  bubble.appendChild(body);

  if (meta) {
    const metaEl = document.createElement("div");
    metaEl.className = "meta";
    metaEl.textContent = meta;
    bubble.appendChild(metaEl);
  }

  article.appendChild(avatar);
  article.appendChild(bubble);
  conversation.appendChild(article);
  conversation.scrollTop = conversation.scrollHeight;
  typesetMath(body);
}

function renderMarkdown(markdown) {
  const source = String(markdown || "").replace(/\r\n?/g, "\n");
  const lines = source.split("\n");
  const html = [];
  let paragraph = [];
  let list = null;
  let inCodeBlock = false;
  let codeFence = "";
  let codeLines = [];
  let inMathBlock = false;
  let mathBlockEnd = "";
  let mathLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(`<p>${renderInline(paragraph.join("\n"))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (!list) {
      return;
    }
    html.push(`</${list}>`);
    list = null;
  };

  const openList = (type) => {
    if (list === type) {
      return;
    }
    closeList();
    list = type;
    html.push(`<${type}>`);
  };

  const flushCodeBlock = () => {
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    inCodeBlock = false;
    codeFence = "";
    codeLines = [];
  };

  const flushMathBlock = () => {
    html.push(`<div class="math-block">${escapeHtml(mathLines.join("\n"))}</div>`);
    inMathBlock = false;
    mathBlockEnd = "";
    mathLines = [];
  };

  for (const line of lines) {
    const fenceMatch = line.match(/^\s*(```+|~~~+)/);
    if (fenceMatch) {
      if (inCodeBlock && fenceMatch[1][0] === codeFence[0] && fenceMatch[1].length >= codeFence.length) {
        flushCodeBlock();
      } else if (!inCodeBlock) {
        flushParagraph();
        closeList();
        inCodeBlock = true;
        codeFence = fenceMatch[1];
        codeLines = [];
      } else {
        codeLines.push(line);
      }
      continue;
    }

    if (inMathBlock) {
      mathLines.push(line);
      if (line.trim().endsWith(mathBlockEnd)) {
        flushMathBlock();
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (trimmed.startsWith("$$") && !trimmed.slice(2).includes("$$")) {
      flushParagraph();
      closeList();
      inMathBlock = true;
      mathBlockEnd = "$$";
      mathLines = [line];
      continue;
    }

    if (trimmed.startsWith("\\[") && !trimmed.includes("\\]")) {
      flushParagraph();
      closeList();
      inMathBlock = true;
      mathBlockEnd = "\\]";
      mathLines = [line];
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      closeList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInline(headingMatch[2].trim())}</h${level}>`);
      continue;
    }

    const unorderedMatch = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      openList("ul");
      html.push(`<li>${renderInline(unorderedMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      openList("ol");
      html.push(`<li>${renderInline(orderedMatch[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(line);
  }

  if (inCodeBlock) {
    flushCodeBlock();
  }
  if (inMathBlock) {
    flushMathBlock();
  }
  flushParagraph();
  closeList();
  return html.join("");
}

function balanceMathDelimiters(text) {
  let balanced = String(text || "");
  if (countUnescaped(balanced, "$$") % 2 === 1) {
    balanced += "\n$$";
  }
  if (countOccurrences(balanced, "\\[") > countOccurrences(balanced, "\\]")) {
    balanced += "\n\\]";
  }
  if (countOccurrences(balanced, "\\(") > countOccurrences(balanced, "\\)")) {
    balanced += "\\)";
  }
  return balanced;
}

function countUnescaped(text, token) {
  let count = 0;
  let index = 0;
  while (index < text.length) {
    const found = text.indexOf(token, index);
    if (found === -1) {
      return count;
    }
    if (text[found - 1] !== "\\") {
      count += 1;
    }
    index = found + token.length;
  }
  return count;
}

function countOccurrences(text, token) {
  let count = 0;
  let index = 0;
  while (index < text.length) {
    const found = text.indexOf(token, index);
    if (found === -1) {
      return count;
    }
    count += 1;
    index = found + token.length;
  }
  return count;
}

function renderInline(text) {
  const placeholders = [];
  const stash = (value) => {
    const token = `\u0000${placeholders.length}\u0000`;
    placeholders.push(value);
    return token;
  };

  let rendered = escapeHtml(text);
  rendered = rendered.replace(/`([^`]+)`/g, (_match, code) => stash(`<code>${code}</code>`));
  rendered = protectMath(rendered, stash);
  rendered = rendered.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_match, label, href) => {
    return stash(`<a href="${escapeAttribute(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  });
  rendered = rendered.replace(/(^|[\s(])((?:https?:\/\/)[^\s<>()]+)/g, (_match, prefix, href) => {
    const trimmedHref = href.replace(/[.,;:!?]+$/g, "");
    const trailing = href.slice(trimmedHref.length);
    return `${prefix}${stash(
      `<a href="${escapeAttribute(unescapeHtml(trimmedHref))}" target="_blank" rel="noopener noreferrer">${trimmedHref}</a>`,
    )}${trailing}`;
  });
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  rendered = rendered.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  rendered = rendered.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  rendered = rendered.replace(/(^|[\s(])_([^_\n]+)_/g, "$1<em>$2</em>");
  rendered = rendered.replace(/\n/g, "<br>");

  return rendered.replace(/\u0000(\d+)\u0000/g, (_match, index) => placeholders[Number(index)] || "");
}

function protectMath(text, stash) {
  let output = "";
  let index = 0;

  while (index < text.length) {
    if (text.startsWith("$$", index)) {
      const end = text.indexOf("$$", index + 2);
      if (end !== -1) {
        output += stash(text.slice(index, end + 2));
        index = end + 2;
        continue;
      }
    }

    if (text.startsWith("\\[", index)) {
      const end = text.indexOf("\\]", index + 2);
      if (end !== -1) {
        output += stash(text.slice(index, end + 2));
        index = end + 2;
        continue;
      }
    }

    if (text.startsWith("\\(", index)) {
      const end = text.indexOf("\\)", index + 2);
      if (end !== -1) {
        output += stash(text.slice(index, end + 2));
        index = end + 2;
        continue;
      }
    }

    if (text[index] === "$" && text[index - 1] !== "\\" && text[index + 1] && !/\s/.test(text[index + 1])) {
      let end = index + 1;
      while (end < text.length) {
        if (text[end] === "$" && text[end - 1] !== "\\" && !/\s/.test(text[end - 1])) {
          output += stash(text.slice(index, end + 1));
          index = end + 1;
          break;
        }
        end += 1;
      }
      if (index === end + 1) {
        continue;
      }
    }

    output += text[index];
    index += 1;
  }

  return output;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const entities = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[char];
  });
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function unescapeHtml(value) {
  const textarea = document.createElement("textarea");
  textarea.innerHTML = value;
  return textarea.value;
}

function typesetMath(element) {
  if (!window.MathJax?.typesetPromise) {
    pendingMathElements.add(element);
    return;
  }
  pendingMathElements.delete(element);
  const promise = window.MathJax.startup?.promise
    ? window.MathJax.startup.promise.then(() => window.MathJax.typesetPromise([element]))
    : window.MathJax.typesetPromise([element]);
  promise?.catch(() => {
    // Keep the original text visible if MathJax cannot typeset a malformed formula.
  });
}

function typesetPendingMath() {
  for (const element of [...pendingMathElements]) {
    typesetMath(element);
  }
}

async function runResearch() {
  const problem = problemEl.value.trim();
  if (!problem) {
    statusText.textContent = "Problem is required";
    problemEl.focus();
    return;
  }

  const payload = {
    problem,
    domain_context: contextEl.value.trim(),
    base_url: baseUrlEl.value.trim(),
    model: modelEl.value.trim(),
    api_key: apiKeyEl.value.trim(),
    temperature: Number(temperatureEl.value || 0.2),
    max_tokens: Number(maxTokensEl.value || 8192),
  };

  appendConversationMessage("user", "Problem", problem, payload.domain_context ? `Context: ${payload.domain_context}` : "");
  setBusy(true);

  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Request failed");
    }
    const meta = [
      `Status: ${data.status}`,
      data.warnings?.length ? `Warnings: ${data.warnings.join(" | ")}` : "",
      data.tool_results?.length ? `Tools: ${summarizeToolResults(data.tool_results)}` : "",
      data.provider_error ? `Provider error: ${data.provider_error}` : "",
      data.continuation_count ? `Continuations: ${data.continuation_count}` : "",
      data.truncated ? "Output may still be truncated. Increase Max Tokens and retry." : "",
      data.finish_reason ? `Finish reason: ${data.finish_reason}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    appendConversationMessage("assistant", "GT Agent Result", data.answer, meta);
  } catch (error) {
    appendConversationMessage(
      "assistant",
      "Blocked",
      "The research request failed before a model answer was produced.",
      String(error),
    );
  } finally {
    setBusy(false);
  }
}

function summarizeToolResults(results) {
  return results
    .map((tool) => {
      const status = tool.result?.status || "ok";
      return `${tool.display_name || tool.id}: ${status}`;
    })
    .join(" | ");
}

function exportActiveConversation() {
  const active = getActiveConversation();
  const format = exportFormatEl.value;
  if (format === "json") {
    downloadFile(`${safeFileName(active.title)}.json`, JSON.stringify(active, null, 2), "application/json");
    return;
  }
  if (format === "markdown") {
    downloadFile(`${safeFileName(active.title)}.md`, conversationToMarkdown(active), "text/markdown");
    return;
  }
  exportConversationPdf(active);
}

function conversationToMarkdown(conversationItem) {
  const lines = [
    `# ${conversationItem.title || "GT Agent Conversation"}`,
    "",
    `- Created: ${conversationItem.created_at || ""}`,
    `- Updated: ${conversationItem.updated_at || ""}`,
    "",
  ];

  for (const message of conversationItem.messages) {
    lines.push(`## ${message.role === "user" ? "User" : "GT Agent"} - ${message.title || "Message"}`);
    lines.push("");
    lines.push(message.text || "");
    if (message.meta) {
      lines.push("");
      lines.push("```text");
      lines.push(message.meta);
      lines.push("```");
    }
    lines.push("");
  }
  return lines.join("\n");
}

function downloadFile(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function safeFileName(value) {
  const cleaned = String(value || "gt-agent-conversation")
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
  return (cleaned || "gt-agent-conversation").slice(0, 80);
}

function exportConversationPdf(conversationItem) {
  const printWindow = window.open("", "_blank", "noopener,noreferrer");
  if (!printWindow) {
    statusText.textContent = "Popup blocked";
    return;
  }
  const messages = conversationItem.messages
    .map((message) => {
      return `
        <article class="export-message ${escapeAttribute(message.role)}">
          <h2>${escapeHtml(message.role === "user" ? "User" : "GT Agent")} - ${escapeHtml(message.title || "Message")}</h2>
          <div class="export-body">${renderMarkdown(balanceMathDelimiters(message.text || ""))}</div>
          ${
            message.meta
              ? `<pre class="export-meta">${escapeHtml(message.meta)}</pre>`
              : ""
          }
        </article>
      `;
    })
    .join("");

  printWindow.document.write(`
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <title>${escapeHtml(conversationItem.title || "GT Agent Conversation")}</title>
        <style>
          body { font-family: Georgia, "Times New Roman", serif; margin: 36px; color: #202426; line-height: 1.55; }
          h1 { font-size: 24px; margin: 0 0 8px; }
          .export-date { color: #667076; font-size: 12px; margin-bottom: 24px; }
          .export-message { break-inside: avoid; border-top: 1px solid #d9e0e3; padding-top: 16px; margin-top: 20px; }
          .export-message h2 { font-size: 16px; margin: 0 0 10px; }
          .export-body pre, .export-meta { background: #f2f5f6; border: 1px solid #d9e0e3; padding: 10px; overflow-wrap: anywhere; white-space: pre-wrap; }
          .export-body code { background: #f2f5f6; padding: 0 3px; }
          mjx-container { overflow-x: auto; max-width: 100%; }
        </style>
        <script>
          window.MathJax = {
            tex: {
              inlineMath: [["$", "$"], ["\\\\(", "\\\\)"]],
              displayMath: [["$$", "$$"], ["\\\\[", "\\\\]"]],
              processEscapes: true
            },
            startup: {
              ready: () => {
                MathJax.startup.defaultReady();
                MathJax.startup.promise.then(() => setTimeout(() => window.print(), 250));
              }
            }
          };
        </script>
        <script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
      </head>
      <body>
        <h1>${escapeHtml(conversationItem.title || "GT Agent Conversation")}</h1>
        <div class="export-date">Updated: ${escapeHtml(conversationItem.updated_at || "")}</div>
        ${messages || "<p>No messages yet.</p>"}
      </body>
    </html>
  `);
  printWindow.document.close();
}

function setBusy(busy) {
  sendBtn.disabled = busy;
  runBtn.disabled = busy;
  statusText.textContent = busy ? "Running model..." : "Idle";
}

sendBtn.addEventListener("click", runResearch);
runBtn.addEventListener("click", runResearch);
newChatBtn.addEventListener("click", createNewConversation);
renameChatBtn.addEventListener("click", renameActiveConversation);
deleteChatBtn.addEventListener("click", deleteActiveConversation);
exportBtn.addEventListener("click", exportActiveConversation);
enableAllToolsBtn.addEventListener("click", () => setAllTools(true));
disableAllToolsBtn.addEventListener("click", () => setAllTools(false));
resetToolsBtn.addEventListener("click", resetTools);
problemEl.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    runResearch();
  }
});
document.addEventListener("mathjax-ready", typesetPendingMath);

loadConversations();
loadConfig();
loadTools();
