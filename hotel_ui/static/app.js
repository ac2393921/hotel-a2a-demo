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
const agentList = document.querySelector("#agent-list");
const agentLoadStatus = document.querySelector("#agent-load-status");
const taskTimeline = document.querySelector("#task-timeline");
const timelineEmpty = document.querySelector("#timeline-empty");
const taskCount = document.querySelector("#task-count");
const partialFailure = document.querySelector("#partial-failure");

let sessionId = null;
let messages = [];
let pendingProposal = null;
let agents = [];
let tasks = [];
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
  tasks = [];
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
    tasks = result.tasks || [];
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

function createAgentCard(agent) {
  const card = document.createElement("article");
  card.className = "agent-card";

  const heading = document.createElement("div");
  heading.className = "agent-card-heading";
  const name = document.createElement("h3");
  name.textContent = agent.name || agent.label;
  const availability = document.createElement("span");
  availability.className = `agent-availability${agent.available ? " is-available" : ""}`;
  availability.textContent = agent.available ? "接続中" : "未接続";
  heading.append(name, availability);

  const relatedTasks = tasks.filter((task) => task.agent_id === agent.id);
  const requestStatus = document.createElement("p");
  requestStatus.className = "agent-request-status";
  requestStatus.textContent = relatedTasks.length
    ? `今回の状態: ${relatedTasks.at(-1).events.at(-1)?.status || "状態不明"}`
    : "今回の依頼なし";

  const description = document.createElement("p");
  description.className = "agent-description";
  description.textContent = agent.description;
  card.append(heading, requestStatus, description);

  if (agent.skills?.length) {
    const skillList = document.createElement("ul");
    skillList.className = "agent-skills";
    for (const skill of agent.skills) {
      const item = document.createElement("li");
      const skillName = document.createElement("strong");
      skillName.textContent = skill.name;
      const skillDescription = document.createElement("span");
      skillDescription.textContent = skill.description;
      item.append(skillName, skillDescription);
      skillList.append(item);
    }
    card.append(skillList);
  }
  return card;
}

function createTaskElement(task) {
  const article = document.createElement("article");
  article.className = "task-card";

  const heading = document.createElement("div");
  heading.className = "task-card-heading";
  const agentName = document.createElement("h4");
  agentName.textContent = task.agent_name;
  const latestStatus = task.events.at(-1)?.status || "状態不明";
  const stateClass = latestStatus === "失敗"
    ? "failed"
    : latestStatus === "完了"
      ? "complete"
      : "pending";
  const state = document.createElement("span");
  state.className = `task-state task-state--${stateClass}`;
  state.textContent = latestStatus;
  heading.append(agentName, state);
  article.append(heading);

  if (task.task_id) {
    const taskId = document.createElement("p");
    taskId.className = "task-id";
    taskId.textContent = `Task ID: ${task.task_id}`;
    article.append(taskId);
  }

  const entries = document.createElement("ol");
  entries.className = "timeline-events";
  for (const event of task.events) {
    const item = document.createElement("li");
    const time = document.createElement("time");
    if (event.timestamp) {
      time.dateTime = event.timestamp;
      time.textContent = new Date(event.timestamp).toLocaleTimeString("ja-JP", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } else {
      time.textContent = "時刻不明";
    }
    const detail = document.createElement("div");
    const status = document.createElement("strong");
    status.textContent = event.status;
    detail.append(status);
    if (event.text) {
      const text = document.createElement("p");
      text.textContent = event.text;
      detail.append(text);
    }
    item.append(time, detail);
    entries.append(item);
  }
  article.append(entries);
  return article;
}

async function loadAgents() {
  try {
    const result = await request("/api/agents");
    agents = result.agents;
    agentLoadStatus.textContent = "Agent Cardの能力情報";
  } catch {
    agentLoadStatus.textContent = "能力情報を取得できません";
  }
  renderAgents();
}

function renderAgents() {
  agentList.replaceChildren(...agents.map(createAgentCard));
}

function renderTasks() {
  taskTimeline.replaceChildren(...tasks.map(createTaskElement));
  timelineEmpty.hidden = tasks.length > 0;
  taskCount.textContent = String(tasks.length);

  const succeeded = tasks.some((task) => task.events.some((event) => event.status === "完了"));
  const failed = tasks.some((task) => task.events.some((event) => event.status === "失敗"));
  partialFailure.hidden = !(succeeded && failed);
  partialFailure.textContent = partialFailure.hidden
    ? ""
    : "一部の部署から応答を得られませんでした。受信できた結果は表示しています。";
}

function render() {
  messageList.replaceChildren(...messages.map(createMessageElement));
  emptyState.hidden = messages.length > 0;
  proposalCard.hidden = !pendingProposal;
  if (pendingProposal) {
    proposalText.textContent = pendingProposal.text;
  }
  renderAgents();
  renderTasks();
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
  let responseReceived = false;

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
    tasks = result.tasks || [];
    responseReceived = true;
  } catch (error) {
    errorMessage.textContent = error.message;
    errorMessage.hidden = false;
    try {
      const current = await request(`/api/sessions/${encodeURIComponent(sessionId)}`);
      messages = current.messages;
      pendingProposal = current.pending_proposal;
      tasks = current.tasks || [];
    } catch {
      // Keep the current conversation visible so the guest can retry.
    }
  } finally {
    setSending(false);
    if (responseReceived) {
      liveStatus.textContent = "フロントデスクから回答を受け取り、部署AgentのTask状況を更新しました。";
    }
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
void loadAgents();
