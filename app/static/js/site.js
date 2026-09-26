// Progressive enhancement only: every page works without JavaScript.

// Copy-to-clipboard for the email address. The button stays hidden unless the Clipboard API exists.
for (const button of document.querySelectorAll("[data-copy]")) {
  if (!navigator.clipboard) continue;
  const block = button.closest(".email-block");
  const source = block.querySelector("[data-copy-source]");
  const label = button.querySelector("[data-copy-label]");
  const status = block.querySelector("[data-copy-status]");
  const original = label.textContent;
  button.hidden = false;
  button.setAttribute("aria-label", `${original} email address`);

  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(source.textContent.trim());
    } catch {
      return;
    }
    label.textContent = button.dataset.copiedLabel;
    status.textContent = "Email address copied to clipboard";
    button.classList.add("is-copied");
    setTimeout(() => {
      label.textContent = original;
      status.textContent = "";
      button.classList.remove("is-copied");
    }, 2000);
  });
}

// "Can I help with this?": POST the question, stream the plain-text answer into the page.
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// A deliberately tiny Markdown subset: paragraphs, "- " lists, **bold**, *italic*, and email links.
// Everything is escaped first, so nothing the model writes can inject markup.
function renderAnswer(text) {
  const inline = (s) =>
    escapeHtml(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/([\w.+-]+@[\w-]+\.[\w.-]*\w)/g, '<a href="mailto:$1">$1</a>');
  return text
    .trim()
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*] /.test(l))) {
        return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
      }
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    })
    .join("");
}

for (const root of document.querySelectorAll("[data-ask]")) {
  const form = root.querySelector("[data-ask-form]");
  const textarea = form.querySelector("textarea");
  const submit = form.querySelector("[data-ask-submit]");
  const count = form.querySelector("[data-ask-count]");
  const answer = root.querySelector("[data-ask-answer]");
  const body = root.querySelector("[data-ask-body]");
  const submitLabel = submit.textContent;
  form.hidden = false;

  const updateCount = () => {
    count.textContent = `${textarea.value.length} / ${textarea.maxLength}`;
  };
  textarea.addEventListener("input", updateCount);
  updateCount();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;

    submit.disabled = true;
    submit.textContent = form.dataset.submittingLabel;
    answer.hidden = false;
    answer.setAttribute("aria-busy", "true");
    answer.classList.remove("is-error");
    body.innerHTML = '<p class="ask-pending"><span></span><span></span><span></span></p>';

    let text = "";
    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: textarea.value }),
      });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        answer.classList.add("is-error");
        text = data.message || form.dataset.errorMessage;
      } else {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          text += decoder.decode(value, { stream: true });
          body.innerHTML = renderAnswer(text);
        }
        text += decoder.decode();
      }
    } catch {
      answer.classList.add("is-error");
      text = text ? `${text}\n\n${form.dataset.errorMessage}` : form.dataset.errorMessage;
    }
    body.innerHTML = renderAnswer(text);
    answer.setAttribute("aria-busy", "false");
    submit.disabled = false;
    submit.textContent = submitLabel;
  });
}
