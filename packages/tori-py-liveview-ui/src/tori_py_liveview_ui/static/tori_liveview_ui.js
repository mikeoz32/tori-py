/* Tori UI: Phoenix LiveView hooks and browser behavior for the components. */
;(() => {
  "use strict";

  const MODE_KEY = "tori-ui-mode";
  const MODES = ["auto", "light", "dark"];
  const root = document.documentElement;

  // ----------------------------------------------------------------- Mode

  // A color mode the visitor chose earlier wins over the document's default.
  // It is applied here, before the body is parsed, so the page never paints
  // twice.
  const storedMode = () => {
    try {
      const mode = localStorage.getItem(MODE_KEY);
      return MODES.includes(mode) ? mode : null;
    } catch {
      return null;
    }
  };
  const applyMode = (mode) => {
    root.dataset.toriUiMode = mode;
  };
  const initialMode = storedMode();
  if (initialMode !== null) applyMode(initialMode);

  const hooks = {};

  // mode_toggle(): marks the current mode and stores the visitor's choice.
  hooks.ToriUiMode = {
    mounted() {
      this.sync = () => {
        const current = root.dataset.toriUiMode ?? "auto";
        for (const option of this.el.querySelectorAll("[data-tori-ui-mode-value]")) {
          const pressed = option.dataset.toriUiModeValue === current;
          option.setAttribute("aria-pressed", String(pressed));
        }
      };
      this.el.addEventListener("click", (event) => {
        const option =
          event.target instanceof Element
            ? event.target.closest("[data-tori-ui-mode-value]")
            : null;
        if (option === null || !this.el.contains(option)) return;
        const mode = option.dataset.toriUiModeValue;
        if (!MODES.includes(mode)) return;
        applyMode(mode);
        try {
          localStorage.setItem(MODE_KEY, mode);
        } catch {
          // Storage can be unavailable; the choice then lasts for this page.
        }
        // Every toggle on the page follows the one that was used.
        window.dispatchEvent(new CustomEvent("tori-ui:mode"));
      });
      window.addEventListener("tori-ui:mode", this.sync);
      this.sync();
    },
    updated() {
      this.sync();
    },
    destroyed() {
      window.removeEventListener("tori-ui:mode", this.sync);
    },
  };

  // -------------------------------------------------------------- Confirm

  // button(confirm=...): asks before the click reaches the LiveView client,
  // whose own click listeners are added to window after this one.
  window.addEventListener(
    "click",
    (event) => {
      const element =
        event.target instanceof Element
          ? event.target.closest("[data-tori-ui-confirm]")
          : null;
      if (element === null) return;
      if (!window.confirm(element.getAttribute("data-tori-ui-confirm"))) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    },
    true,
  );

  // ----------------------------------------------------------------- Copy

  const copiedTimers = new WeakMap();

  const writeClipboard = async (text) => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    // Plain HTTP on another host has no Clipboard API.
    const focused = document.activeElement;
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    const dialog = document.activeElement?.closest("dialog[open]");
    (dialog ?? document.body).append(area);
    area.select();
    try {
      if (!document.execCommand("copy")) throw new Error("Clipboard copy failed");
    } finally {
      area.remove();
      focused?.focus({preventScroll: true});
    }
  };

  const copySource = (target) => {
    if (target.matches("[data-tori-ui-copy-source]")) return target;
    return target.querySelector("[data-tori-ui-copy-source]") ?? target;
  };

  // Read content without copying the controls used to present it. Preformatted
  // text keeps its whitespace; ordinary blocks keep paragraph boundaries.
  const copyText = (source) => {
    if (source.nodeType === Node.TEXT_NODE) {
      return source.textContent.replace(/\s+/g, " ");
    }
    if (!(source instanceof Element)) return "";
    if (source.hasAttribute("data-tori-ui-copy-text")) {
      return source.getAttribute("data-tori-ui-copy-text");
    }
    if (source.matches(
      "[data-tori-ui-copy-exclude], button, input, select, textarea, svg, script, style",
    )) {
      return "";
    }
    if (getComputedStyle(source).display === "none") return "";
    if (source.tagName === "BR") return "\n";
    if (source.matches("pre, code")) return source.textContent;
    const children = source.matches("details:not([open])")
      ? [source.querySelector("summary")].filter(Boolean)
      : [...source.childNodes];
    let text = "";
    for (const child of children) {
      const part = copyText(child);
      if (!part) continue;
      const block = child instanceof Element &&
        !getComputedStyle(child).display.startsWith("inline");
      const paragraph = block && child.matches("p, h1, h2, h3, h4, h5, h6");
      const gap = paragraph ? "\n\n" : block ? "\n" : "";
      if (gap && text && !text.endsWith("\n")) text += gap;
      if (!part.trim() && text.endsWith("\n")) continue;
      text += part;
      if (gap && !text.endsWith("\n")) text += gap;
    }
    return text;
  };

  // copy_button(): a JS dispatch names the element; this listener copies its
  // text and reports back on the button that dispatched.
  window.addEventListener("tori-ui:copy", (event) => {
    if (!(event.target instanceof Element)) return;
    const source = copySource(event.target);
    const exact = source.hasAttribute("data-tori-ui-copy-text") ||
      typeof source.value === "string" || source.matches("pre, code");
    const content = typeof source.value === "string" ? source.value : copyText(source);
    const text = exact ? content : content.replace(/^\n+|\n+$/g, "");
    const button = event.detail?.dispatcher;
    writeClipboard(text).then(
      () => {
        if (!(button instanceof Element)) return;
        const status = button.querySelector('[role="status"]');
        button.setAttribute("data-tori-ui-copied", "");
        if (status !== null) {
          status.textContent = button.getAttribute("data-tori-ui-copied-label") ?? "";
        }
        clearTimeout(copiedTimers.get(button));
        copiedTimers.set(
          button,
          setTimeout(() => {
            button.removeAttribute("data-tori-ui-copied");
            if (status !== null) status.textContent = "";
          }, 2000),
        );
      },
      () => {},
    );
  });

  // ------------------------------------------------------------ App shell

  // app_shell(): the shell element outlives a live navigation, and so would a
  // sidebar opened over the content. Its own close command shuts it.
  window.addEventListener("phx:navigate", () => {
    const open = document.querySelectorAll(".tori-ui-app-shell--sidebar-open");
    for (const shell of open) {
      const close = shell.getAttribute("phx-window-keydown");
      if (close !== null) globalThis.liveSocket?.execJS(shell, close);
    }
  });

  // ---------------------------------------------------------------- Toast

  // toast(): presses its own dismiss button after the duration, so the page
  // or the browser closes it the same way a visitor would. The countdown
  // pauses while the visitor points at the toast or focuses inside it.
  hooks.ToriUiToast = {
    mounted() {
      let remaining = Number(this.el.dataset.toriUiDuration);
      if (!(remaining > 0)) return;
      let started = 0;
      let timer = null;
      let hovered = false;
      let focused = this.el.contains(document.activeElement);
      const close = () => {
        this.el.querySelector(".tori-ui-toast__dismiss")?.click();
      };
      const resume = () => {
        if (timer !== null || hovered || focused) return;
        started = Date.now();
        timer = setTimeout(close, remaining);
      };
      const pause = () => {
        if (timer === null) return;
        clearTimeout(timer);
        timer = null;
        remaining = Math.max(remaining - (Date.now() - started), 1000);
      };
      this.el.addEventListener("pointerenter", () => {
        hovered = true;
        pause();
      });
      this.el.addEventListener("pointerleave", () => {
        hovered = false;
        resume();
      });
      this.el.addEventListener("focusin", () => {
        focused = true;
        pause();
      });
      this.el.addEventListener("focusout", (event) => {
        focused = event.relatedTarget instanceof Node &&
          this.el.contains(event.relatedTarget);
        resume();
      });
      this.stop = () => clearTimeout(timer);
      resume();
    },
    destroyed() {
      this.stop?.();
    },
  };

  // ----------------------------------------------------------------- Tabs

  // tabs(): arrow keys, Home, and End move between the tabs and select the
  // one they land on, as a click does.
  hooks.ToriUiTabs = {
    mounted() {
      this.el.addEventListener("keydown", (event) => {
        const tabs = [...this.el.querySelectorAll('[role="tab"]')];
        const index = tabs.indexOf(document.activeElement);
        if (index === -1) return;
        const last = tabs.length - 1;
        const moves = {
          ArrowRight: index === last ? 0 : index + 1,
          ArrowLeft: index === 0 ? last : index - 1,
          Home: 0,
          End: last,
        };
        const next = moves[event.key];
        if (next === undefined) return;
        event.preventDefault();
        tabs[next].focus();
        tabs[next].click();
      });
    },
  };

  // -------------------------------------------------------------- Tooltip

  // tooltip(): Escape hides an open bubble until the pointer or the focus
  // leaves its content.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = document.querySelectorAll(
      ".tori-ui-tooltip:hover, .tori-ui-tooltip:focus-within",
    );
    for (const tip of open) {
      const restore = () => {
        tip.removeAttribute("data-tori-ui-dismissed");
        tip.removeEventListener("pointerleave", restore);
        tip.removeEventListener("focusout", restore);
      };
      tip.setAttribute("data-tori-ui-dismissed", "");
      tip.addEventListener("pointerleave", restore);
      tip.addEventListener("focusout", restore);
    }
  });

  // ------------------------------------------------------------- Chat log

  // chat_log(): follows new content while the visitor is at the bottom, and
  // lets go as soon as they scroll up to read.
  hooks.ToriUiChatLog = {
    mounted() {
      const log = this.el;
      // Only the visitor's scrolling changes this. A patch that makes the
      // content taller does not, or the log would let go by itself.
      let pinned = true;
      const toBottom = () => {
        log.scrollTop = log.scrollHeight;
      };
      const mark = () => {
        log.toggleAttribute("data-tori-ui-unpinned", !pinned);
      };
      this.follow = () => {
        if (pinned) toBottom();
        mark();
      };
      log.addEventListener(
        "scroll",
        () => {
          pinned = log.scrollHeight - log.scrollTop - log.clientHeight < 48;
          mark();
        },
        {passive: true},
      );
      log.querySelector(".tori-ui-chat-log__jump")?.addEventListener("click", () => {
        pinned = true;
        this.follow();
        log.focus();
      });
      // New messages and growing ones change the tree; late images and
      // wrapping change only the size.
      this.mutations = new MutationObserver(this.follow);
      this.mutations.observe(log, {
        childList: true,
        subtree: true,
        characterData: true,
      });
      this.sizes = new ResizeObserver(this.follow);
      const messages = log.querySelector(".tori-ui-chat-log__messages");
      if (messages !== null) this.sizes.observe(messages);
      this.follow();
    },
    updated() {
      this.follow();
    },
    destroyed() {
      this.mutations.disconnect();
      this.sizes.disconnect();
    },
  };

  // ------------------------------------------------------------- Composer

  // composer(): Enter sends, Shift+Enter breaks the line, and the field
  // grows with its text. An empty or busy form does not submit.
  hooks.ToriUiComposer = {
    mounted() {
      const form = this.el;
      const field = form.querySelector(".tori-ui-composer__input");
      if (field === null) return;
      const blocked = () =>
        form.dataset.toriUiBusy === "true" || field.value.trim() === "";
      this.resize = () => {
        const style = getComputedStyle(field);
        const line = parseFloat(style.lineHeight) || 24;
        const frame =
          parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
        const rows = Number(field.dataset.toriUiMaxRows) || 8;
        field.style.height = "auto";
        const height = Math.min(field.scrollHeight, line * rows + frame);
        field.style.height = `${height}px`;
      };
      field.addEventListener("input", this.resize);
      field.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        event.preventDefault();
        if (!blocked()) form.requestSubmit();
      });
      form.addEventListener("submit", (event) => {
        if (blocked()) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
        // The LiveView client reads the form during this same event, so the
        // field is emptied right after it.
        setTimeout(() => {
          field.value = "";
          this.resize();
          field.focus();
        });
      });
      this.resize();
    },
    updated() {
      this.resize?.();
    },
  };

  // --------------------------------------------------------------- Dialog

  // modal(), drawer(), confirm_dialog(): a native modal dialog. The browser
  // holds the focus inside, makes the rest of the page inert, and returns the
  // focus to where it was when the dialog closes.
  hooks.ToriUiDialog = {
    mounted() {
      const dialog = this.el;
      const dismissible = () => dialog.dataset.toriUiDismissible !== "false";
      // Closing by any route presses the dialog's own dismiss control, so the
      // browser or the page closes it the way that control says.
      const dismiss = () => {
        dialog.querySelector("[data-tori-ui-dismiss]")?.click();
      };
      dialog.addEventListener("tori-ui:open", (event) => {
        if (event.target !== dialog) return;
        if (!dialog.open) dialog.showModal();
      });
      dialog.addEventListener("tori-ui:close", (event) => {
        if (event.target !== dialog) return;
        if (dialog.open) dialog.close();
      });
      // Escape.
      dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        if (dismissible()) dismiss();
      });
      dialog.addEventListener("click", (event) => {
        if (!(event.target instanceof Element) ||
          event.target.closest("dialog") !== dialog) return;
        // A click on the dialog element itself is a click on its backdrop.
        if (event.target === dialog) {
          if (dismissible()) dismiss();
          return;
        }
        // A dialog the browser owns closes once its action is confirmed; the
        // LiveView client still sees this click first.
        const confirmed =
          event.target instanceof Element &&
          event.target.closest("[data-tori-ui-confirm-action]") !== null;
        if (confirmed && dialog.dataset.toriUiOpen === undefined) {
          setTimeout(() => dialog.close());
        }
      });
      // With data-tori-ui-open the page owns the state and this follows it.
      this.sync = () => {
        const wanted = dialog.dataset.toriUiOpen;
        if (wanted === "true" && !dialog.open) dialog.showModal();
        if (wanted === "false" && dialog.open) dialog.close();
      };
      this.sync();
    },
    updated() {
      this.sync();
    },
    destroyed() {
      if (this.el.open) this.el.close();
    },
  };

  // ---------------------------------------------------------------- Popup

  // dropdown(), popover(): JS commands open and close the panel; this adds
  // what they cannot: focus on opening, arrow keys in a menu, Escape, and
  // closing when a choice is made or the focus leaves.
  hooks.ToriUiPopup = {
    mounted() {
      const root = this.el;
      const trigger = root.querySelector("[aria-expanded]");
      const panel = root.querySelector(".tori-ui-popup__panel");
      if (trigger === null || panel === null) return;
      const isOpen = () => root.classList.contains("tori-ui-popup--open");
      const close = () => {
        if (!isOpen()) return;
        this.liveSocket.execJS(root, root.getAttribute("phx-click-away"));
      };
      const items = () => [
        ...panel.querySelectorAll('[role="menuitem"]:not(:disabled)'),
      ];
      // The LiveView client opens the panel on a later animation frame, so
      // the focus moves when the class arrives, not when the button is hit.
      let wasOpen = isOpen();
      this.opened = new MutationObserver(() => {
        const open = isOpen();
        if (open && !wasOpen) (items()[0] ?? panel).focus();
        wasOpen = open;
      });
      this.opened.observe(root, {attributes: true, attributeFilter: ["class"]});
      root.addEventListener("keydown", (event) => {
        if (!isOpen()) return;
        if (event.key === "Escape") {
          event.stopPropagation();
          close();
          trigger.focus();
          return;
        }
        const list = items();
        if (list.length === 0) return;
        const index = list.indexOf(document.activeElement);
        const last = list.length - 1;
        const moves = {
          ArrowDown: index >= last ? 0 : index + 1,
          ArrowUp: index <= 0 ? last : index - 1,
          Home: 0,
          End: last,
        };
        const next = moves[event.key];
        if (next === undefined) return;
        event.preventDefault();
        list[next].focus();
      });
      panel.addEventListener("click", (event) => {
        const chosen =
          event.target instanceof Element &&
          event.target.closest('[role="menuitem"]') !== null;
        if (!chosen) return;
        // After the LiveView client has handled the choice.
        setTimeout(() => {
          close();
          trigger.focus();
        });
      });
      root.addEventListener("focusout", (event) => {
        if (event.relatedTarget instanceof Node && !root.contains(event.relatedTarget)) {
          close();
        }
      });
    },
    destroyed() {
      this.opened?.disconnect();
    },
  };

  // -------------------------------------------------------- Registration

  // The LiveView client reads globalThis.ToriLiveHooks from a deferred script.
  // An application may replace that object from an inline script in the body,
  // so the hooks are registered again once the document is parsed, which
  // browsers do before they run deferred scripts.
  const register = () => {
    Object.assign((globalThis.ToriLiveHooks ??= {}), hooks);
  };
  register();
  if (document.readyState === "loading") {
    document.addEventListener("readystatechange", register, {once: true});
  }
})();
