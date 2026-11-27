import {ReactiveElement} from "../vendor/lit-reactive-element-2.1.2/reactive-element.js";

// LiveView owns the light DOM. Lit observes attributes and schedules behavior;
// this base deliberately has no renderer, template, shadow root, or DOM diff.
export class ToriElement extends ReactiveElement {
  createRenderRoot() { return this; }

  connectedCallback() {
    super.connectedCallback();
    // A patch may move the same element without ending its lifetime.
    if (this.connection) return;
    this.connection = new AbortController();
    this.observers = new Set();
    this.timers = new Set();
    this.connect();
    if (this.id) {
      const attach = () => globalThis.LiveView.createHook(this, {
        mounted: () => this.requestUpdate(),
        updated: () => this.requestUpdate(),
      });
      if (globalThis.LiveView) attach();
      else this.listen(window, "tori-live:ready", attach, {once: true});
    }
    this.requestUpdate();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    queueMicrotask(() => {
      if (this.isConnected || !this.connection) return;
      this.connection.abort();
      for (const observer of this.observers) observer.disconnect();
      for (const timer of this.timers) clearTimeout(timer);
      this.disconnect();
      this.connection = null;
    });
  }

  connect() {}
  disconnect() {}

  listen(target, name, callback, options = {}) {
    target.addEventListener(name, callback, {...options, signal: this.connection.signal});
  }

  observe(target, options, callback = () => this.requestUpdate()) {
    const observer = new MutationObserver(callback);
    observer.observe(target, options);
    this.observers.add(observer);
    return observer;
  }

  later(callback, delay = 0) {
    const connection = this.connection;
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      if (!connection.signal.aborted && this.isConnected) callback();
    }, delay);
    this.timers.add(timer);
    return timer;
  }

  clearTimer(timer) {
    clearTimeout(timer);
    this.timers.delete(timer);
  }
}
