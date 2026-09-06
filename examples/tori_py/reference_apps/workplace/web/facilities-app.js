import {html} from "/assets/lit-core.min.js";

import {adminPanelTemplate} from "/web/admin-panel.js";
import {WorkplaceApp} from "/web/workplace-app.js";

const FACILITY_SECTIONS = Object.freeze({
  overview: {label: "Overview", description: "Exceptions and current signals"},
  spaces: {label: "Spaces", description: "Inventory and lifecycle"},
  policies: {label: "Policies", description: "Hours and booking rules"},
  audit: {label: "Audit", description: "Booking transitions"},
  system: {label: "System health", description: "Persistent delivery"},
});

export class FacilitiesApp extends WorkplaceApp {
  get isFacilitiesApplication() {
    return true;
  }

  render() {
    const section = FACILITY_SECTIONS[this.activeFacility] ?? FACILITY_SECTIONS.overview;
    const denied = this.initialized && !this.admin;
    return html`
      <a class="skip-link" href="#facilities-content">Skip to facilities workspace</a>
      <div class="workspace-shell facilities-shell">
        <aside class="workspace-sidebar">
          <header class="masthead">
            <div class="wordmark"><span aria-hidden="true">⌑</span><strong>TORI</strong> SPACE</div>
            <p class="desk-label">Facilities operations <span>/</span> N</p>
          </header>
          <nav id="facilities-navigation" class="workspace-navigation facilities-navigation" aria-label="Facilities">
            <p class="navigation-label">Facilities</p>
            ${Object.entries(FACILITY_SECTIONS).map(([key, item], index) => html`
              <button
                type="button"
                data-facility=${key}
                aria-label=${item.label}
                aria-current=${this.activeFacility === key ? "page" : "false"}
                ?disabled=${!this.admin}
                @click=${this.openFacilitySection}
              ><span>0${index + 1}</span><strong>${item.label}</strong><small>${item.description}</small></button>
            `)}
          </nav>
          <div class="sidebar-status">
            <span class="signal ${this.offline ? "offline" : ""}" aria-hidden="true"></span>
            <div>
              <small>${this.offline ? "Connection paused" : "Facilities workspace"}</small>
              <strong id="identity-text">${this.actor}</strong>
              <span>${this.initialized ? this.tenant : "Checking identity"}</span>
            </div>
          </div>
          <a class="sidebar-app-link" href="/live/workplace">Employee workspace</a>
          <button class="sidebar-signout" id="logout" type="button" ?hidden=${!this.initialized} @click=${this.logout}>Sign out</button>
        </aside>
        <main id="facilities-content" class="workspace-content facilities-content">
          <header class="workspace-intro compact-intro" aria-labelledby="page-title">
            <div>
              <p class="eyebrow">Building N / Facilities</p>
              <h1 id="page-title">${section.label}</h1>
              <p>${section.description}</p>
            </div>
            <dl class="workspace-context" aria-label="Current facilities context">
              <div><dt>Office</dt><dd>Building N</dd></div>
              <div><dt>Tenant</dt><dd>${this.tenant || "-"}</dd></div>
              <div><dt>Timezone</dt><dd>${this.timeZone}</dd></div>
            </dl>
          </header>
          ${denied
            ? html`<section class="access-denied"><p class="eyebrow">Access restricted</p><h2>Facilities administrator role required</h2><p>Use the employee workspace or sign in with an authorized facilities account.</p><a class="action-button" href="/live/workplace">Open employee workspace</a></section>`
            : this.admin
              ? html`<section class="workspace-view admin-panel" id="admin-panel">${adminPanelTemplate(this)}</section>`
              : html`<p class="list-message">Checking facilities access...</p>`}
        </main>
      </div>
      <details class="developer-drawer app-diagnostics">
        <summary>Developer diagnostics</summary>
        <footer class="workspace-footer">
          <span>TORI SPACE / FACILITIES REFERENCE</span>
          <span id="api-status" role="status">${this.offline ? "OFFLINE / CHANGES PAUSED" : this.initialized ? "GATEWAY LINKED" : "AWAITING GATEWAY"}</span>
          <span>NOT A BUILDING SAFETY SYSTEM</span>
        </footer>
      </details>
    `;
  }
}
