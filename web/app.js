const questionsEl = document.querySelector("#questions");
const template = document.querySelector("#questionTemplate");
const stateRows = document.querySelector("#stateRows");
const statusEl = document.querySelector("#status");
const answersEl = document.querySelector("#answers");
const inputJson = document.querySelector("#inputJson");
const outputJson = document.querySelector("#outputJson");
const explanationMode = document.querySelector("#explanationMode");
const assistPanel = document.querySelector("#assistPanel");
const assistDescription = document.querySelector("#assistDescription");
const assistToggle = document.querySelector("#assistToggle");
const assistGenerate = document.querySelector("#assistGenerate");
const assistCancel = document.querySelector("#assistCancel");
const refinePanel = document.querySelector("#refinePanel");
const refineInstruction = document.querySelector("#refineInstruction");
const refineToggle = document.querySelector("#refineToggle");
const refineGenerate = document.querySelector("#refineGenerate");
const refineCancel = document.querySelector("#refineCancel");
const refineRevert = document.querySelector("#refineRevert");
let refineUndoPayload = null;

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
      type: "true/false",
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
  row.addEventListener("input", updateInputJson);
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    updateInputJson();
  });
  stateRows.appendChild(row);
  updateInputJson();
}

function addQuestion(type = "choice", data = {}) {
  const node = template.content.firstElementChild.cloneNode(true);
  const qid = node.querySelector(".qid");
  const qtype = node.querySelector(".qtype");
  const instructions = node.querySelector(".instructions");
  const typeHelp = node.querySelector(".question-type-help");

  qid.value = data.id || nextId(type);
  qtype.value = normalizeQuestionType(data.type || type);
  instructions.value = data.instructions || "";
  node.dataset.type = qtype.value;
  updateTypeHelp(typeHelp, qtype.value);

  qtype.addEventListener("change", () => {
    node.dataset.type = qtype.value;
    updateTypeHelp(typeHelp, qtype.value);
    renderCriteria(node, qtype.value, {});
    updateInputJson();
  });
  node.addEventListener("input", updateInputJson);
  node.querySelector(".remove").addEventListener("click", () => {
    node.remove();
    updateInputJson();
  });
  node.querySelector(".describe").addEventListener("click", () => autoDescribe(node));

  questionsEl.appendChild(node);
  renderCriteria(node, qtype.value, data.criteria);
  updateInputJson();
}

function updateTypeHelp(help, type) {
  if (!help) return;
  const text = {
    choice: "Choice returns exactly one option key from the options you provide.",
    score: "Score returns a number on your ordered rubric, starting at 0 for the first level.",
    "true/false": "True/False returns true or false for a yes/no judgment.",
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
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    updateInputJson();
  });
  host.insertBefore(row, host.querySelector(".mini-add"));
  row.addEventListener("input", updateInputJson);
  updateInputJson();
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
    updateInputJson();
  });
  host.insertBefore(row, host.querySelector(".mini-add"));
  updateScoreIndexes(host);
  row.addEventListener("input", updateInputJson);
  updateInputJson();
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

function normalizeQuestionType(type) {
  return type === "bool" || type === "noul" ? "true/false" : type;
}

function answerCssType(type) {
  return type === "true/false" || type === "noul" ? "bool" : type;
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
    const data = await readJsonResponse(response);
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
  updateInputJson();
  statusEl.textContent = "Evaluating...";
  answersEl.className = "answers empty";
  answersEl.textContent = "Working in parallel.";
  outputJson.textContent = "{}";

  try {
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPayload()),
    });
    const data = await readJsonResponse(response);
    outputJson.textContent = JSON.stringify(compactAnswers(data.answers || {}), null, 2);
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
      value = answer["true/false"] ?? answer.bool ?? answer.noul;
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
    card.className = `answer answer-${answerCssType(answer.type)}`;
    const typeLabel = ["true/false", "bool", "noul"].includes(answer.type) ? "True/False" : answer.type;
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
  return `<div class="metric">True/False: <strong>${answer["true/false"] ?? answer.bool ?? answer.noul ? "true" : "false"}</strong></div>`;
}

function loadExample() {
  refineUndoPayload = null;
  updateRefineRevertState();
  stateRows.innerHTML = "";
  Object.entries(examples.state).forEach(([key, value]) => addStateRow(key, value));
  questionsEl.innerHTML = "";
  examples.questions.forEach((question) => addQuestion(question.type, question));
  updateInputJson();
  outputJson.textContent = "{}";
  answersEl.className = "answers empty";
  answersEl.textContent = "No results yet.";
  statusEl.textContent = "";
}

