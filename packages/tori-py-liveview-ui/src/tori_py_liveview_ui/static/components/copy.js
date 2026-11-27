import {ToriElement} from "./base.js";

const writeClipboard = async (text) => {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const focused = document.activeElement;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  (focused?.closest("dialog[open]") ?? document.body).append(area);
  area.select();
  try {
    if (!document.execCommand("copy")) throw new Error("Clipboard copy failed");
  } finally {
    area.remove();
    focused?.focus({preventScroll: true});
  }
};

// Keep complete messages and preformatted whitespace; omit presentation controls.
const copyText = (source) => {
  if (source.nodeType === Node.TEXT_NODE) return source.textContent.replace(/\s+/g, " ");
  if (!(source instanceof Element)) return "";
  if (source.hasAttribute("data-tori-ui-copy-text")) return source.getAttribute("data-tori-ui-copy-text");
  if (source.matches("[data-tori-ui-copy-exclude], button, input, select, textarea, svg, script, style")) return "";
  if (getComputedStyle(source).display === "none") return "";
  if (source.tagName === "BR") return "\n";
  if (source.matches("pre, code")) return source.textContent;
  const children = source.matches("details:not([open])")
    ? [source.querySelector("summary")].filter(Boolean) : [...source.childNodes];
  let text = "";
  for (const child of children) {
    const part = copyText(child);
    if (!part) continue;
    const block = child instanceof Element && !getComputedStyle(child).display.startsWith("inline");
    const paragraph = block && child.matches("p, h1, h2, h3, h4, h5, h6");
    const gap = paragraph ? "\n\n" : block ? "\n" : "";
    if (gap && text && !text.endsWith("\n")) text += gap;
    if (!part.trim() && text.endsWith("\n")) continue;
    text += part;
    if (gap && !text.endsWith("\n")) text += gap;
  }
  return text;
};

export class ToriCopy extends ToriElement {
  static properties = {to: {type: String}, scope: {type: String}};

  connect() {
    this.listen(this, "click", (event) => {
      const button = event.target instanceof Element ? event.target.closest("button") : null;
      if (!button || button.closest("tori-ui-copy") !== this || button.disabled) return;
      this.copy(button);
    });
  }

  async copy(button) {
    const connection = this.connection;
    try {
      const target = this.scope === "closest" ? button.closest(this.to)
        : this.scope === "inner" ? button.querySelector(this.to) : document.querySelector(this.to);
      if (!target) return;
      const source = target.matches("[data-tori-ui-copy-source]") ? target
        : target.querySelector("[data-tori-ui-copy-source]") ?? target;
      const exact = source.hasAttribute("data-tori-ui-copy-text") ||
        typeof source.value === "string" || source.matches("pre, code");
      const content = typeof source.value === "string" ? source.value : copyText(source);
      await writeClipboard(exact ? content : content.replace(/^\n+|\n+$/g, ""));
      if (connection.signal.aborted || !this.isConnected) return;
      const status = button.querySelector('[role="status"]');
      button.setAttribute("data-tori-ui-copied", "");
      if (status) status.textContent = button.getAttribute("data-tori-ui-copied-label") ?? "";
      this.clearTimer(this.copiedTimer);
      this.copiedTimer = this.later(() => {
        button.removeAttribute("data-tori-ui-copied");
        if (status) status.textContent = "";
      }, 2000);
    } catch { /* Unavailable clipboard and invalid/missing selectors leave the control usable. */ }
  }
}
