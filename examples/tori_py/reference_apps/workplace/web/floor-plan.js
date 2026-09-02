import {html} from "/assets/lit-core.min.js";

const MARKERS = [
  ["Desk 17", "desk", "17", "16%", "58%"],
  ["Desk 18", "desk", "18", "28%", "58%"],
  ["Desk 19", "desk", "19", "40%", "58%"],
  ["Desk 20", "desk", "20", "52%", "58%"],
  ["Focus booth A", "booth", "A", "73%", "58%"],
  ["Focus booth B", "booth", "B", "84%", "58%"],
  ["Meet 03", "room-pin", "03", "71%", "24%"],
];

function markerTemplate(host, marker) {
  const [name, className, label, x, y] = marker;
  const resource = host.resources.find((item) => item.name === name);
  return html`
    <button
      class="resource ${className} ${host.selected?.id === resource?.id ? "selected" : ""}"
      data-id=${resource?.id ?? ""}
      data-name=${name}
      data-kind=${resource?.kind ?? ""}
      style=${`--x:${x};--y:${y}`}
      ?hidden=${!resource || resource.active === false}
      @click=${() => host.selectResource(resource)}
    >${label}</button>
  `;
}

export function floorPlanTemplate(host) {
  return html`
    <div class="map-panel">
      <div class="map-tools" aria-label="Floor plan controls">
        <span class="floor-stamp">N.03 <small>scale 1:200</small></span>
        <div class="zoom-controls">
          <button type="button" aria-label="Zoom out" @click=${host.zoomOut}>-</button>
          <button type="button" aria-label="Reset floor plan" @click=${host.zoomReset}>o</button>
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
          ${MARKERS.map((marker) => markerTemplate(host, marker))}
          <span class="elevator">⇅<br><small>LIFT</small></span>
          <span class="entry">ENTRY →</span>
        </div>
      </div>
      <p class="map-note">Drag the drawing to inspect. Select a marker to request a booking.</p>
    </div>
  `;
}
