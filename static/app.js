(() => {
  const cfg = window.RUDE_ROYE_CHAT;
  if (!cfg) return;

  const logEl = document.getElementById(cfg.mountId);
  const formEl = document.getElementById(cfg.formId);
  const inputEl = document.getElementById(cfg.inputId);

  const state = {
    history: [],
  };

  function bubble(role, text) {
    const row = document.createElement("div");
    row.className = "d-flex";
    row.style.justifyContent = role === "user" ? "flex-end" : "flex-start";

    const b = document.createElement("div");
    b.className = "px-3 py-2 rounded-3";
    b.style.maxWidth = "85%";
    b.style.whiteSpace = "pre-wrap";
    b.style.border = "1px solid rgba(255,255,255,0.12)";
    b.style.background =
      role === "user"
        ? "rgba(79,140,255,0.20)"
        : "rgba(255,255,255,0.06)";
    b.textContent = text;

    row.appendChild(b);
    logEl.appendChild(row);
    logEl.scrollTop = logEl.scrollHeight;
  }

  async function send(text) {
    bubble("user", text);
    state.history.push({ role: "user", content: text });

    let reply = "No.";
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history: state.history.slice(-20) }),
      });
      const data = await res.json().catch(() => null);
      if (data && typeof data.reply === "string") reply = data.reply;
    } catch {
      reply = "No. (server said no too)";
    }

    bubble("bot", reply);
    state.history.push({ role: "assistant", content: reply });
  }

  bubble("bot", "No. (…okay fine) Say something.");

  formEl.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = (inputEl.value || "").trim();
    if (!text) return;
    inputEl.value = "";
    send(text);
  });
})();

