import {ToriElement} from "./base.js";

export class ToriTabs extends ToriElement {
  connect() {
    this.listen(this, "keydown", (event) => {
      const tabs = [...this.querySelectorAll('[role="tab"]')]
        .filter((tab) => tab.closest("tori-ui-tabs") === this);
      const index = tabs.indexOf(document.activeElement);
      if (index === -1) return;
      const last = tabs.length - 1;
      const next = {ArrowRight: index === last ? 0 : index + 1,
        ArrowLeft: index === 0 ? last : index - 1, Home: 0, End: last}[event.key];
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].focus();
      tabs[next].click();
    });
  }
}
