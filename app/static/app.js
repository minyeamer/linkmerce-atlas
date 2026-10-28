const $ = (id) => document.getElementById(id);
let focus = null,
  kind = "",
  nodes = new Map(),
  stats = null,
  searchTimer,
  account = null,
  busy = false,
  evidenceMap = new Map();
const symbols = {
  module: "{ }",
  function: "ƒ",
  dag: "⌁",
  model: "◇",
  table: "▤",
  source: "↳",
  macro: "λ",
  selector: "⋈",
  plugin: "⊞",
};
async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error("서버 응답을 읽지 못했습니다.");
  }
  if (!response.ok) throw new Error(data.detail || "요청에 실패했습니다.");
  return data;
}
function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  setTimeout(() => ($("toast").hidden = true), 5000);
}
function remember(items) {
  items.forEach((n) => nodes.set(n.id, n));
}
async function search() {
  try {
    const result = await api(
      "/api/search?" +
        new URLSearchParams({ q: $("search").value, kind, limit: 50 }),
    );
    remember(result);
    $("results").replaceChildren();
    if (!result.length)
      $("results").append(
        element("p", "일치하는 구성요소가 없습니다.", "muted"),
      );
    for (const n of result) {
      const button = element(
        "button",
        undefined,
        "result" + (n.id === focus ? " selected" : ""),
      );
      button.append(element("span", symbols[n.kind] || "·", "symbol"));
      const label = element("div");
      label.append(
        element("b", n.label),
        element("small", n.layer + " · " + n.kind),
      );
      button.append(label);
      button.onclick = () => selectNode(n.id);
      $("results").append(button);
    }
  } catch (e) {
    toast(e.message);
  }
}
async function loadStats() {
  stats = await api("/api/stats");
  $("stats").replaceChildren();
  for (const [name, value] of [
    ["구성요소", stats.nodes],
    ["선언된 관계", stats.edges],
    ["Wirelog 도달 관계", stats.derived_paths],
    ["분석한 파일", stats.files],
  ]) {
    const item = element("div");
    item.append(element("span", name), element("b", value.toLocaleString()));
    $("stats").append(item);
  }
  $("indexed").textContent =
    "갱신 " + new Date(stats.indexed_at).toLocaleString("ko-KR");
  $("warning-count").textContent = ` · ${stats.warnings.length}개`;
  $("warnings").replaceChildren();
  for (const warning of stats.warnings) {
    $("warnings").append(
      element(
        "p",
        `${warning.path}${warning.line ? ":" + warning.line : ""} · ${warning.reason}`,
      ),
    );
  }
  $("revision").textContent =
    `Source commit ${stats.commit || "unknown"} · Snapshot ${stats.fingerprint.slice(0, 16)} · Wirelog ${stats.wirelog_revision.slice(0, 12)}`;
}
function cite(id, label) {
  const button = element("button", label || "출처 ↗", "cite");
  button.onclick = () => showEvidenceId(id);
  return button;
}
async function showEvidenceId(id) {
  try {
    const ev =
      evidenceMap.get(id) ||
      (await api("/api/evidence/" + encodeURIComponent(id)));
    renderEvidence([ev], true);
  } catch (e) {
    toast(e.message);
  }
}
function renderEvidence(items, highlight = false) {
  if (!highlight) {
    $("evidence").replaceChildren();
    evidenceMap = new Map();
  }
  for (const e of items) {
    evidenceMap.set(e.id, e);
    let card = document.getElementById("ev-" + e.id);
    if (!card) {
      card = element("article", undefined, "source-card");
      card.id = "ev-" + e.id;
      const title = element("a", e.path + ":" + e.line);
      title.href = "#ev-" + e.id;
      title.onclick = (event) => {
        event.preventDefault();
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };
      card.append(
        title,
        element(
          "small",
          e.id +
            (e.format === "normalized"
              ? " · 정규화한 선언"
              : " · 색인 시점 코드 발췌"),
        ),
        element("pre", e.snippet),
      );
      $("evidence").append(card);
    }
    if (highlight) {
      document
        .querySelectorAll(".source-card")
        .forEach((c) => c.classList.remove("highlight"));
      card.classList.add("highlight");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
  $("evidence-count").textContent = evidenceMap.size;
}
async function selectNode(id) {
  try {
    const data = await api("/api/node?" + new URLSearchParams({ id }));
    focus = id;
    remember(data.nodes);
    remember(data.upstream);
    remember(data.downstream);
    $("layer-map").hidden = true;
    $("node-view").hidden = false;
    $("overview").hidden = false;
    $("map-title").textContent = data.node.label;
    $("focus-label").textContent = "질문 범위: " + data.node.label;
    $("node-summary").replaceChildren();
    $("node-summary").append(
      element(
        "div",
        `${data.node.layer} · ${data.node.kind} · 상위 ${data.upstream_count}개 · 하위 ${data.downstream_count}개 (Wirelog)`,
      ),
    );
    if (data.node.description)
      $("node-summary").append(element("p", data.node.description));
    if (data.node.schedule)
      $("node-summary").append(
        element("p", "코드에 선언된 schedule: " + data.node.schedule),
      );
    for (const eid of data.node.evidence) $("node-summary").append(cite(eid));
    drawGraph(data);
    $("relations").replaceChildren();
    for (const e of data.edges) {
      const row = element("div", undefined, "relation-row");
      for (const [i, key] of [e.source, e.target].entries()) {
        if (i)
          row.append(
            element(
              "span",
              "→ " +
                e.relation +
                (e.certainty === "conditional" ? " · 조건부" : "") +
                " →",
            ),
          );
        const button = element("button", nodes.get(key)?.label || key);
        button.onclick = () => selectNode(key);
        row.append(button);
      }
      row.append(cite(e.evidence, "↗"));
      $("relations").append(row);
    }
    if (data.total_direct_edges > data.edges.length)
      $("relations").append(
        element(
          "p",
          `직접 관계 ${data.total_direct_edges}개 중 ${data.edges.length}개를 표시합니다.`,
          "muted",
        ),
      );
    $("reach-lists").replaceChildren();
    for (const [name, list, total, direction] of [
      ["상위 구성요소", data.upstream, data.upstream_count, "up"],
      ["하위 구성요소", data.downstream, data.downstream_count, "down"],
    ]) {
      const details = element("details");
      details.append(element("summary", `${name} ${total}개 · 경로 확인`));
      for (const n of list) {
        const button = element("button", n.label + " · " + n.layer);
        button.onclick = () =>
          showPath(
            direction === "up" ? n.id : id,
            direction === "up" ? id : n.id,
          );
        details.append(button);
      }
      if (total > list.length)
        details.append(element("p", `최대 ${list.length}개 표시`));
      $("reach-lists").append(details);
    }
    await search();
  } catch (e) {
    toast(e.message);
  }
}
function drawGraph(data) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const upstream = data.nodes
    .filter(
      (n) =>
        n.id !== focus &&
        data.edges.some((e) => e.source === n.id && e.target === focus),
    )
    .slice(0, 7);
  const downstream = data.nodes
    .filter(
      (n) =>
        n.id !== focus &&
        data.edges.some((e) => e.target === n.id && e.source === focus),
    )
    .slice(0, 7);
  const height = Math.max(
    160,
    Math.max(upstream.length, downstream.length) * 42 + 25,
  );
  svg.setAttribute("viewBox", `0 0 900 ${height}`);
  svg.style.width = "100%";
  svg.style.minWidth = "650px";
  const positions = new Map([[focus, [350, height / 2 - 15]]]);
  upstream.forEach((n, i) => positions.set(n.id, [10, 15 + i * 42]));
  downstream.forEach((n, i) => positions.set(n.id, [680, 15 + i * 42]));
  for (const e of data.edges) {
    const a = positions.get(e.source),
      b = positions.get(e.target);
    if (!a || !b) continue;
    const line = document.createElementNS(ns, "path");
    line.setAttribute(
      "d",
      `M ${a[0] + 200} ${a[1] + 15} C ${a[0] + 260} ${a[1] + 15} ${b[0] - 60} ${b[1] + 15} ${b[0]} ${b[1] + 15}`,
    );
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", "#bfd6cc");
    line.setAttribute("stroke-width", "1.4");
    svg.append(line);
  }
  for (const [id, [x, y]] of positions) {
    const g = document.createElementNS(ns, "g");
    g.style.cursor = "pointer";
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
    g.setAttribute("aria-label", nodes.get(id)?.label || id);
    g.onclick = () => selectNode(id);
    g.onkeydown = (e) => {
      if (e.key === "Enter") selectNode(id);
    };
    const rect = document.createElementNS(ns, "rect");
    for (const [k, v] of Object.entries({
      x,
      y,
      width: 200,
      height: 30,
      rx: 5,
      fill: id === focus ? "#087e67" : "white",
      stroke: id === focus ? "#087e67" : "#d7e5df",
    }))
      rect.setAttribute(k, v);
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", x + 10);
    text.setAttribute("y", y + 19);
    text.setAttribute("font-size", "10");
    text.setAttribute("fill", id === focus ? "white" : "#527165");
    const label = nodes.get(id)?.label || id;
    text.textContent = label.length > 32 ? label.slice(0, 29) + "…" : label;
    const title = document.createElementNS(ns, "title");
    title.textContent = label;
    g.append(rect, text, title);
    svg.append(g);
  }
  $("graph-canvas").replaceChildren(svg);
}
async function showPath(source, target) {
  try {
    const result = await api(
      "/api/path?" + new URLSearchParams({ source, target }),
    );
    if (!result.reachable) {
      toast("현재 색인에서 연결 경로를 찾지 못했습니다.");
      return;
    }
    renderEvidence(result.evidence);
    const lines = result.edges
      .map(
        (e) =>
          `${nodes.get(e.source)?.label || e.source} → ${nodes.get(e.target)?.label || e.target} (${e.relation}) [${e.evidence}]`,
      )
      .join("\n\n");
    addMessage("assistant", "Wirelog가 확인한 경로입니다.\n\n" + lines);
  } catch (e) {
    toast(e.message);
  }
}
function addMessage(role, text) {
  const welcome = document.querySelector(".welcome");
  if (welcome) welcome.remove();
  const box = element("article", undefined, "message " + role);
  box.append(
    element("div", role === "user" ? "YOU" : "LINKMERCE ATLAS", "role"),
  );
  const body = element("div", undefined, "body");
  const pattern = /\[(E[0-9a-f]{12})\]/g;
  let end = 0;
  for (const match of text.matchAll(pattern)) {
    body.append(
      document.createTextNode(text.slice(end, match.index)),
      cite(match[1], match[1].slice(0, 7)),
    );
    end = match.index + match[0].length;
  }
  body.append(document.createTextNode(text.slice(end)));
  box.append(body);
  $("messages").append(box);
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return box;
}
async function ask(question) {
  if (busy) return;
  if ($("mode").value === "ai" && !account?.connected) {
    $("account-dialog").showModal();
    return;
  }
  busy = true;
  $("send").disabled = true;
  addMessage("user", question);
  $("question").value = "";
  const pending = addMessage(
    "assistant",
    "코드 관계와 근거를 확인하고 있습니다…",
  );
  try {
    const result = await api("/api/ask", {
      method: "POST",
      body: JSON.stringify({
        question,
        focus,
        mode: $("mode").value,
        model: $("model").value || "gpt-6-luna",
      }),
    });
    pending.remove();
    renderEvidence(result.evidence);
    const box = addMessage("assistant", result.answer);
    if (result.audit.length)
      box.append(element("p", result.audit.join(" "), "audit"));
    box.append(
      element(
        "small",
        result.provider === "chatgpt"
          ? "Using your ChatGPT plan"
          : result.provider === "openai"
            ? "OpenAI API · 사용자 API 계정 사용"
            : "Wirelog + 소스 근거 탐색",
        "muted",
      ),
    );
  } catch (e) {
    pending.remove();
    addMessage("assistant", "답변을 완료하지 못했습니다. " + e.message);
  } finally {
    busy = false;
    $("send").disabled = false;
  }
}
async function authStatus() {
  account = await api("/api/auth/status");
  $("account-label").textContent = account.connected
    ? account.provider === "chatgpt"
      ? "ChatGPT 연결됨"
      : "OpenAI API 연결됨"
    : "AI 계정 연결";
  $("connected-account").hidden = !account.connected;
  $("connect-options").hidden = account.connected;
  $("model-control").hidden = !account.connected;
  $("identity").textContent = account.identity || "";
  $("usage-label").textContent =
    account.provider === "chatgpt"
      ? "질문은 내 ChatGPT 구독 할당량을 사용합니다."
      : "질문은 내 OpenAI API 계정에 과금됩니다.";
  $("usage").hidden = account.provider !== "chatgpt";
  $("chatgpt-login").classList.toggle("disabled", !account.chatgpt_enabled);
  $("chatgpt-login").setAttribute(
    "aria-disabled",
    String(!account.chatgpt_enabled),
  );
  $("oauth-note").textContent = account.chatgpt_enabled
    ? "로그인과 함께 ChatGPT 구독 사용 권한을 승인하세요."
    : account.chatgpt_note + " 현재 배포에는 등록 정보가 없습니다.";
  if (account.connected) {
    const modelList = await api("/api/models");
    $("model").replaceChildren();
    for (const model of modelList) {
      const option = element("option", model.name);
      option.value = model.id;
      $("model").append(option);
    }
    const preferred = [
      account.selected_model,
      account.default_model,
      "gpt-6-luna",
      "gpt-6.1-sol",
      "gpt-5.4-mini",
      "gpt-4.1-mini",
    ].find((id) => modelList.some((m) => m.id === id));
    if (preferred) $("model").value = preferred;
    $("mode").value = "ai";
  }
}
$("search").oninput = () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(search, 180);
};
$("filters").onclick = (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  kind = button.dataset.kind;
  document
    .querySelectorAll(".filters button")
    .forEach((b) => b.classList.toggle("active", b === button));
  search();
};
document.querySelectorAll(".layer").forEach(
  (el) =>
    (el.onclick = () => {
      $("search").value = el.dataset.query;
      kind = "";
      search();
    }),
);
$("overview").onclick = () => {
  focus = null;
  $("node-view").hidden = true;
  $("layer-map").hidden = false;
  $("overview").hidden = true;
  $("map-title").textContent = "Linkmerce의 구성";
  $("focus-label").textContent = "전체 프로젝트에서 검색";
  search();
};
document
  .querySelectorAll(".suggestions button")
  .forEach((button) => (button.onclick = () => ask(button.textContent)));
