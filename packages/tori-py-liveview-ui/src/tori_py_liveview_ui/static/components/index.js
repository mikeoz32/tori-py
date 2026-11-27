import {ToriMode} from "./mode.js";
import {ToriConfirm} from "./confirm.js";
import {ToriCopy} from "./copy.js";
import {ToriToast} from "./toast.js";
import {ToriTabs} from "./tabs.js";
import {ToriTooltip} from "./tooltip.js";
import {ToriChatLog} from "./chat-log.js";
import {ToriComposer} from "./composer.js";
import {ToriDialog} from "./dialog.js";
import {ToriPopup} from "./popup.js";
import {ToriAppShell} from "./app-shell.js";

// Each element owns its behavior and waits for Phoenix only for its hook bridge.
// Registration resolves the document gate before the first LiveView join.
for (const [name, element] of Object.entries({
  "tori-ui-mode": ToriMode, "tori-ui-confirm": ToriConfirm, "tori-ui-copy": ToriCopy,
  "tori-ui-toast": ToriToast, "tori-ui-tabs": ToriTabs, "tori-ui-tooltip": ToriTooltip,
  "tori-ui-chat-log": ToriChatLog, "tori-ui-composer": ToriComposer,
  "tori-ui-dialog": ToriDialog, "tori-ui-popup": ToriPopup, "tori-ui-app-shell": ToriAppShell,
})) {
  if (!customElements.get(name)) customElements.define(name, element);
}
window.dispatchEvent(new CustomEvent("tori-ui:defined"));
