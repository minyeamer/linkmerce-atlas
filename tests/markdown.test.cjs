const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { JSDOM } = require("jsdom");
const root = path.resolve(__dirname, "..");

function setup() {
  const dom = new JSDOM('<!doctype html><main id="result"></main>', {
    url: "http://localhost:8088/",
    runScripts: "outside-only",
  });
  for (const filename of [
    "vendor/markdown-it.min.js",
    "vendor/purify.min.js",
    "markdown.js",
  ]) {
    dom.window.eval(
      readFileSync(path.join(root, "app/static", filename), "utf8"),
    );
  }
  const calls = [];
  const render = (text) => {
    const result = dom.window.document.getElementById("result");
    result.replaceChildren(
      dom.window.LinkmerceMarkdown.render(text, (id) => {
        const button = dom.window.document.createElement("button");
        button.className = "cite";
        button.textContent = id.slice(0, 7);
        button.onclick = () => calls.push(id);
        return button;
      }),
    );
    return result;
  };
  return { dom, render, calls };
}

test("renders the reported answer with emphasis, identifiers and semantic lists", () => {
  const { dom, render } = setup();
  const result = render(
    "`smartstore_order` Dag은 **dbt selector**와 연결됩니다.\n\n- **BigQuery**: `smartstore__sales_daily` [Eba0f57af0427]\n- **Postgres**: `smartstore__sales_summary` [Ea28b4dace71f]",
  );
  assert.equal(result.querySelector("p code").textContent, "smartstore_order");
  assert.equal(result.querySelector("p strong").textContent, "dbt selector");
  assert.equal(result.querySelectorAll("ul > li").length, 2);
  assert.equal(result.querySelectorAll(".cite").length, 2);
  assert(!result.textContent.includes("**"));
  dom.window.close();
});

test("keeps clickable citations within nested formatting, lists and table cells", () => {
  const { dom, render, calls } = setup();
  const result = render(
    "**근거 [Eba0f57af0427]**\n\n1. 첫째 [E1c488620c614]\n   - 중첩 [Ea28b4dace71f]\n\n| 대상 | 출처 |\n| --- | --- |\n| dbt | [E17eaf1e4fbb2] |",
  );
  assert(result.querySelector("strong > button.cite"));
  assert(result.querySelector("ol ul button.cite"));
  assert(result.querySelector(".markdown-table td button.cite"));
  result.querySelector("button.cite").click();
  assert.deepEqual(calls, ["Eba0f57af0427"]);
  assert.equal(result.querySelector("button.cite").type, "button");
  assert.match(
    result.querySelector("button.cite").getAttribute("aria-label"),
    /근거/,
  );
  dom.window.close();
});

test("preserves fenced code and inline code without converting example citation syntax", () => {
  const { dom, render } = setup();
  const result = render(
    "# 흐름\n\n`[Eba0f57af0427]`\n\n```sql\nSELECT * FROM smartstore.order;\n-- [E1c488620c614]\n```\n\n> 실행 조건은 별도 확인\n\n---",
  );
  assert.equal(result.querySelector("h1").textContent, "흐름");
  assert.match(result.querySelector("pre code").textContent, /SELECT \*/);
  assert.equal(result.querySelectorAll("button").length, 0);
  assert(result.querySelector("blockquote"));
  assert(result.querySelector("hr"));
  dom.window.close();
});

test("blocks raw HTML, executable links and remote image requests", () => {
  const { dom, render } = setup();
  const result = render(
    "<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n\n[unsafe](javascript:alert%281%29)\n\n[encoded](java&#x73;cript:alert%281%29)\n\n![tracking](https://untrusted.example/pixel.png)\n\n[allowed](https://example.com/docs)",
  );
  assert.equal(result.querySelectorAll("script,img,iframe,svg").length, 0);
  assert.equal(result.querySelectorAll("[onclick],[onerror]").length, 0);
  const links = [...result.querySelectorAll("a")];
  assert.equal(links.length, 1);
  assert.equal(links[0].href, "https://example.com/docs");
  assert.equal(links[0].target, "_blank");
  assert.equal(links[0].rel, "noopener noreferrer");
  dom.window.close();
});

test("renders synthetic onboarding answers without an AI request", () => {
  const { dom, render } = setup();
  const report = JSON.parse(
    readFileSync(path.join(root, "tests/fixtures/markdown-answers.json")),
  );
  for (const item of report.results) {
    const result = render(item.answer);
    assert(result.querySelector("p"));
    assert(result.querySelector("button.cite"));
    assert.equal(result.querySelectorAll("script").length, 0);
  }
  dom.window.close();
});

test("the message integration renders assistant Markdown and keeps user text literal", async () => {
  const { dom } = setup();
  const page = readFileSync(path.join(root, "app/static/index.html"), "utf8");
  dom.window.document.body.innerHTML = page.slice(
    page.indexOf("<body>") + 6,
    page.indexOf("</body>"),
  );
  dom.window.HTMLElement.prototype.scrollIntoView = () => {};
  dom.window.fetch = async (url) => ({
    ok: true,
    json: async () => {
      if (url.startsWith("/api/search")) return [];
      if (url === "/api/auth/status")
        return { connected: false, chatgpt_enabled: false };
      return {
        nodes: 0,
        edges: 0,
        derived_paths: 0,
        files: 0,
        warnings: [],
        fingerprint: "test",
        wirelog_revision: "test",
        indexed_at: "2026-10-28T00:00:00Z",
      };
    },
  });
  dom.window.eval(readFileSync(path.join(root, "app/static/app.js"), "utf8"));
  dom.window.addMessage("user", "**문자 그대로** <script>");
  dom.window.addMessage("assistant", "**강조**와 `코드` [Eba0f57af0427]");
  const user = dom.window.document.querySelector(".message.user .body");
  const assistant = dom.window.document.querySelector(
    ".message.assistant .body",
  );
  assert.equal(user.textContent, "**문자 그대로** <script>");
  assert.equal(user.children.length, 0);
  assert(assistant.matches(".markdown-body"));
  assert.equal(assistant.querySelector("strong").textContent, "강조");
  assert(assistant.querySelector("button.cite"));
  await new Promise((resolve) => setImmediate(resolve));
  dom.window.close();
});
