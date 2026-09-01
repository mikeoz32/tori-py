const DEFAULT_RECONNECT_DELAYS = [100, 500, 1000, 2000, 5000];
const HEARTBEAT_INTERVAL = 30000;
const PROTOCOL_VERSION = 2;

export class OpalLiveView {
  constructor(root, {hooks = {}} = {}) {
    this.root = root;
    this.token = root.dataset.opalToken;
    this.socketPath = root.dataset.opalSocket;
    this.protocol = PROTOCOL_VERSION;
    this.version = 0;
    this.rendered = null;
    this.socket = null;
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;
    this.connectionGeneration = 0;
    this.heartbeatRef = 0;
    this.lastHeartbeatAck = 0;
    this.nextEventRef = 0;
    this.eventQueue = [];
    this.inFlightEvent = null;
    this.stopped = false;
    this.hookDefinitions = hooks && typeof hooks === "object" ? hooks : {};
    this.hooks = new Map();
    this.invalidHookElements = new WeakSet();
    this.disconnectedHooks = null;
    this.nextHookEventRef = 0;
    this.pendingUpdatedHooks = [];
    this.currentResource = this.locationResource();
    this.navigationMarker = root.id || "opal-live-root";
    this.popStateHandler = () => this.onPopState();
    this.markHistoryEntry();
    this.bindEvents();
  }

  connect() {
    if (this.stopped) return;
    if (this.socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(this.socket.readyState)) return;
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(this.socketPath, `${scheme}//${window.location.host}`);
    const generation = ++this.connectionGeneration;
    const socket = new WebSocket(url);
    this.socket = socket;
    this.root.dataset.opalStatus = "connecting";

    socket.addEventListener("open", () => {
      if (!this.currentConnection(socket, generation)) return;
      this.lastHeartbeatAck = Date.now();
      if (!this.send({type: "join", protocol: this.protocol, token: this.token})) {
        socket.close(1001, "join send failed");
        return;
      }
      this.startHeartbeat();
    });

    socket.addEventListener("message", event => {
      if (this.currentConnection(socket, generation)) this.onMessage(event);
    });
    socket.addEventListener("close", event => {
      if (!this.currentConnection(socket, generation)) return;
      this.stopHeartbeat();
      this.root.dataset.opalStatus = "disconnected";
      this.disconnectHooks();
      this.failPendingEvents(event.code);
      if (!this.stopped && this.locationResource() !== this.currentResource) {
        window.location.reload();
        return;
      }
      if (!this.stopped && this.shouldReconnect(event.code)) this.scheduleReconnect();
    });
  }

  disconnect() {
    this.stopped = true;
    this.connectionGeneration += 1;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.stopHeartbeat();
    this.disconnectHooks();
    window.removeEventListener("popstate", this.popStateHandler);
    if (this.socket) this.socket.close(1000, "page unload");
  }

  bindEvents() {
    window.addEventListener("popstate", this.popStateHandler);
    this.root.addEventListener("click", event => {
      const link = event.target.closest("a[data-opal-patch], a[data-opal-navigate]");
      if (link && this.root.contains(link) && this.navigationClick(event, link)) return;

      const target = event.target.closest("[data-opal-click]");
      if (!target || !this.root.contains(target)) return;
      event.preventDefault();
      const componentTarget = this.componentTarget(target);
      if (componentTarget !== undefined) {
        this.pushEvent(target.dataset.opalClick, this.eventValue(target), componentTarget);
      }
    });

    this.root.addEventListener("submit", event => {
      const form = event.target.closest("form[data-opal-submit]");
      if (!form) return;
      event.preventDefault();
      const value = this.formValue(form, event.submitter);
      const componentTarget = this.componentTarget(form);
      if (value && componentTarget !== undefined) {
        this.pushEvent(form.dataset.opalSubmit, value, componentTarget);
      }
    });

    const pushChange = target => {
      const owner = target.closest("[data-opal-change]") || target.form?.closest("[data-opal-change]");
      if (!owner || !this.root.contains(owner)) return;
      const value = owner instanceof HTMLFormElement ? this.formValue(owner) : this.eventValue(owner);
      const componentTarget = this.componentTarget(owner);
      if (value && componentTarget !== undefined) {
        this.pushEvent(owner.dataset.opalChange, value, componentTarget);
      }
    };
    this.root.addEventListener("change", event => {
      const target = event.target;
      const owner = target.closest("[data-opal-change]") || target.form?.closest("[data-opal-change]");
      if (!owner || Object.prototype.hasOwnProperty.call(owner.dataset, "opalDebounce")) return;
      pushChange(target);
    });
    this.root.addEventListener("input", event => {
      const target = event.target;
      const owner = target.closest("[data-opal-change]") || target.form?.closest("[data-opal-change]");
      if (!owner || !Object.prototype.hasOwnProperty.call(owner.dataset, "opalDebounce")) return;
      window.clearTimeout(owner.__opalDebounceTimer);
      owner.__opalDebounceTimer = window.setTimeout(
        () => pushChange(target),
        Number(owner.dataset.opalDebounce) || 0,
      );
    });
  }

