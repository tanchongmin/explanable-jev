const questionsEl = document.querySelector("#questions");
const template = document.querySelector("#questionTemplate");
const stateRows = document.querySelector("#stateRows");
const statusEl = document.querySelector("#status");
const answersEl = document.querySelector("#answers");
const rawJson = document.querySelector("#rawJson");
const explanationMode = document.querySelector("#explanationMode");

const examples = {
  state: {
    ticket_message:
      "I was charged twice for order A-104 and the shoes arrived in the wrong size. Can someone refund the duplicate charge and swap these for a size 10?",
    refund_policy: "Duplicate charges are eligible for a refund after payment verification.",
  },
  questions: [
    {
      id: "department",
      type: "choice",
      instructions: "Which team should handle `ticket_message`?",
      criteria: {
        returns: "Exchanges, wrong size, wrong item, or damaged items.",
        shipping: "Delivery status, delays, lost packages, or carrier issues.",
        billing: "Charges, invoices, duplicate payments, refunds, and payment problems.",
      },
    },
    {
      id: "frustration",
      type: "score",
      instructions: "How frustrated does the customer appear in `ticket_message`?",
      criteria: ["Calm and neutral.", "Concerned but civil.", "Very angry or using strong language."],
    },
    {
      id: "refund_eligible",
      type: "noul",
      instructions: "Based on `ticket_message` and `refund_policy`, is the requested refund eligible?",
      criteria: {
        true: "The request matches the policy conditions for a refund.",
        false: "The request does not meet the policy conditions for a refund.",
      },
    },
  ],
};

function nextId(type) {
  return `${type}_${questionsEl.children.length + 1}`;
}

function addStateRow(key = "", value = "") {
  const row = document.createElement("div");
  row.className = "state-row";
  row.innerHTML = `
    <input class="state-key" placeholder="key" />
    <textarea class="state-value" placeholder="value" spellcheck="false"></textarea>
    <button type="button" title="Remove">x</button>
  `;
  row.querySelector(".state-key").value = key;
  const valueField = row.querySelector(".state-value");
  valueField.value = value;
  wireAutoResize(valueField);
  row.querySelector("button").addEventListener("click", () => row.remove());
  stateRows.appendChild(row);
}

function addQuestion(type = "choice", data = {}) {
  const node = template.content.firstElementChild.cloneNode(true);
  const qid = node.querySelector(".qid");
  const qtype = node.querySelector(".qtype");
  const instructions = node.querySelector(".instructions");
  const typeHelp = node.querySelector(".question-type-help");

  qid.value = data.id || nextId(type);
  qtype.value = data.type || type;
  instructions.value = data.instructions || "";
  node.dataset.type = qtype.value;
  updateTypeHelp(typeHelp, qtype.value);

  qtype.addEventListener("change", () => {
    node.dataset.type = qtype.value;
    updateTypeHelp(typeHelp, qtype.value);
    renderCriteria(node, qtype.value, {});
  });
  node.querySelector(".remove").addEventListener("click", () => node.remove());
  node.querySelector(".describe").addEventListener("click", () => autoDescribe(node));

  questionsEl.appendChild(node);
  renderCriteria(node, qtype.value, data.criteria);
}

function updateTypeHelp(help, type) {
  if (!help) return;
  const text = {
    choice: "Choice returns exactly one option key from the options you provide.",
    score: "Score returns a number on your ordered rubric, starting at 0 for the first level.",
    noul: "True/False returns true or false for a yes/no judgment.",
  }[type];
  help.innerHTML = `?<span class="tooltip">${escapeHtml(text)}</span>`;
}

function renderCriteria(node, type, criteria) {
  const host = node.querySelector(".criteria");
  host.innerHTML = "";

  if (type === "choice") {
    const title = document.createElement("span");
    title.className = "criteria-title";
    title.textContent = "Options";
    host.appendChild(title);
    const entries = Object.entries(criteria && !Array.isArray(criteria) ? criteria : {
      option_a: "",
      option_b: "",
    });
    entries.forEach(([key, value]) => addChoiceRow(host, key, value || ""));
    addMiniButton(host, "Add option", () => addChoiceRow(host, "", ""));
    return;
  }

  if (type === "score") {
    const title = document.createElement("span");
    title.className = "criteria-title";
    title.textContent = "Levels";
    host.appendChild(title);
    const levels = Array.isArray(criteria) && criteria.length ? criteria : ["Low", "High"];
    levels.forEach((value) => addScoreRow(host, value || ""));
    addMiniButton(host, "Add level", () => addScoreRow(host, ""));
    updateScoreIndexes(host);
    return;
  }

  const title = document.createElement("span");
  title.className = "criteria-title";
  title.textContent = "True / false criteria";
  host.appendChild(title);
  addChoiceRow(host, "true", criteria?.true || "", true);
  addChoiceRow(host, "false", criteria?.false || "", true);
}

