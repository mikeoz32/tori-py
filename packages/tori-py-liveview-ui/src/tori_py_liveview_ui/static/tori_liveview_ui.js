/* Tori UI document initialization. Component behavior lives in Lit elements. */
;(() => {
  try {
    const mode = localStorage.getItem("tori-ui-mode");
    if (["auto", "light", "dark"].includes(mode)) document.documentElement.dataset.toriUiMode = mode;
  } catch { /* Storage is optional. */ }

  const previous = globalThis.ToriLiveReady;
  const ready = Promise.withResolvers();
  const defined = () => {
    window.removeEventListener("error", failed, true);
    ready.resolve();
  };
  const failed = (event) => {
    if (!(event.target instanceof HTMLScriptElement) ||
      !event.target.hasAttribute("data-tori-ui-components")) return;
    window.removeEventListener("tori-ui:defined", defined);
    window.removeEventListener("error", failed, true);
    ready.reject(new Error("Tori UI components could not be loaded"));
  };
  window.addEventListener("tori-ui:defined", defined, {once: true});
  window.addEventListener("error", failed, true);
  globalThis.ToriLiveReady = Promise.all([previous, ready.promise]);
  // Report a failed module load even when this document has no LiveView root.
  globalThis.ToriLiveReady.catch((error) => console.error(error));
})();
