import {html} from "/assets/lit-core.min.js";

function markerLabel(resource) {
  const number = resource.name?.match(/\d+/)?.[0];
  if (number) return number;
  return resource.name
    ?.split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || "?";
}

function markerTemplate(host, resource) {
  const x = `${Math.max(4, Math.min(96, Number(resource.x ?? 500) / 10))}%`;
  const y = `${Math.max(8, Math.min(92, Number(resource.y ?? 500) / 10))}%`;
  const className = resource.kind === "room" ? "room-pin" : "desk";
  return html`
    <button
      class="resource ${className} ${host.selected?.id === resource?.id ? "selected" : ""}"
      data-id=${resource?.id ?? ""}
      data-name=${resource?.name ?? ""}
      data-kind=${resource?.kind ?? ""}
      style=${`--x:${x};--y:${y}`}
      aria-label=${resource?.name ?? resource?.id ?? "Workplace resource"}
      ?hidden=${resource.active === false}
      @click=${() => host.selectResource(resource)}
    >${markerLabel(resource)}</button>
  `;
}

export function floorPlanTemplate(host) {
  return html`
    <div class="map-panel">
      <div class="map-tools" aria-label="Floor plan controls">
        <span class="floor-stamp">N.03 <small>scale 1:200</small></span>
        <div class="zoom-controls">
          <button type="button" aria-label="Zoom out" @click=${host.zoomOut}>-</button>
          <button type="button" aria-label="Reset floor plan" @click=${host.zoomReset}>Reset</button>
          <button type="button" aria-label="Zoom in" @click=${host.zoomIn}>+</button>
        </div>
      </div>
      <div
        class="map-viewport"
        id="map-viewport"
        tabindex="0"
        aria-label="Interactive floor plan. Drag to pan; use plus and minus to zoom."
        @pointerdown=${host.startDrag}
        @pointermove=${host.moveDrag}
        @pointerup=${host.endDrag}
        @pointercancel=${host.endDrag}
      >
        <div
          class="floorplan"
          id="floorplan"
          style=${`transform:translate(${host.mapX}px, ${host.mapY}px) scale(${host.mapScale})`}
        >
          <div class="north">N ↑</div>
          <div class="room studio">STUDIO<br><small>01</small></div>
          <div class="room tea">TEA / PRINT</div>
          <div class="room library">LIBRARY</div>
          <div class="room meeting">MEET 03</div>
          <div class="room lounge">COMMON GROUND</div>
          <div class="corridor">CIRCULATION / 1800 CLEAR</div>
          ${host.resources.map((resource) => markerTemplate(host, resource))}
          <span class="elevator">⇅<br><small>LIFT</small></span>
          <span class="entry">ENTRY →</span>
        </div>
      </div>
      <p class="map-note"><span>Drag to move</span><span>Select a marker to reserve</span></p>
    </div>
  `;
}
