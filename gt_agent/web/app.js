const problemEl = document.getElementById("problem");
const contextEl = document.getElementById("context");
const baseUrlEl = document.getElementById("baseUrl");
const modelEl = document.getElementById("model");
const apiKeyEl = document.getElementById("apiKey");
const temperatureEl = document.getElementById("temperature");
const sendBtn = document.getElementById("sendBtn");
const runBtn = document.getElementById("runBtn");
const statusText = document.getElementById("statusText");
const conversation = document.getElementById("conversation");

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
    if (config.has_api_key) {
      apiKeyEl.placeholder = "Using environment API key";
    }
  } catch (_error) {
    // The UI still works with its built-in defaults if config discovery fails.
  }
}

function appendMessage(role, title, text, meta = "") {
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
  body.textContent = text;
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
  };

  appendMessage("user", "Problem", problem, payload.domain_context ? `Context: ${payload.domain_context}` : "");
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
      data.provider_error ? `Provider error: ${data.provider_error}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    appendMessage("assistant", "GT Agent Result", data.answer, meta);
  } catch (error) {
    appendMessage("assistant", "Blocked", "The research request failed before a model answer was produced.", String(error));
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  sendBtn.disabled = busy;
  runBtn.disabled = busy;
  statusText.textContent = busy ? "Running model..." : "Idle";
}

sendBtn.addEventListener("click", runResearch);
runBtn.addEventListener("click", runResearch);
problemEl.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    runResearch();
  }
});

loadConfig();
