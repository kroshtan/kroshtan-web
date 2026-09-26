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
