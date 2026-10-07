const sessionKey = "hotel-a2a-guest-session";
const exampleMessage = "部屋のエアコンが壊れていて、19時からレストランも予約しています";

const conversation = document.querySelector("#conversation");
const emptyState = document.querySelector("#empty-state");
const messageList = document.querySelector("#messages");
const proposalCard = document.querySelector("#proposal-card");
const proposalText = document.querySelector("#proposal-text");
const messageForm = document.querySelector("#message-form");
const messageInput = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const approveButton = document.querySelector("#approve-button");
const rejectButton = document.querySelector("#reject-button");
const exampleButton = document.querySelector("#example-button");
const errorMessage = document.querySelector("#error-message");
const liveStatus = document.querySelector("#live-status");

let sessionId = null;
let messages = [];
let pendingProposal = null;
let isSending = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || "通信に失敗しました。もう一度お試しください。");
  }
  return body;
}

async function createSession() {
  const result = await request("/api/sessions", { method: "POST" });
  sessionId = result.session_id;
  sessionStorage.setItem(sessionKey, sessionId);
  messages = [];
  pendingProposal = null;
  render();
}

async function loadSession() {
  const savedId = sessionStorage.getItem(sessionKey);
  if (!savedId) {
    await createSession();
    return;
  }

  try {
    const result = await request(`/api/sessions/${encodeURIComponent(savedId)}`);
    sessionId = result.session_id;
    messages = result.messages;
    pendingProposal = result.pending_proposal;
    render();
  } catch {
    await createSession();
  }
}

function createMessageElement(message) {
  const article = document.createElement("article");
  article.className = `message message--${message.role === "user" ? "user" : "assistant"}`;

  const content = document.createElement("div");
  content.className = "message-content";

  const author = document.createElement("span");
  author.className = "message-author";
  author.textContent = message.role === "user" ? "あなた" : "フロントデスク";

  const text = document.createElement("p");
  text.className = "message-text";
  text.textContent = message.text;

  content.append(author, text);
  article.append(content);
  return article;
}

function render() {
  messageList.replaceChildren(...messages.map(createMessageElement));
  emptyState.hidden = messages.length > 0;
  proposalCard.hidden = !pendingProposal;
  if (pendingProposal) {
    proposalText.textContent = pendingProposal.text;
  }
  conversation.scrollTop = conversation.scrollHeight;
}

function setSending(value) {
  isSending = value;
  messageInput.disabled = value;
  sendButton.disabled = value;
  approveButton.disabled = value;
  rejectButton.disabled = value;
  liveStatus.textContent = value ? "Front Deskが確認しています。" : "";
}

async function sendMessage(text) {
  const cleanText = text.trim();
  if (!cleanText || isSending || !sessionId) {
    return;
  }

  messages.push({ role: "user", text: cleanText });
  errorMessage.hidden = true;
  render();
  setSending(true);

  try {
    const result = await request(
      `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        body: JSON.stringify({ text: cleanText }),
      },
    );
    messages.push({ role: "assistant", text: result.reply });
    pendingProposal = result.pending_proposal;
  } catch (error) {
    errorMessage.textContent = error.message;
    errorMessage.hidden = false;
    try {
      const current = await request(`/api/sessions/${encodeURIComponent(sessionId)}`);
      messages = current.messages;
      pendingProposal = current.pending_proposal;
    } catch {
      // Keep the current conversation visible so the guest can retry.
    }
  } finally {
    setSending(false);
    render();
    messageInput.focus();
  }
}

messageForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = messageInput.value;
  if (!text.trim() || isSending) {
    return;
  }
  messageInput.value = "";
  void sendMessage(text);
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    messageForm.requestSubmit();
  }
});

approveButton.addEventListener("click", () => {
  void sendMessage("はい、この変更案を承認します。");
});

rejectButton.addEventListener("click", () => {
  void sendMessage("いいえ、この変更案は拒否します。");
});

exampleButton.addEventListener("click", () => {
  messageInput.value = exampleMessage;
  messageInput.focus();
});

void loadSession().catch((error) => {
  errorMessage.textContent = error.message;
  errorMessage.hidden = false;
});
