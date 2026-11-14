/* Tori UI: Phoenix LiveView hooks and browser behavior for the components. */
;(() => {
  "use strict";

  const THEME_KEY = "tori-ui-theme";
  const THEMES = ["auto", "light", "dark"];
  const root = document.documentElement;

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
  const theme = storedTheme();
  if (theme !== null) root.dataset.toriUiTheme = theme;

  const hooks = {};

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