function addChoiceRow(host, key, value, fixedKey = false) {
  const row = document.createElement("div");
  row.className = "row";
  row.innerHTML = `
    <input class="key" placeholder="key" ${fixedKey ? "readonly" : ""} />
    <textarea class="value option-description" placeholder="description" spellcheck="false"></textarea>
    <button type="button" title="Remove">x</button>
  `;
  row.querySelector(".key").value = key;
  const valueField = row.querySelector(".value");
  valueField.value = value;
  wireAutoResize(valueField);
  row.querySelector("button").addEventListener("click", () => row.remove());
  host.insertBefore(row, host.querySelector(".mini-add"));
}

function addScoreRow(host, value) {
  const row = document.createElement("div");
  row.className = "row score";
  row.innerHTML = `
    <span class="score-index"></span>
    <textarea class="value option-description" placeholder="level description" spellcheck="false"></textarea>
    <button type="button" title="Remove">x</button>
  `;
  const valueField = row.querySelector(".value");
  valueField.value = value;
  wireAutoResize(valueField);
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    updateScoreIndexes(host);
  });
  host.insertBefore(row, host.querySelector(".mini-add"));
  updateScoreIndexes(host);
}

function updateScoreIndexes(host) {
  const rows = [...host.querySelectorAll(".row.score")];
  const denominator = Math.max(rows.length - 1, 1);
  rows.forEach((row, index) => {
    const intensity = index / denominator;
    const badge = row.querySelector(".score-index");
    badge.textContent = index;
    badge.style.setProperty("--level-intensity", intensity.toFixed(3));
  });
}