  pushEvent(event, value = {}, target = null) {
    const pending = this.enqueueEvent(event, value, target);
    return pending !== null;
  }

  enqueueEvent(event, value, target, completion = {}) {
    if (typeof event !== "string" || event.length === 0) return null;
    if (this.root.dataset.opalStatus !== "connected") return null;
    let normalizedValue;
    try {
      normalizedValue = JSON.parse(JSON.stringify(value));
    } catch (_) {
      return null;
    }
    const pending = {
      type: "event",
      event,
      value: normalizedValue,
      target,
      ref: ++this.nextEventRef,
      ...completion,
    };
    this.eventQueue.push(pending);
    this.flushEvents();
    return pending;
  }

  pushHookEvent(hook, event, value = {}, callback = null, target = null) {
    if (callback !== null && typeof callback !== "function") {
      throw new TypeError("LiveView hook reply callback must be a function");
    }

    if (callback) {
      const pending = this.enqueueEvent(event, value, target, {hook, callback});
      if (!pending) this.reportHookError(hook, "pushEvent", new Error("LiveView is not connected"));
      return pending?.ref ?? null;
    }

    return new Promise((resolve, reject) => {
      const pending = this.enqueueEvent(event, value, target, {hook, resolve, reject});
      if (!pending) reject(new Error("LiveView is not connected or the event payload is invalid"));
    });
  }

  pushHookEventTo(hook, selectorOrTarget, event, value = {}, callback = null) {
    let targets;
    if (typeof selectorOrTarget === "string") {
      try {
        targets = Array.from(this.root.querySelectorAll(selectorOrTarget));
      } catch (_) {
        targets = [];
      }
    } else if (selectorOrTarget instanceof Element && this.root.contains(selectorOrTarget)) {
      targets = [selectorOrTarget];
    } else {
      targets = [];
    }

    if (targets.length === 0) {
      const error = new Error("LiveView hook target was not found");
      if (callback) {
        this.reportHookError(hook, "pushEventTo", error);
        return [];
      }
      return Promise.reject(error);
    }

    const operations = targets.map(targetElement => {
      const target = this.componentTarget(targetElement);
      if (target === undefined) {
        if (callback) return null;
        return Promise.reject(new Error("LiveView hook target is invalid"));
      }
      return this.pushHookEvent(hook, event, value, callback, target);
    });
    return callback ? operations.filter(value => value !== null) : Promise.allSettled(operations);
  }

  pushPatch(to, {history = "push"} = {}) {
    if (this.root.dataset.opalStatus !== "connected") return false;
    if (!["push", "replace", "none"].includes(history)) return false;
    const url = this.localURL(to);
    if (!url) return false;
    this.eventQueue.push({
      type: "patch",
      to: this.resourceFor(url),
      history,
      ref: ++this.nextEventRef,
    });
    this.flushEvents();
    return true;
  }