$("ask-form").onsubmit = (e) => {
  e.preventDefault();
  const q = $("question").value.trim();
  if (q) ask(q);
};
$("question").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("ask-form").requestSubmit();
  }
};
$("account-button").onclick = () => {
  $("auth-error").textContent = "";
  $("account-dialog").showModal();
};
$("close-dialog").onclick = () => $("account-dialog").close();
$("key-form").onsubmit = async (e) => {
  e.preventDefault();
  $("key-submit").disabled = true;
  $("auth-error").textContent = "";
  const key = $("api-key").value.trim();
  $("api-key").value = "";
  try {
    await api("/api/auth/api-key", {
      method: "POST",
      body: JSON.stringify({ key }),
    });
    await authStatus();
    toast("AI 계정을 연결했습니다.");
  } catch (error) {
    $("auth-error").textContent = error.message;
  } finally {
    $("key-submit").disabled = false;
  }
};
$("logout").onclick = async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    $("mode").value = "evidence";
    await authStatus();
    toast("AI 계정 연결을 해제했습니다.");
  } catch (e) {
    $("auth-error").textContent = e.message;
  }
};
$("refresh").onclick = async () => {
  const headers = {};
  if (stats?.admin_required) {
    const token = prompt("색인 갱신용 관리자 토큰");
    if (!token) return;
    headers["x-admin-token"] = token;
  }
  $("refresh").disabled = true;
  try {
    await api("/api/reindex", { method: "POST", headers });
    await loadStats();
    await search();
    if (focus) await selectNode(focus);
    toast("새 소스에서 관계를 갱신했습니다.");
  } catch (e) {
    toast(e.message);
  } finally {
    $("refresh").disabled = false;
  }
};
document.addEventListener("keydown", (e) => {
  if (
    e.key === "/" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  ) {
    e.preventDefault();
    $("search").focus();
  }
});
Promise.all([loadStats(), search(), authStatus()]).catch((e) =>
  toast(e.message),
);

$("model").onchange = async () => {
  try {
    await api("/api/auth/model", {
      method: "POST",
      body: JSON.stringify({ model: $("model").value }),
    });
  } catch (error) {
    toast(error.message);
  }
};
