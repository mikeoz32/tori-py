import {ToriElement} from "./base.js";

export class ToriChatLog extends ToriElement {
  connect() {
    this.pinned = !this.hasAttribute("data-tori-ui-unpinned");
    this.listen(this, "scroll", () => {
      this.pinned = this.scrollHeight - this.scrollTop - this.clientHeight < 48;
      this.mark();
    }, {passive: true});
    this.listen(this, "click", (event) => {
      if (!(event.target instanceof Element) || !event.target.closest(".tori-ui-chat-log__jump")) return;
      this.pinned = true;
      this.follow();
      this.focus();
    });
    this.observe(this, {childList: true, subtree: true, characterData: true});
    this.messages = null;
    this.sizes = new ResizeObserver(() => this.follow());
    this.observers.add(this.sizes);
  }

  updated() {
    if (!this.connection) return;
    const messages = this.querySelector(".tori-ui-chat-log__messages");
    if (this.messages !== messages) {
      this.sizes.disconnect();
      this.messages = messages;
      if (messages) this.sizes.observe(messages);
    }
    this.follow();
  }

  mark() { this.toggleAttribute("data-tori-ui-unpinned", !this.pinned); }
  follow() {
    if (this.pinned) this.scrollTop = this.scrollHeight;
    this.mark();
  }
}