function wireAutoResize(textarea) {
  const resize = () => {
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight + 2}px`;
  };
  textarea.addEventListener("input", resize);
  requestAnimationFrame(resize);
}

function addMiniButton(host, text, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "mini-add";
  button.textContent = text;
  button.addEventListener("click", onClick);
  host.appendChild(button);
}

function collectState() {
  const state = {};
  for (const row of stateRows.children) {
    const key = row.querySelector(".state-key").value.trim();
    const value = row.querySelector(".state-value").value.trim();
    if (key) state[key] = value;
  }
  return state;
}

function collectPayload() {
  const state = collectState();

  const questions = {};
  for (const node of questionsEl.children) {
    const id = node.querySelector(".qid").value.trim();
    const type = node.querySelector(".qtype").value;
    const instructions = node.querySelector(".instructions").value.trim();
    const question = { type, instructions };

    if (type === "choice") {
      question.criteria = {};
      for (const row of node.querySelectorAll(".row")) {
        const key = row.querySelector(".key").value.trim();
        if (key) question.criteria[key] = row.querySelector(".value").value.trim() || null;
      }
    } else if (type === "score") {
      question.criteria = [...node.querySelectorAll(".row .value")]
        .map((input) => input.value.trim())
        .filter(Boolean);
    } else {
      question.criteria = {};
      for (const row of node.querySelectorAll(".row")) {
        const key = row.querySelector(".key").value.trim();
        const value = row.querySelector(".value").value.trim();
        if (value) question.criteria[key] = value;
      }
      if (!Object.keys(question.criteria).length) delete question.criteria;
    }

    questions[id] = question;
  }

  return { state, questions, explanationMode: explanationMode.checked };
}

function collectQuestion(node) {
  const id = node.querySelector(".qid").value.trim();
  const type = node.querySelector(".qtype").value;
  const instructions = node.querySelector(".instructions").value.trim();
  const question = { id, type, instructions };

  if (type === "choice") {
    question.criteria = {};
    for (const row of node.querySelectorAll(".row")) {
      const key = row.querySelector(".key").value.trim();
      if (key) question.criteria[key] = row.querySelector(".value").value.trim() || null;
    }
  } else if (type === "score") {
    question.criteria = [...node.querySelectorAll(".row .value")]
      .map((input) => input.value.trim())
      .filter(Boolean);
  } else {
    question.criteria = {};
    for (const row of node.querySelectorAll(".row")) {
      const key = row.querySelector(".key").value.trim();
      const value = row.querySelector(".value").value.trim();
      if (value) question.criteria[key] = value;
    }
  }

  return question;
}

async function autoDescribe(node) {
  const button = node.querySelector(".describe");
  const question = collectQuestion(node);
  const type = question.type;
  let options = [];

  if (type === "choice") {
    options = Object.keys(question.criteria);
  } else if (type === "score") {
    options = question.criteria;
  }

  button.disabled = true;
  button.textContent = "Describing...";
  try {
    const response = await fetch("/api/describe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type,
        instructions: question.instructions,
        options,
        state: collectState(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Description generation failed.");
    applyDescriptions(node, data.descriptions || {});
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Auto describe";
  }
}

function applyDescriptions(node, descriptions) {
  const type = node.querySelector(".qtype").value;
  if (type === "score") {
    const rows = [...node.querySelectorAll(".row")];
    rows.forEach((row, index) => {
      const key = String(index);
      const byLabel = row.querySelector(".value").value.trim();
      const description = descriptions[key] || descriptions[byLabel];
      if (description) {
        const value = row.querySelector(".value");
        value.value = description;
        wireAutoResize(value);
      }
    });
    return;
  }

  for (const row of node.querySelectorAll(".row")) {
    const key = row.querySelector(".key").value.trim();
    const value = row.querySelector(".value");
    if (descriptions[key]) {
      value.value = descriptions[key];
      wireAutoResize(value);
    }
  }
}

async function runEvaluation() {
  statusEl.textContent = "Evaluating...";
  answersEl.className = "answers empty";
  answersEl.textContent = "Working in parallel.";
  rawJson.textContent = "{}";

  try {
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
    const data = await response.json();
    rawJson.textContent = JSON.stringify(compactAnswers(data.answers || {}), null, 2);
    if (!response.ok) throw new Error(data.error || "Evaluation failed.");
    statusEl.textContent = `${data.elapsed_ms} ms · ${data.parallelism} question workers`;
    renderAnswers(data.answers);
  } catch (error) {
    statusEl.textContent = "Error";
    answersEl.className = "answers";
    answersEl.innerHTML = `<div class="answer"><strong>${escapeHtml(error.message)}</strong></div>`;
  }
}

function compactAnswers(answers) {
  const compact = {};
  for (const [id, answer] of Object.entries(answers)) {
    let value;
    if (answer.type === "choice") {
      value = answer.choice;
    } else if (answer.type === "score") {
      value = answer.score;
    } else {
      value = answer.noul;
    }

    compact[id] = answer.explanation
      ? { answer: value, explanation: answer.explanation }
      : value;
  }
  return compact;
}

function renderAnswers(answers) {
  answersEl.className = "answers";
  answersEl.innerHTML = "";
  for (const [id, answer] of Object.entries(answers)) {
    const card = document.createElement("article");
    card.className = `answer answer-${answer.type}`;
    const typeLabel = answer.type === "noul" ? "True/False" : answer.type;
    const promptText = formatPrompt(answer.prompt);
    card.innerHTML = `
      <div class="answer-head">
        <h3 class="answer-question">
          ${escapeHtml(id)}
          ${promptText ? `<span class="prompt-tooltip">${escapeHtml(promptText)}</span>` : ""}
        </h3>
        <span class="badge">${escapeHtml(typeLabel)}</span>
      </div>
      ${renderSummary(answer)}
      ${answer.explanation ? `<div class="explanation"><strong>Explanation</strong><span>${escapeHtml(answer.explanation)}</span></div>` : ""}
    `;
    answersEl.appendChild(card);
  }
}

function formatPrompt(prompt) {
  if (!prompt) return "";
  return `System:\n${prompt.system || ""}\n\nUser:\n${prompt.user || ""}`;
}

function renderSummary(answer) {
  if (answer.type === "choice") {
    return `<div class="metric">Choice: <strong>${escapeHtml(answer.choice)}</strong></div>`;
  }
  if (answer.type === "score") {
    return `<div class="metric">Score: <strong>${fmt(answer.score)}</strong></div>`;
  }
  return `<div class="metric">True/False: <strong>${answer.noul ? "true" : "false"}</strong></div>`;
}

function loadExample() {
  stateRows.innerHTML = "";
  Object.entries(examples.state).forEach(([key, value]) => addStateRow(key, value));
  questionsEl.innerHTML = "";
  examples.questions.forEach((question) => addQuestion(question.type, question));
  rawJson.textContent = "{}";
  answersEl.className = "answers empty";
  answersEl.textContent = "No results yet.";
  statusEl.textContent = "";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function fmt(value) {
  return Number(value).toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

document.querySelectorAll("[data-add]").forEach((button) => {
  button.addEventListener("click", () => addQuestion(button.dataset.add));
});
document.querySelector("#loadExample").addEventListener("click", loadExample);
document.querySelector("#run").addEventListener("click", runEvaluation);
document.querySelector("#addStateRow").addEventListener("click", () => addStateRow());

loadExample();
