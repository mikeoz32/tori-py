function errorMessage(payload, fallback) {
  if (typeof payload === "string") return payload;
  return payload?.detail
    ?? payload?.message
    ?? payload?.error
    ?? payload?.errors?.[0]?.message
    ?? fallback;
}

export class ApiClient {
  constructor(keycloak) {
    this.keycloak = keycloak;
  }

  async request(path, options = {}) {
    if (!navigator.onLine) {
      throw new Error("You are offline. Reconnect and retry.");
    }
    await this.keycloak.updateToken(30);
    let response;
    try {
      response = await fetch(path, {
        ...options,
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${this.keycloak.token}`,
          ...options.headers,
        },
      });
    } catch {
      throw new Error("Cannot reach the gateway. Check your connection and retry.");
    }
    if (!response.ok) {
      const text = await response.text();
      let payload = text;
      try {
        payload = JSON.parse(text);
      } catch {
        // Plain-text errors remain useful to the operator.
      }
      throw new Error(errorMessage(payload, `Gateway returned ${response.status}`));
    }
    return response.status === 204 ? null : response.json();
  }
}