function applyGeneratedSetup(data) {
  stateRows.innerHTML = "";
  Object.entries(data.state || {}).forEach(([key, value]) => {
    addStateRow(key, typeof value === "string" ? value : JSON.stringify(value));
  });

  questionsEl.innerHTML = "";
  for (const [id, question] of Object.entries(data.questions || {})) {
    addQuestion(question.type, { id, ...question });
  }

  if (typeof data.explanationMode === "boolean") {
    explanationMode.checked = data.explanationMode;
  }
  updateInputJson();
  outputJson.textContent = "{}";
  answersEl.className = "answers empty";
  answersEl.textContent = "No results yet.";
}

function clonePayload(payload) {
  return JSON.parse(JSON.stringify(payload));
}

function updateRefineRevertState() {
  if (!refineRevert) return;
  refineRevert.disabled = !refineUndoPayload;
}

function revertRefine() {
  if (!refineUndoPayload) return;
  applyGeneratedSetup(refineUndoPayload);
  refineUndoPayload = null;
  updateRefineRevertState();
  statusEl.textContent = "Reverted to the previous setup.";
}

function updateInputJson() {
  if (!inputJson) return;
  inputJson.textContent = JSON.stringify(collectPayload(), null, 2);
}

async function copyJson(targetId, button) {
  const target = document.querySelector(`#${targetId}`);
  if (!target) return;
  const text = target.textContent;
  const originalLabel = button.getAttribute("aria-label") || "Copy JSON";

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    button.classList.add("copied");
    button.setAttribute("aria-label", "Copied");
    setTimeout(() => {
      button.classList.remove("copied");
      button.setAttribute("aria-label", originalLabel);
    }, 1200);
  } catch (error) {
    statusEl.textContent = "Copy failed.";
  }
}

async function readJsonResponse(response) {
  const text = await response.text();
  const contentType = response.headers.get("Content-Type") || "";
  if (contentType.includes("application/json")) {
    return JSON.parse(text);
  }

  const fallback = text.trim().startsWith("<")
    ? `Server returned HTML for ${response.url}. Make sure this app is running through python3 server.py and that the backend has this API route.`
    : text.trim();
  throw new Error(fallback || `Server returned ${response.status}.`);
}

async function assistMe() {
  const description = assistDescription.value.trim();
  if (!description) {
    statusEl.textContent = "Describe what you want first.";
    assistDescription.focus();
    return;
  }

  assistGenerate.disabled = true;
  assistToggle.disabled = true;
  assistGenerate.textContent = "Generating...";
  statusEl.textContent = "Generating setup...";

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    });
    const data = await readJsonResponse(response);
    if (!response.ok) throw new Error(data.error || "Generation failed.");
    refineUndoPayload = null;
    updateRefineRevertState();
    applyGeneratedSetup(data);
    assistPanel.hidden = true;
    statusEl.textContent = "Generated editable state and questions.";
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    assistGenerate.disabled = false;
    assistToggle.disabled = false;
    assistGenerate.textContent = "Generate";
  }
}

async function refineSetup() {
  const instruction = refineInstruction.value.trim();
  if (!instruction) {
    statusEl.textContent = "Describe the refinement you want first.";
    refineInstruction.focus();
    return;
  }

  refineGenerate.disabled = true;
  refineToggle.disabled = true;
  refineGenerate.textContent = "Refining...";
  statusEl.textContent = "Refining setup...";
  const previousPayload = clonePayload(collectPayload());

  try {
    const response = await fetch("/api/refine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instruction,
        current: collectPayload(),
      }),
    });
    const data = await readJsonResponse(response);
    if (!response.ok) throw new Error(data.error || "Refinement failed.");
    refineUndoPayload = previousPayload;
    applyGeneratedSetup(data);
    updateRefineRevertState();
    refinePanel.hidden = true;
    statusEl.textContent = "Refined editable state and questions.";
  } catch (error) {
    statusEl.textContent = error.message;
  } finally {
    refineGenerate.disabled = false;
    refineToggle.disabled = false;
    refineGenerate.textContent = "Refine";
  }
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
explanationMode.addEventListener("change", updateInputJson);
document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    copyJson(button.dataset.copy, button);
  });
});
document.querySelectorAll("[data-json-panel]").forEach((panel) => {
  panel.addEventListener("click", () => {
    panel.classList.toggle("open");
  });
});
assistToggle.addEventListener("click", () => {
  assistPanel.hidden = !assistPanel.hidden;
  refinePanel.hidden = true;
  if (!assistPanel.hidden) assistDescription.focus();
});
assistCancel.addEventListener("click", () => {
  assistPanel.hidden = true;
});
assistGenerate.addEventListener("click", assistMe);
refineToggle.addEventListener("click", () => {
  refinePanel.hidden = !refinePanel.hidden;
  assistPanel.hidden = true;
  if (!refinePanel.hidden) refineInstruction.focus();
});
refineCancel.addEventListener("click", () => {
  refinePanel.hidden = true;
});
refineRevert.addEventListener("click", revertRefine);
refineGenerate.addEventListener("click", refineSetup);

loadExample();