  flushEvents() {
    if (this.inFlightEvent || this.eventQueue.length === 0) return;
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

    const pending = this.eventQueue.shift();
    this.inFlightEvent = pending;
    const message = pending.type === "event"
      ? {
          type: "event",
          event: pending.event,
          value: pending.value,
          target: pending.target,
          version: this.version,
          ref: pending.ref,
        }
      : {
          type: "patch",
          to: pending.to,
          history: pending.history,
          version: this.version,
          ref: pending.ref,
        };
    if (!this.send(message)) {
      this.inFlightEvent = null;
      this.eventQueue.unshift(pending);
    }
  }

  onMessage(event) {
    if (typeof event.data !== "string") {
      this.socket.close(1003, "text messages required");
      return;
    }
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_) {
      this.socket.close(1002, "invalid server message");
      return;
    }

    if (message.type === "render") {
      if (message.protocol !== this.protocol) {
        this.socket.close(1002, "unsupported protocol");
        return;
      }
      try {
        this.applyRender(message);
      } catch (_) {
        this.socket.close(1002, "invalid render");
        return;
      }
      this.reconnectAttempt = 0;
      if (this.inFlightEvent && message.ref === this.inFlightEvent.ref) {
        const pending = this.inFlightEvent;
        this.inFlightEvent = null;
        if (message.status === "stale") {
          this.eventQueue.unshift(pending);
        } else {
          this.resolvePendingEvent(pending, message);
        }
      }
      this.flushEvents();
    } else if (message.type === "heartbeat") {
      if (message.ref === this.heartbeatRef) this.lastHeartbeatAck = Date.now();
    } else if (message.type === "error") {
      if (this.inFlightEvent && message.ref === this.inFlightEvent.ref) {
        const pending = this.inFlightEvent;
        this.inFlightEvent = null;
        this.rejectPendingEvent(pending, new Error(message.reason || "LiveView event failed"));
        this.flushEvents();
        if (pending.type === "patch" && pending.history === "none") {
          window.location.reload();
          return;
        }
      }
      this.root.dispatchEvent(new CustomEvent("opal:error", {detail: message}));
    }
  }

  applyRender(message) {
    if (!Number.isSafeInteger(message.version) || message.version < 0) {
      throw new Error("invalid render version");
    }

    this.pendingUpdatedHooks = [];
    this.patchRoot(this.renderHTML(message));
    this.applyStreams(message.streams);
    this.version = message.version;
    this.root.dataset.opalStatus = "connected";
    if (Object.prototype.hasOwnProperty.call(message, "title")) document.title = message.title;
    this.reconcileHooks();
    this.flushUpdatedHooks();
    this.reconnectHooks();
    const navigating = this.applyNavigation(message);
    if (!navigating) this.applyPushedEvents(message.events);
    this.root.dispatchEvent(new CustomEvent("opal:render", {detail: message}));
  }

  applyNavigation(message) {
    const navigation = message.navigation;
    if (navigation === undefined) return false;
    if (
      !navigation ||
      typeof navigation !== "object" ||
      !["patch", "navigate"].includes(navigation.kind) ||
      !["push", "replace", "none"].includes(navigation.history) ||
      typeof navigation.to !== "string"
    ) {
      throw new Error("invalid navigation");
    }

    const url = this.localURL(navigation.to);
    if (!url) throw new Error("invalid navigation target");
    if (navigation.kind === "navigate") {
      if (navigation.history === "none") throw new Error("invalid navigation history");
      this.root.dispatchEvent(new CustomEvent("opal:navigate", {detail: navigation}));
      this.navigateDocument(url, navigation.history === "replace");
      return true;
    }

    if (typeof message.token !== "string" || message.token.length === 0) {
      throw new Error("missing navigation token");
    }
    const resource = this.resourceFor(url);
    if (navigation.history === "push") {
      window.history.pushState(this.navigationState(), "", url);
    } else if (navigation.history === "replace") {
      window.history.replaceState(this.navigationState(), "", url);
    } else if (this.locationResource() !== resource) {
      throw new Error("navigation history mismatch");
    } else {
      this.markHistoryEntry();
    }

    this.currentResource = resource;
    this.token = message.token;
    this.root.dataset.opalToken = message.token;
    this.root.dispatchEvent(new CustomEvent("opal:navigate", {detail: navigation}));
    return false;
  }

  renderHTML(message) {
    if (message.rendered) {
      const {fingerprint, statics, dynamics} = message.rendered;
      if (
        typeof fingerprint !== "string" ||
        !Array.isArray(statics) ||
        !Array.isArray(dynamics) ||
        statics.length !== dynamics.length + 1 ||
        !statics.every(value => typeof value === "string") ||
        !dynamics.every(value => typeof value === "string")
      ) {
        throw new Error("invalid rendered snapshot");
      }
      this.rendered = {fingerprint, statics: [...statics], dynamics: [...dynamics]};
    } else if (message.diff) {
      if (
        !this.rendered ||
        typeof message.fingerprint !== "string" ||
        message.fingerprint !== this.rendered.fingerprint ||
        typeof message.diff !== "object" ||
        Array.isArray(message.diff)
      ) {
        throw new Error("invalid render diff");
      }

      const dynamics = [...this.rendered.dynamics];
      for (const [position, value] of Object.entries(message.diff)) {
        if (!/^(0|[1-9]\d*)$/.test(position) || typeof value !== "string") {
          throw new Error("invalid dynamic position");
        }
        const index = Number(position);
        if (index >= dynamics.length) throw new Error("dynamic position out of bounds");
        dynamics[index] = value;
      }
      this.rendered = {...this.rendered, dynamics};
    } else {
      throw new Error("missing rendered state");
    }

    return String.raw({raw: this.rendered.statics}, ...this.rendered.dynamics);
  }

  patchRoot(html) {
    const template = document.createElement("template");
    template.innerHTML = html;
    this.morphChildren(this.root, template.content);
  }

  morphChildren(currentParent, nextParent) {
    const keyed = new Map();
    for (const child of currentParent.childNodes) {
      const key = this.nodeKey(child);
      if (!key) continue;
      keyed.set(key, keyed.has(key) ? null : child);
    }

    const nextKeys = new Set();
    let cursor = currentParent.firstChild;
    for (const nextChild of Array.from(nextParent.childNodes)) {
      const key = this.nodeKey(nextChild);
      if (key && nextKeys.has(key)) throw new Error("duplicate DOM key");
      if (key) nextKeys.add(key);

      let current = key ? keyed.get(key) : null;
      if (current && !this.sameNodeKind(current, nextChild)) current = null;
      if (!current && !key && cursor && !this.nodeKey(cursor) && this.sameNodeKind(cursor, nextChild)) {
        current = cursor;
      }

      if (current) {
        if (current !== cursor) currentParent.insertBefore(current, cursor);
        this.morphNode(current, nextChild);
      } else {
        current = nextChild.cloneNode(true);
        currentParent.insertBefore(current, cursor);
      }
      cursor = current.nextSibling;
    }

    while (cursor) {
      const next = cursor.nextSibling;
      currentParent.removeChild(cursor);
      cursor = next;
    }
  }

  morphNode(current, next) {
    if (current.nodeType !== Node.ELEMENT_NODE) {
      if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
      return;
    }

    const hook = this.hooks.get(current);
    const hookUpdating = Boolean(
      hook &&
      hook.name === next.getAttribute("data-opal-hook") &&
      !current.isEqualNode(next)
    );
    if (hookUpdating) this.invokeHook(hook, "beforeUpdate", next);

    const focused = document.activeElement === current;
    const controlState = focused ? this.controlState(current) : null;
    const streamOwned = current.hasAttribute("data-opal-stream") && next.hasAttribute("data-opal-stream");
    this.morphAttributes(current, next);
    if (!streamOwned) this.morphChildren(current, next);
    this.syncControl(current, next, controlState);
    if (hookUpdating) this.pendingUpdatedHooks.push({element: current, hook});
  }

  applyStreams(operations) {
    if (operations === undefined) return;
    if (!Array.isArray(operations)) throw new Error("invalid stream operations");

    const prepared = operations.map(operation => this.prepareStreamOperation(operation));
    for (const operation of prepared) {
      if (operation.op === "reset") {
        operation.container.replaceChildren();
      } else if (operation.op === "delete") {
        this.streamChild(operation.container, operation.id)?.remove();
      } else {
        this.applyStreamInsert(operation);
      }
    }
  }

  prepareStreamOperation(operation) {
    if (!operation || typeof operation !== "object" || Array.isArray(operation)) {
      throw new Error("invalid stream operation");
    }
    if (typeof operation.container !== "string" || operation.container.length === 0) {
      throw new Error("invalid stream container");
    }

    const container = document.getElementById(operation.container);
    if (!container || !this.root.contains(container) || !container.hasAttribute("data-opal-stream")) {
      throw new Error("missing stream container");
    }

    if (operation.op === "reset") return {op: "reset", container};
    if (typeof operation.id !== "string" || operation.id.length === 0) {
      throw new Error("invalid stream item id");
    }
    if (operation.op === "delete") return {op: "delete", container, id: operation.id};
    if (operation.op !== "insert") throw new Error("unsupported stream operation");
    if (
      typeof operation.html !== "string" ||
      !Number.isSafeInteger(operation.at) ||
      operation.at < -1 ||
      (
        operation.limit !== undefined &&
        (!Number.isSafeInteger(operation.limit) || operation.limit === 0)
      )
    ) {
      throw new Error("invalid stream insertion");
    }

    const template = document.createElement("template");
    template.innerHTML = operation.html;
    if (template.content.childElementCount !== 1) throw new Error("stream item must have one root element");
    for (const node of template.content.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.nodeValue.trim() !== "") {
        throw new Error("stream item must have one root element");
      }
    }
    const element = template.content.firstElementChild;
    if (element.id !== operation.id) throw new Error("stream item id mismatch");

    return {
      op: "insert",
      container,
      id: operation.id,
      element,
      at: operation.at,
      limit: operation.limit,
    };
  }

  applyStreamInsert(operation) {
    const existing = this.streamChild(operation.container, operation.id);
    if (existing) {
      if (this.sameNodeKind(existing, operation.element)) {
        this.morphNode(existing, operation.element);
      } else {
        existing.replaceWith(operation.element);
      }
    } else {
      const reference = operation.at === -1 ? null : operation.container.children.item(operation.at);
      operation.container.insertBefore(operation.element, reference);
    }

    if (operation.limit === undefined) return;
    const keep = Math.abs(operation.limit);
    while (operation.container.children.length > keep) {
      const child = operation.limit > 0
        ? operation.container.lastElementChild
        : operation.container.firstElementChild;
      child.remove();
    }
  }

  streamChild(container, id) {
    return Array.from(container.children).find(child => child.id === id) || null;
  }

  reconcileHooks() {
    const elements = Array.from(this.root.querySelectorAll("[data-opal-hook]"));
    const present = new Set(elements);

    for (const [element, hook] of Array.from(this.hooks.entries())) {
      if (!present.has(element) || element.dataset.opalHook !== hook.name) {
        this.destroyHook(element, hook);
      }
    }

    const idCounts = new Map();
    for (const element of elements) {
      if (element.id) idCounts.set(element.id, (idCounts.get(element.id) || 0) + 1);
    }

    for (const element of elements) {
      const name = element.dataset.opalHook;
      const definition = Object.prototype.hasOwnProperty.call(this.hookDefinitions, name)
        ? this.hookDefinitions[name]
        : null;
      let error = null;
      if (!element.id) {
        error = new Error("LiveView hook elements require a unique id");
      } else if (idCounts.get(element.id) !== 1) {
        error = new Error("LiveView hook element ids must be unique inside the live root");
      } else if (!definition || !["object", "function"].includes(typeof definition)) {
        error = new Error(`Unknown LiveView hook: ${name}`);
      }

      if (error) {
        if (this.hooks.has(element)) this.destroyHook(element, this.hooks.get(element));
        if (!this.invalidHookElements.has(element)) {
          this.invalidHookElements.add(element);
          this.reportHookError({name, el: element}, "mounted", error);
        }
        continue;
      }

      if (this.hooks.has(element)) continue;

      this.invalidHookElements.delete(element);
      let hook;
      try {
        hook = typeof definition === "function" ? new definition() : Object.create(definition);
        const eventHandlers = new Map();
        Object.defineProperties(hook, {
          name: {value: name},
          el: {value: element, writable: true},
          liveView: {value: this},
          liveSocket: {value: this},
          pushEvent: {
            value: (event, payload = {}, callback = null) =>
              this.pushHookEvent(hook, event, payload, callback),
          },
          pushEventTo: {
            value: (target, event, payload = {}, callback = null) =>
              this.pushHookEventTo(hook, target, event, payload, callback),
          },
          handleEvent: {
            value: (event, callback) => this.addHookEventHandler(hook, eventHandlers, event, callback),
          },
          removeHandleEvent: {
            value: ref => eventHandlers.delete(ref),
          },
          __opalEventHandlers: {value: eventHandlers},
        });
      } catch (creationError) {
        this.invalidHookElements.add(element);
        this.reportHookError({name, el: element}, "mounted", creationError);
        continue;
      }

      this.hooks.set(element, hook);
      this.invokeHook(hook, "mounted");
    }
  }

  flushUpdatedHooks() {
    const pending = this.pendingUpdatedHooks;
    this.pendingUpdatedHooks = [];
    for (const {element, hook} of pending) {
      if (this.hooks.get(element) === hook && this.root.contains(element)) {
        this.invokeHook(hook, "updated");
      }
    }
  }

  addHookEventHandler(hook, handlers, event, callback) {
    if (typeof event !== "string" || event.length === 0 || typeof callback !== "function") {
      throw new TypeError("LiveView hook event handlers require an event name and callback");
    }
    const ref = ++this.nextHookEventRef;
    handlers.set(ref, {event, callback});
    return ref;
  }

  applyPushedEvents(events) {
    if (events === undefined) return;
    if (!Array.isArray(events)) throw new Error("invalid pushed events");
    const prepared = events.map(event => {
      if (
        !event ||
        typeof event !== "object" ||
        Array.isArray(event) ||
        typeof event.event !== "string" ||
        event.event.length === 0 ||
        !Object.prototype.hasOwnProperty.call(event, "payload")
      ) {
        throw new Error("invalid pushed event");
      }
      return event;
    });

    for (const event of prepared) {
      window.dispatchEvent(new CustomEvent(`opal:${event.event}`, {detail: event.payload}));
      for (const hook of Array.from(this.hooks.values())) {
        for (const handler of Array.from(hook.__opalEventHandlers.values())) {
          if (handler.event !== event.event) continue;
          try {
            handler.callback.call(hook, event.payload);
          } catch (error) {
            this.reportHookError(hook, `handleEvent:${event.event}`, error);
          }
        }
      }
    }
  }

  invokeHook(hook, callbackName, ...args) {
    const callback = hook[callbackName];
    if (callback === undefined) return;
    if (typeof callback !== "function") {
      this.reportHookError(hook, callbackName, new TypeError("LiveView hook callback must be a function"));
      return;
    }
    try {
      callback.call(hook, ...args);
    } catch (error) {
      this.reportHookError(hook, callbackName, error);
    }
  }

  destroyHook(element, hook) {
    this.invokeHook(hook, "destroyed");
    hook.__opalEventHandlers.clear();
    this.disconnectedHooks?.delete(hook);
    this.hooks.delete(element);
  }

  disconnectHooks() {
    if (this.disconnectedHooks !== null) return;
    this.disconnectedHooks = new Set(this.hooks.values());
    for (const hook of this.disconnectedHooks) this.invokeHook(hook, "disconnected");
  }

  reconnectHooks() {
    if (this.disconnectedHooks === null) return;
    const disconnected = this.disconnectedHooks;
    this.disconnectedHooks = null;
    for (const hook of disconnected) {
      if (this.hooks.get(hook.el) === hook) this.invokeHook(hook, "reconnected");
    }
  }

  reportHookError(hook, callback, error) {
    const detail = {hook: hook.name || "", callback, error};
    this.root.dispatchEvent(new CustomEvent("opal:hook-error", {detail}));
    console.error(`Opal LiveView hook ${detail.hook}.${callback} failed`, error);
  }

  morphAttributes(current, next) {
    for (const attribute of Array.from(current.attributes)) {
      if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name);
    }
    for (const attribute of next.attributes) {
      if (current.getAttribute(attribute.name) !== attribute.value) {
        current.setAttribute(attribute.name, attribute.value);
      }
    }
  }

  controlState(element) {
    const state = {};
    if ("value" in element) state.value = element.value;
    if ("checked" in element) state.checked = element.checked;
    if ("selectionStart" in element) {
      state.selectionStart = element.selectionStart;
      state.selectionEnd = element.selectionEnd;
      state.selectionDirection = element.selectionDirection;
    }
    return state;
  }

  syncControl(current, next, preserved) {
    if (preserved) {
      if (Object.prototype.hasOwnProperty.call(preserved, "value")) current.value = preserved.value;
      if (Object.prototype.hasOwnProperty.call(preserved, "checked")) current.checked = preserved.checked;
      if (
        preserved.selectionStart !== null &&
        preserved.selectionStart !== undefined &&
        "setSelectionRange" in current
      ) {
        current.setSelectionRange(
          preserved.selectionStart,
          preserved.selectionEnd,
          preserved.selectionDirection,
        );
      }
      return;
    }

    if (current instanceof HTMLInputElement) {
      if (current.type !== "file") current.value = next.value;
      current.checked = next.checked;
    } else if (current instanceof HTMLTextAreaElement) {
      current.value = next.value;
    } else if (current instanceof HTMLSelectElement) {
      current.value = next.value;
    } else if (current instanceof HTMLOptionElement) {
      current.selected = next.selected;
    }
  }

  sameNodeKind(current, next) {
    if (current.nodeType !== next.nodeType) return false;
    if (current.nodeType !== Node.ELEMENT_NODE) return true;
    return current.tagName === next.tagName && this.nodeKey(current) === this.nodeKey(next);
  }

  nodeKey(node) {
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    return node.getAttribute("data-opal-key") || node.id || null;
  }

  eventValue(element) {
    const value = {};
    for (const [key, item] of Object.entries(element.dataset)) {
      if (key.startsWith("opalValue")) {
        const name = key.slice("opalValue".length);
        value[name.charAt(0).toLowerCase() + name.slice(1)] = item;
      }
    }
    if ("value" in element && element.name) value[element.name] = element.value;
    return value;
  }

  componentTarget(element) {
    const component = element.closest("[data-opal-target]");
    if (!component || !this.root.contains(component)) return null;

    const rawTarget = component.dataset.opalTarget;
    if (!/^[1-9]\d*$/.test(rawTarget || "")) {
      this.root.dispatchEvent(new CustomEvent("opal:error", {
        detail: {type: "error", reason: "invalid_target"},
      }));
      return undefined;
    }

    const target = Number(rawTarget);
    if (!Number.isSafeInteger(target)) {
      this.root.dispatchEvent(new CustomEvent("opal:error", {
        detail: {type: "error", reason: "invalid_target"},
      }));
      return undefined;
    }
    return target;
  }

  navigationClick(event, link) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      link.hasAttribute("download") ||
      (link.target && link.target !== "_self")
    ) {
      return false;
    }

    const url = this.localURL(link.href);
    if (!url) return false;
    event.preventDefault();
    const replace = link.hasAttribute("data-opal-replace");
    if (link.hasAttribute("data-opal-patch")) {
      if (!this.pushPatch(url.href, {history: replace ? "replace" : "push"})) {
        this.navigateDocument(url, replace);
      }
    } else {
      this.navigateDocument(url, replace);
    }
    return true;
  }

  onPopState() {
    const state = window.history.state;
    if (!state || state.__opalLiveView !== this.navigationMarker) {
      window.location.reload();
      return;
    }

    const resource = this.locationResource();
    if (resource === this.currentResource) return;
    if (this.inFlightEvent || this.eventQueue.length > 0) {
      window.location.reload();
      return;
    }
    if (!this.pushPatch(resource, {history: "none"})) window.location.reload();
  }

  localURL(value) {
    try {
      const url = new URL(value, window.location.href);
      if (
        url.origin !== window.location.origin ||
        url.username ||
        url.password ||
        url.hash
      ) {
        return null;
      }
      return url;
    } catch (_) {
      return null;
    }
  }

  resourceFor(url) {
    return `${url.pathname}${url.search}`;
  }

  locationResource() {
    return `${window.location.pathname}${window.location.search}`;
  }

  navigationState() {
    const current = window.history.state;
    const state = current && typeof current === "object" && !Array.isArray(current)
      ? {...current}
      : {};
    state.__opalLiveView = this.navigationMarker;
    return state;
  }

  markHistoryEntry() {
    window.history.replaceState(this.navigationState(), "", window.location.href);
  }

  navigateDocument(url, replace) {
    if (replace) {
      window.location.replace(url.href);
    } else {
      window.location.assign(url.href);
    }
  }

  formValue(form, submitter = null) {
    const value = {};
    for (const [name, item] of new FormData(form).entries()) {
      if (item instanceof File) {
        if (item.name === "" && item.size === 0) continue;
        this.root.dispatchEvent(new CustomEvent("opal:error", {
          detail: {type: "error", reason: "uploads_unsupported"},
        }));
        return null;
      }
      if (Object.prototype.hasOwnProperty.call(value, name)) {
        value[name] = Array.isArray(value[name]) ? [...value[name], item] : [value[name], item];
      } else {
        value[name] = item;
      }
    }
    if (submitter && submitter.name) value[submitter.name] = submitter.value;
    return value;
  }

  send(message) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    try {
      this.socket.send(JSON.stringify(message));
      return true;
    } catch (_) {
      return false;
    }
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastHeartbeatAck > HEARTBEAT_INTERVAL * 2) {
        if (this.socket) this.socket.close(1001, "heartbeat timeout");
        return;
      }
      if (!this.send({type: "heartbeat", ref: ++this.heartbeatRef}) && this.socket) {
        this.socket.close(1001, "heartbeat send failed");
      }
    }, HEARTBEAT_INTERVAL);
  }

  stopHeartbeat() {
    if (this.heartbeatTimer) window.clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = DEFAULT_RECONNECT_DELAYS[
      Math.min(this.reconnectAttempt, DEFAULT_RECONNECT_DELAYS.length - 1)
    ];
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay + Math.floor(Math.random() * 100));
  }

  currentConnection(socket, generation) {
    return this.socket === socket && this.connectionGeneration === generation;
  }

  shouldReconnect(code) {
    return ![1000, 1002, 1003, 1008, 1009].includes(code);
  }

  resolvePendingEvent(pending, message) {
    if (pending.type !== "event") return;
    const reply = Object.prototype.hasOwnProperty.call(message, "reply") ? message.reply : null;
    if (pending.callback) {
      try {
        pending.callback.call(pending.hook, reply, pending.ref);
      } catch (error) {
        this.reportHookError(pending.hook, "reply", error);
      }
    }
    if (pending.resolve) pending.resolve({reply, ref: pending.ref});
  }

  rejectPendingEvent(pending, error) {
    if (pending.type === "event" && pending.reject) pending.reject(error);
  }

  failPendingEvents(code) {
    const pending = [this.inFlightEvent, ...this.eventQueue].filter(Boolean);
    this.inFlightEvent = null;
    this.eventQueue = [];
    for (const event of pending) {
      this.rejectPendingEvent(event, new Error(`LiveView connection closed (${code})`));
      this.root.dispatchEvent(new CustomEvent("opal:event-error", {
        detail: {event: event.event || event.type, ref: event.ref, code},
      }));
    }
  }

}

export function connectAll(root = document, {hooks = globalThis.OpalLiveViewHooks || {}} = {}) {
  return Array.from(root.querySelectorAll("[data-opal-live-root]"), element => {
    const liveView = new OpalLiveView(element, {hooks});
    Object.defineProperty(element, "__opalLiveView", {value: liveView, configurable: true});
    liveView.connect();
    return liveView;
  });
}

const instances = connectAll();
window.addEventListener("pagehide", () => instances.forEach(instance => instance.disconnect()));
