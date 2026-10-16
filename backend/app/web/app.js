"use strict";
const $ = (id) => document.getElementById(id);
const state = { key: "", principal: null, selected: null, offset: 0, generation: 0, hasNext: false };
let messageTimer;
function message(text, error = false) {
  clearTimeout(messageTimer); $("status").textContent = text;
  $("status").className = error ? "error" : ""; $("status").hidden = false;
  messageTimer = setTimeout(() => { $("status").hidden = true; }, 8000);
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (state.key) headers.set("Authorization", `Bearer ${state.key}`);
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) signOut();
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`);
  }
  return body;
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
function button(text, callback, className = "secondary") {
  const element = node("button", text, className); element.type = "button";
  element.addEventListener("click", () => perform(element, callback)); return element;
}
async function perform(element, action) {
  element.disabled = true;
  try { await action(); } catch (error) { message(error.message, true); }
  finally {
    element.disabled = element.id === "previous" ? state.offset === 0 :
      element.id === "next" ? !state.hasNext : false;
  }
}
function signOut() {
  state.key = ""; state.principal = null; state.selected = null; state.offset = 0; state.generation++;
  $("access-key").value = ""; $("pdf").value = ""; $("title").value = "";
  $("party").value = ""; $("contract-type").value = "";
  $("detail").replaceChildren(); $("contract-list").replaceChildren();
  $("workspace").hidden = true; $("login").hidden = false; $("upload-panel").hidden = true;
}
async function connect() {
  state.key = $("access-key").value.trim();
  const principal = await api("/auth/me"); state.principal = principal;
  $("access-key").value = ""; $("user-name").textContent = principal.user_id;
  $("tenant-name").textContent = `${principal.tenant_id} · ${principal.role}`;
  $("local-notice").hidden = principal.authentication_required;
  $("show-upload").hidden = principal.role !== "reviewer";
  $("workspace").hidden = false; $("login").hidden = true;
  $("detail").replaceChildren(node("div", "Select an agreement to explore its review, evidence, and obligations.", "empty"));
  await loadContracts();
}
async function loadContracts() {
  const generation = ++state.generation;
  const params = new URLSearchParams({ offset: state.offset, limit: 50 });
  if ($("party").value.trim()) params.set("party", $("party").value.trim());
  if ($("contract-type").value.trim()) params.set("contract_type", $("contract-type").value.trim());
  const contracts = await api(`/contracts?${params}`);
  if (generation !== state.generation || !state.principal) return;
  $("contract-list").replaceChildren(); $("list-count").textContent = `${state.offset + 1}–${state.offset + contracts.length}`;
  if (!contracts.length) { $("contract-list").append(node("p", "No agreements here yet. Upload a PDF or adjust your filters.", "muted")); $("list-count").textContent = "0"; }
  state.hasNext = contracts.length === 50;
  $("previous").disabled = state.offset === 0; $("next").disabled = !state.hasNext;
  for (const contract of contracts) {
    const card = button("", () => selectContract(contract.id), "contract-card"); card.dataset.id = contract.id;
    card.classList.toggle("selected", state.selected === contract.id);
    card.append(node("strong", contract.title));
    const meta = node("div", null, "card-meta"); meta.append(node("span", contract.contract_type || "Agreement"), node("span", contract.status, `badge ${contract.status}`)); card.append(meta);
    $("contract-list").append(card);
  }
}
async function selectContract(id) {
  state.selected = id; const principal = state.principal;
  const contract = await api(`/contracts/${id}`);
  if (state.selected !== id || state.principal !== principal) return;
  document.querySelectorAll(".contract-card").forEach(card => card.classList.toggle("selected", card.dataset.id === id));
  renderContract(contract);
}
function fact(container, label, value) {
  const item = node("div", null, "fact"); item.append(node("small", label), node("p", value || "Not identified")); container.append(item);
}
function evidence(container, text, page) { container.append(node("div", `Page ${page ?? "—"} · ${text}`, "evidence")); }
function renderContract(contract) {
  const detail = $("detail"); detail.replaceChildren();
  const heading = node("div", null, "detail-heading"); heading.append(node("h2", contract.title), node("span", contract.status, `badge ${contract.status}`)); detail.append(heading);
  detail.append(node("p", `${contract.filename} · ${contract.chunks.length} pages with text`, "hint"));
  const actions = node("div", null, "actions");
  if (state.principal.role === "reviewer" && ["pending", "failed"].includes(contract.status)) {
    actions.append(button("Run contract review ↗", async () => {
      message("Review in progress. This may take several minutes.");
      try { await api(`/contracts/${contract.id}/analyze`, { method: "POST" }); }
      catch (error) { await loadContracts(); await selectContract(contract.id); throw error; }
      await loadContracts(); await selectContract(contract.id); message("Review completed.");
    }));
  }
  if (contract.status === "processing" && state.principal.role === "reviewer") {
    actions.append(button("Recover interrupted review", async () => {
      await api(`/contracts/${contract.id}/recover`, { method: "POST" });
      await loadContracts(); await selectContract(contract.id); message("Interrupted review recovered. You can run it again.");
    }));
    detail.append(node("p", "A review is processing. Recovery is available after the configured timeout and only when no worker is actively holding the review.", "hint"));
  }
  actions.append(button("Refresh", async () => { await loadContracts(); await selectContract(contract.id); }, "quiet")); detail.append(actions);
  const tabs = node("div", null, "tabs"); tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Contract details");
  const content = node("div"); content.setAttribute("role", "tabpanel"); content.id = "contract-tab-panel";
  const entries = [ ["Overview", null], ["Obligations", contract.obligations], ["Risks", contract.risks], ["Clauses", contract.clauses], ["Source", contract.chunks] ];
  for (const [label, items] of entries) {
    const tab = button(label + (items ? ` (${items.length})` : ""), () => showTab(tab, label, items));
    tab.setAttribute("role", "tab"); tab.setAttribute("aria-controls", content.id); tab.setAttribute("aria-selected", "false"); tabs.append(tab);
  }
  function showTab(selectedTab, label, items) {
    for (const tab of tabs.children) { tab.setAttribute("aria-selected", String(tab === selectedTab)); tab.tabIndex = tab === selectedTab ? 0 : -1; }
    content.replaceChildren();
    if (!items) {
      const facts = node("div", null, "facts");
      fact(facts, "Agreement type", contract.contract_type); fact(facts, "Governing law", contract.governing_law);
      fact(facts, "Effective", contract.effective_date); fact(facts, "Expires", contract.expiration_date); fact(facts, "Renews", contract.renewal_date);
      fact(facts, "Parties", contract.parties.map(p => `${p.name}${p.role ? ` (${p.role})` : ""}`).join("; ")); fact(facts, "Payment terms", contract.payment_terms);
      content.append(facts);
      if (contract.status !== "completed") content.append(node("p", "Run a review to extract metadata, obligations, clauses, and risks.", "hint"));
      return;
    }
    if (!items.length) content.append(node("p", `No ${label.toLowerCase()} identified.`, "muted"));
    for (const item of items) {
      const card = node("article", null, "result-card");
      if (label === "Source") { card.append(node("h3", `Page ${item.page_number}`), node("div", item.content, "source-text")); }
      else {
        card.append(node("h3", item.title || item.category || item.clause_type.replaceAll("_", " ")));
        const level = item.priority || item.level;
        if (level) card.append(node("span", level, `badge ${level}`));
        if (item.description) card.append(node("p", item.description));
        for (const [key, title] of [["responsible_party", "Responsible"], ["counterparty", "Counterparty"], ["due_date", "Due"], ["recurring_frequency", "Frequency"], ["why_it_matters", "Why it matters"], ["recommendation", "Review action"]]) {
          if (item[key]) card.append(node("p", `${title}: ${item[key]}`));
        }
        evidence(card, item.source_text, item.page_number); card.append(node("p", `Model confidence: ${Math.round(item.confidence * 100)}%`, "hint"));
      }
      content.append(card);
    }
  }
  tabs.addEventListener("keydown", event => {
    const buttons = [...tabs.children]; const index = buttons.indexOf(event.target);
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step) { event.preventDefault(); const target = buttons[(index + step + buttons.length) % buttons.length]; target.click(); target.focus(); }
  });
  detail.append(tabs, content); showTab(tabs.firstChild, "Overview", null);
  const ask = node("section", null, "ask-panel"); ask.append(node("h3", "Ask this agreement"), node("p", "Answers include the supporting source passages.", "hint"));
  const form = node("form", null, "question-row"); const input = node("input"); input.placeholder = "What notice is required to terminate?"; input.setAttribute("aria-label", "Question about this agreement"); input.maxLength = 2000; input.required = true;
  const submit = node("button", "Ask ↗"); submit.type = "submit"; const answer = node("div", null, "answer");
  form.append(input, submit); form.addEventListener("submit", event => { event.preventDefault(); perform(submit, async () => {
    answer.textContent = "Finding supporting evidence…";
    try {
      const result = await api(`/contracts/${contract.id}/questions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: input.value }) });
      answer.replaceChildren(node("p", result.answered ? result.answer : "This agreement does not provide enough evidence to answer that question."));
      for (const source of result.sources) evidence(answer, source.excerpt, source.page_number);
    } catch (error) { answer.textContent = "The answer could not be generated. Try again when the model is available."; throw error; }
  }); }); ask.append(form, answer); detail.append(ask);
  const search = node("section", null, "ask-panel"); search.append(node("h3", "Find a passage"));
  const searchForm = node("form", null, "question-row"); const query = node("input");
  query.placeholder = "Search for a clause or topic"; query.setAttribute("aria-label", "Search this agreement"); query.required = true; query.maxLength = 2000;
  const searchButton = node("button", "Search"); searchButton.type = "submit"; const results = node("div", null, "answer");
  searchForm.append(query, searchButton); searchForm.addEventListener("submit", event => { event.preventDefault(); perform(searchButton, async () => {
    results.textContent = "Searching this agreement…";
    try {
      const response = await api(`/contracts/${contract.id}/search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query.value, top_k: 5 }) });
      results.replaceChildren(); for (const match of response.results) evidence(results, match.text, match.page_number);
      if (!response.results.length) results.textContent = "No matching passages found.";
    } catch (error) { results.textContent = "Search is unavailable. Try again when the embedding model is available."; throw error; }
  }); }); search.append(searchForm, results); detail.append(search);
}
$("login-form").addEventListener("submit", event => { event.preventDefault(); perform(event.submitter, connect); });
$("sign-out").addEventListener("click", signOut);
$("show-upload").addEventListener("click", () => { $("upload-panel").hidden = !$("upload-panel").hidden; });
$("cancel-upload").addEventListener("click", () => { $("upload-panel").hidden = true; });
$("upload-form").addEventListener("submit", event => { event.preventDefault(); perform(event.submitter, async () => {
  const data = new FormData(); data.append("file", $("pdf").files[0]); if ($("title").value.trim()) data.append("title", $("title").value.trim());
  const contract = await api("/contracts", { method: "POST", body: data }); $("upload-form").reset(); $("upload-panel").hidden = true;
  state.offset = 0; await loadContracts(); await selectContract(contract.id); message("Contract uploaded. Ready for review.");
}); });
$("filter-form").addEventListener("submit", event => { event.preventDefault(); state.offset = 0; perform(event.submitter, loadContracts); });
$("previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - 50); perform($("previous"), loadContracts); });
$("next").addEventListener("click", () => { state.offset += 50; perform($("next"), loadContracts); });
