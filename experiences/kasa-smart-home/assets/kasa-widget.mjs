const root = typeof document === "undefined" ? null : document.getElementById("piphi-widget-root");
const host = typeof window === "undefined" ? null : window.PiPhiWidgetHost;

const state = {
  bootstrap: null,
  values: new Map(),
  error: "",
  pending: "",
  subscriptions: [],
  bindingScope: "",
  ready: false,
};

export function normalizeBoolean(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const normalized = String(value ?? "").trim().toLowerCase();
  return ["1", "true", "on", "yes", "active"].includes(normalized);
}

export function formatReading(value, unit, maximumFractionDigits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  const display = Number.isFinite(numeric)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(numeric)
    : String(value);
  return unit ? `${display} ${unit}` : display;
}

export function statesFromEvent(event) {
  if (event?.kind === "snapshot") return Array.isArray(event.data?.states) ? event.data.states : [];
  if (event?.kind === "point" && event.data) {
    return [{
      capability_id: event.data.capabilityId ?? event.data.capability_id,
      value: event.data.value,
      display_value: event.data.displayValue ?? event.data.display_value,
      unit: event.data.unit,
      found: true,
    }];
  }
  return [];
}

export function commandForPower(value) {
  return normalizeBoolean(value) ? "turn_off" : "turn_on";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function widgetMode() {
  const id = String(state.bootstrap?.package?.id ?? "");
  return id.endsWith("/smart-plug") ? "smart-plug" : "device-control";
}

export function cardTargetForMode(mode) {
  return mode === "smart-plug" ? "smart-plug-card" : "device-card";
}

export async function activateTarget(targetId, widgetHost = host) {
  if (!widgetHost?.activateInteraction) return undefined;
  return widgetHost.activateInteraction(targetId);
}

function setting(name, fallback = true) {
  const value = state.bootstrap?.settings?.[name];
  return typeof value === "boolean" ? value : fallback;
}

export function dashboardDensity(settings = state.bootstrap?.settings) {
  return settings?.dashboard_density === "expanded" ? "expanded" : "compact";
}

function contentHeight() {
  const content = root?.querySelector(".kasa");
  const minimum = widgetMode() === "device-control" && dashboardDensity() === "compact" ? 104 : 180;
  return Math.max(minimum, content?.scrollHeight ?? root?.scrollHeight ?? minimum);
}

function updateValues(event) {
  for (const item of statesFromEvent(event)) {
    const id = String(item.capability_id ?? item.capabilityId ?? "").trim();
    if (!id || item.found === false) continue;
    state.values.set(id, {
      value: item.value,
      display: item.display_value ?? item.displayValue,
      unit: item.unit,
    });
  }
}

function value(id) {
  return state.values.get(id)?.value;
}

function reading(id, fallbackUnit) {
  const item = state.values.get(id);
  return formatReading(item?.display ?? item?.value, item?.unit ?? fallbackUnit);
}

function styles() {
  return `<style>
    .kasa { display: grid; align-content: start; min-height: 0; gap: var(--piphi-experience-gap, 10px); padding: 2px; color: var(--piphi-widget-text, #172033); }
    .kasa__hero, .kasa__tile { border: 1px solid var(--piphi-experience-tile-border, color-mix(in srgb, currentColor 14%, transparent)); background: var(--piphi-experience-tile-surface, color-mix(in srgb, currentColor 5%, transparent)); border-radius: var(--piphi-experience-radius, 16px); box-shadow: var(--piphi-experience-tile-shadow, none); }
    .kasa__hero { display: flex; align-items: center; justify-content: space-between; gap: 14px; min-height: 82px; padding: 13px 14px; overflow: hidden; isolation: isolate; }
    .kasa__hero[data-active="true"] { background: linear-gradient(112deg, color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 13%, var(--piphi-experience-tile-surface, transparent)), var(--piphi-experience-tile-surface, transparent) 68%); }
    .kasa__hero--level { position: relative; padding-bottom: 20px; }
    .kasa__hero--level::after { position: absolute; z-index: -1; width: 92px; height: 92px; right: -28px; top: -36px; border-radius: 50%; background: color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 11%, transparent); content: ""; }
    .kasa__level { position: absolute; right: 14px; bottom: 9px; left: 14px; height: 4px; border-radius: 999px; background: color-mix(in srgb, currentColor 14%, transparent); }
    .kasa__level-fill { position: relative; display: block; width: var(--kasa-level); height: 100%; min-width: 4px; border-radius: inherit; background: var(--piphi-experience-accent, #14b8a6); transition: width .18s ease; }
    .kasa__level-fill::after { position: absolute; width: 7px; height: 7px; right: -3px; top: 50%; border: 2px solid color-mix(in srgb, var(--piphi-experience-tile-surface, transparent) 82%, white); border-radius: 50%; background: var(--piphi-experience-accent, #14b8a6); box-shadow: 0 2px 7px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 35%, transparent); content: ""; transform: translateY(-50%); }
    .kasa__identity { min-width: 0; flex: 1; align-self: stretch; display: grid; align-content: center; padding: 0; border: 0; background: transparent; color: inherit; text-align: start; cursor: pointer; }
    .kasa__identity:hover .kasa__title, .kasa__slider-details:hover label { color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__eyebrow { margin: 0 0 5px; color: var(--piphi-widget-text-muted, #64748b); font-size: .65rem; font-weight: 800; letter-spacing: .105em; text-transform: uppercase; }
    .kasa__title { margin: 0; font-size: 1.02rem; line-height: 1.18; font-weight: 780; transition: color .16s ease; }
    .kasa__state { display: flex; align-items: center; gap: 6px; margin: 5px 0 0; color: var(--piphi-widget-text-muted, #64748b); font-size: .75rem; font-weight: 620; }
    .kasa__state-dot { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: color-mix(in srgb, currentColor 38%, transparent); }
    .kasa__hero[data-active="true"] .kasa__state-dot { background: var(--piphi-experience-accent, #14b8a6); box-shadow: 0 0 0 3px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 13%, transparent); }
    .kasa__power { display: grid; place-items: center; width: 46px; height: 46px; flex: 0 0 46px; border: 1px solid color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 24%, transparent); border-radius: 15px; background: color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 11%, transparent); color: var(--piphi-experience-accent, #0f766e); cursor: pointer; transition: transform .18s ease, background .18s ease, color .18s ease, box-shadow .18s ease; }
    .kasa__power svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 2.25; }
    .kasa__power[aria-pressed="true"] { border-color: transparent; background: var(--piphi-experience-accent, #14b8a6); color: white; box-shadow: 0 9px 24px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 30%, transparent); }
    .kasa__power:hover:not(:disabled) { transform: translateY(-1px) scale(1.025); box-shadow: 0 10px 24px color-mix(in srgb, var(--piphi-experience-accent, #14b8a6) 22%, transparent); }
    .kasa__power:active:not(:disabled) { transform: translateY(0) scale(.97); }
    .kasa__power:disabled { cursor: wait; opacity: .68; }
    .kasa__slider { display: grid; grid-template-columns: 1fr; gap: 6px; padding: 10px 12px; }
    .kasa__slider-details { display: grid; grid-template-columns: 1fr auto; gap: 12px; padding: 0; border: 0; background: transparent; color: inherit; text-align: start; cursor: pointer; }
    .kasa__slider label { font-weight: 700; transition: color .16s ease; }
    .kasa__slider output { color: var(--piphi-widget-text-muted, #64748b); font-variant-numeric: tabular-nums; }
    .kasa__slider input { grid-column: 1 / -1; width: 100%; accent-color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__section-title { margin: 2px 2px -2px; color: var(--piphi-widget-text-muted, #64748b); font-size: .72rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
    .kasa__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--piphi-experience-gap, 12px); }
    .kasa__tile { min-width: 0; padding: 11px 12px; cursor: pointer; text-align: start; color: inherit; font: inherit; }
    .kasa__tile:hover { border-color: var(--piphi-experience-accent, #14b8a6); }
    .kasa__metric-label { display: block; color: var(--piphi-widget-text-muted, #64748b); font-size: .72rem; }
    .kasa__metric-value { display: block; margin-top: 4px; font-size: 1.12rem; font-weight: 780; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .kasa__metric-value--energy { color: var(--piphi-experience-energy-accent, #d97706); }
    .kasa__message { margin: 0; padding: 10px 12px; border-radius: 12px; background: color-mix(in srgb, #dc2626 10%, transparent); color: #b91c1c; font-size: .82rem; }
    @container (max-width: 360px) { .kasa__metrics { grid-template-columns: 1fr 1fr; } .kasa__metrics > :first-child { grid-column: 1 / -1; } }
    @container (max-width: 250px) { .kasa__hero { gap: 10px; padding-inline: 11px; } .kasa__power { width: 42px; height: 42px; flex-basis: 42px; border-radius: 13px; } .kasa__level { right: 11px; left: 11px; } }
    @media (prefers-reduced-motion: reduce) { .kasa__power, .kasa__level span { transition: none; } }
  </style>`;
}

function energyTile(id, label, unit, targetId, accent = false) {
  return `<button class="kasa__tile" type="button" data-target="${targetId}">
    <span class="kasa__metric-label">${label}</span>
    <strong class="kasa__metric-value${accent ? " kasa__metric-value--energy" : ""}">${reading(id, unit)}</strong>
  </button>`;
}

function render() {
  if (!root) return;
  const mode = widgetMode();
  const cardTarget = cardTargetForMode(mode);
  const isOn = normalizeBoolean(value("switch"));
  const brightness = Number(value("brightness"));
  const density = dashboardDensity();
  const showBrightness = mode === "device-control" && Number.isFinite(brightness);
  const compactBrightness = showBrightness && density === "compact";
  const energy = mode === "smart-plug"
    ? `<p class="kasa__section-title">Energy use</p><div class="kasa__metrics">
        ${energyTile("energy_power", "Right now", "W", "smart-plug-energy", true)}
        ${setting("show_today") ? energyTile("energy_today", "Today", "kWh", "smart-plug-energy") : ""}
        ${setting("show_month") ? energyTile("energy_this_month", "This month", "kWh", "smart-plug-energy") : ""}
      </div>`
    : "";
  root.innerHTML = `${styles()}<section class="kasa kasa--${density}" aria-label="Kasa ${mode === "smart-plug" ? "smart plug" : "device control"}">
    <div class="kasa__hero${compactBrightness ? " kasa__hero--level" : ""}" data-active="${isOn}">
      <button class="kasa__identity" type="button" data-target="${cardTarget}" aria-label="View Kasa device details"><p class="kasa__eyebrow">Kasa device</p><h2 class="kasa__title">Power</h2><p class="kasa__state"><span class="kasa__state-dot" aria-hidden="true"></span><span>${isOn ? "On" : "Off"}${compactBrightness ? ` · ${Math.round(brightness)}%` : ""}</span></p></button>
      <button class="kasa__power" type="button" aria-label="Turn ${isOn ? "off" : "on"}" aria-pressed="${isOn}" ${state.pending ? "disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"></path><path d="M6.3 5.8a8 8 0 1 0 11.4 0"></path></svg></button>
      ${compactBrightness ? `<span class="kasa__level" style="--kasa-level: ${Math.max(0, Math.min(100, brightness))}%" aria-hidden="true"><span class="kasa__level-fill"></span></span>` : ""}
    </div>
    ${showBrightness && density === "expanded" ? `<div class="kasa__slider kasa__tile"><button class="kasa__slider-details" type="button" data-target="${cardTarget}" aria-label="View brightness details"><label for="brightness">Brightness</label><output for="brightness">${Math.round(brightness)}%</output></button><input id="brightness" type="range" min="0" max="100" step="1" value="${Math.round(brightness)}" aria-label="Brightness"></div>` : ""}
    ${energy}
    ${state.error ? `<p class="kasa__message" role="alert">${escapeHtml(state.error)}</p>` : ""}
  </section>`;

  root.querySelector(".kasa__power")?.addEventListener("click", () => runCommand(commandForPower(isOn)));
  root.querySelector("#brightness")?.addEventListener("change", (event) => runCommand("set_brightness", { brightness: Number(event.currentTarget.value) }, "brightness"));
  root.querySelectorAll("[data-target]").forEach((element) => element.addEventListener("click", () => {
    void activateTarget(element.dataset.target).catch((error) => {
      state.error = error instanceof Error ? error.message : "Unable to open device details.";
      render();
    });
  }));
  if (state.ready) {
    queueMicrotask(() => void host?.setHeight(contentHeight()));
  }
}

async function runCommand(commandName, args = {}, slotId = "power") {
  if (!host || state.pending) return;
  state.pending = commandName;
  state.error = "";
  render();
  try {
    await host.executeCommand({ commandName, args, slotId });
  } catch (error) {
    state.error = error instanceof Error ? error.message : "The device did not respond. Try again.";
  } finally {
    state.pending = "";
    render();
  }
}

async function connect(bootstrap) {
  state.bootstrap = bootstrap;
  render();
  if (!state.ready) {
    await host.ready({ height: contentHeight() });
    state.ready = true;
  }
  const bindings = Array.isArray(bootstrap?.bindings) ? bootstrap.bindings : [];
  const bindingScope = bindings
    .map((slot) => [slot.id, slot.binding?.configId, slot.binding?.deviceKey, slot.binding?.capabilityId].join(":"))
    .join("|");
  if (state.bindingScope === bindingScope && state.subscriptions.length) return;
  for (const unsubscribe of state.subscriptions.splice(0)) {
    try { await unsubscribe(); } catch { /* The host may already have released it. */ }
  }
  state.bindingScope = bindingScope;
  state.values.clear();
  for (const slot of bindings) {
    try {
      const unsubscribe = await host.subscribeState({ slotId: slot.id }, (event) => {
        if (event?.kind === "error") state.error = event.error?.message || "Live updates are temporarily unavailable.";
        else { state.error = ""; updateValues(event); }
        render();
      });
      state.subscriptions.push(unsubscribe);
    } catch (error) {
      state.error = error instanceof Error ? error.message : "Unable to load device state.";
      render();
    }
  }
}

if (root && host) {
  host.subscribe((bootstrap) => void connect(bootstrap));
}
