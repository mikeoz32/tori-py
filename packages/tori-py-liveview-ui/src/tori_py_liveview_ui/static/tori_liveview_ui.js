/* Tori UI: Phoenix LiveView hooks and browser behavior for the components. */
;(() => {
  "use strict";

  const THEME_KEY = "tori-ui-theme";
  const THEMES = ["auto", "light", "dark"];
  const root = document.documentElement;

  // ---------------------------------------------------------------- Theme

  // A theme the visitor chose earlier wins over the document's default. It is
  // applied here, before the body is parsed, so the page never paints twice.
  const storedTheme = () => {
    try {
      const theme = localStorage.getItem(THEME_KEY);
      return THEMES.includes(theme) ? theme : null;
    } catch {
      return null;
    }
  };
  const applyTheme = (theme) => {
    root.dataset.toriUiTheme = theme;
  };
  const initialTheme = storedTheme();
  if (initialTheme !== null) applyTheme(initialTheme);

  const hooks = {};

  // theme_toggle(): marks the current theme and stores the visitor's choice.
  hooks.ToriUiTheme = {
    mounted() {
      this.sync = () => {
        const current = root.dataset.toriUiTheme ?? "auto";
        for (const option of this.el.querySelectorAll("[data-tori-ui-theme-value]")) {
          const pressed = option.dataset.toriUiThemeValue === current;
          option.setAttribute("aria-pressed", String(pressed));
        }
      };
      this.el.addEventListener("click", (event) => {
        const option =
          event.target instanceof Element
            ? event.target.closest("[data-tori-ui-theme-value]")
            : null;
        if (option === null || !this.el.contains(option)) return;
        const theme = option.dataset.toriUiThemeValue;
        if (!THEMES.includes(theme)) return;
        applyTheme(theme);
        try {
          localStorage.setItem(THEME_KEY, theme);
        } catch {
          // Storage can be unavailable; the choice then lasts for this page.
        }
        // Every toggle on the page follows the one that was used.
        window.dispatchEvent(new CustomEvent("tori-ui:theme"));
      });
      window.addEventListener("tori-ui:theme", this.sync);
      this.sync();
    },
    updated() {
      this.sync();
    },
    destroyed() {
      window.removeEventListener("tori-ui:theme", this.sync);
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
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    try {
      document.execCommand("copy");
    } finally {
      area.remove();
    }
  };

  const copySource = (target) => {
    if (target.matches("[data-tori-ui-copy-source]")) return target;
    return target.querySelector("[data-tori-ui-copy-source]") ?? target;
  };

  // copy_button(): a JS dispatch names the element; this listener copies its
  // text and reports back on the button that dispatched.
  window.addEventListener("tori-ui:copy", (event) => {
    if (!(event.target instanceof Element)) return;
    const source = copySource(event.target);
    const text =
      typeof source.value === "string" ? source.value : (source.innerText ?? "");
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
      const close = () => {
        this.el.querySelector(".tori-ui-toast__dismiss")?.click();
      };
      const resume = () => {
        if (timer !== null) return;
        started = Date.now();
        timer = setTimeout(close, remaining);
      };
      const pause = () => {
        if (timer === null) return;
        clearTimeout(timer);
        timer = null;
        remaining = Math.max(remaining - (Date.now() - started), 1000);
      };
      this.el.addEventListener("pointerenter", pause);
      this.el.addEventListener("pointerleave", resume);
      this.el.addEventListener("focusin", pause);
      this.el.addEventListener("focusout", resume);
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
