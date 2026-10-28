/* AI 답변만 안전하게 렌더링하고 출처를 실제 버튼으로 연결한다. */
(function () {
  "use strict";

  const parser = window.markdownit
    ? new window.markdownit({ html: false, linkify: false, typographer: false })
    : null;

  if (parser) {
    // 답변을 읽는 것만으로 외부 이미지를 요청하지 않는다.
    parser.renderer.rules.image = (tokens, index) =>
      parser.utils.escapeHtml(tokens[index].content || "이미지");
  }

  function attachCitations(fragment, createCitation) {
    const walker = document.createTreeWalker(
      fragment,
      window.NodeFilter.SHOW_TEXT,
    );
    const texts = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.parentElement?.closest("pre, code, a, button"))
        texts.push(node);
    }
    for (const node of texts) {
      const pattern = /\[(E[0-9a-f]{12})\]/g;
      const matches = [...node.textContent.matchAll(pattern)];
      if (!matches.length) continue;
      const replacement = document.createDocumentFragment();
      let end = 0;
      for (const match of matches) {
        replacement.append(
          document.createTextNode(node.textContent.slice(end, match.index)),
        );
        const button = createCitation(match[1]);
        button.type = "button";
        button.title = `근거 ${match[1]} 보기`;
        button.setAttribute("aria-label", `근거 ${match[1]} 보기`);
        replacement.append(button);
        end = match.index + match[0].length;
      }
      replacement.append(document.createTextNode(node.textContent.slice(end)));
      node.replaceWith(replacement);
    }
  }

  function render(text, createCitation) {
    let fragment;
    if (parser && window.DOMPurify) {
      fragment = window.DOMPurify.sanitize(parser.render(text), {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: [
          "p",
          "br",
          "strong",
          "em",
          "s",
          "code",
          "pre",
          "blockquote",
          "ul",
          "ol",
          "li",
          "h1",
          "h2",
          "h3",
          "h4",
          "h5",
          "h6",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
          "a",
          "hr",
        ],
        ALLOWED_ATTR: ["href", "title", "start", "class"],
        ALLOW_DATA_ATTR: false,
        ALLOW_ARIA_ATTR: false,
      });
    } else {
      fragment = document.createDocumentFragment();
      fragment.append(document.createTextNode(text));
    }

    for (const link of fragment.querySelectorAll("a")) {
      const href = link.getAttribute("href");
      let allowed = false;
      try {
        allowed =
          Boolean(href) &&
          ["http:", "https:", "mailto:"].includes(
            new URL(href, window.location.href).protocol,
          );
      } catch {
        /* 잘못된 URL은 일반 텍스트로 표시한다. */
      }
      if (!allowed) {
        link.replaceWith(...link.childNodes);
        continue;
      }
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }

    attachCitations(fragment, createCitation);
    for (const table of fragment.querySelectorAll("table")) {
      const wrapper = document.createElement("div");
      wrapper.className = "markdown-table";
      table.replaceWith(wrapper);
      wrapper.append(table);
    }
    return fragment;
  }

  window.LinkmerceMarkdown = Object.freeze({ render });
})();
