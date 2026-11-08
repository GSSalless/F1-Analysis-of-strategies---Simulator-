const el = (id) => document.getElementById(id);
const controls = Object.fromEntries(["event", "driver", "mode", "scenario", "horizon", "lap", "pit"].map((id) => [id, el(id)]));
const tyreNames = {
  SOFT: ["Macio", "#ff7474"], MEDIUM: ["Médio", "#ffd857"], HARD: ["Duro", "#eef2f4"],
  INTERMEDIATE: ["Intermediário", "#66e79a"], WET: ["Chuva forte", "#76b9ff"],
};
const stateNames = {green: "Bandeira verde", sc: "Safety car", vsc: "VSC", red: "Bandeira vermelha", closed: "Boxes fechados"};
const trackNames = {dry: "Seca", damp: "Úmida", wet: "Molhada", unknown: "Sem dados"};
const number = new Intl.NumberFormat("pt-BR", {minimumFractionDigits: 1, maximumFractionDigits: 2});
let events = [];
let race;
let driver;
let timer;
let revision = 0;
let playbackIndex = 0;
let pending = false;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (className) node.className = className;
  return node;
}

async function api(path, args) {
  const response = await fetch(path + (args ? "?" + new URLSearchParams(args) : ""));
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Erro ao consultar o replay.");
  return data;
}

function setOptions(select, options, preferred) {
  select.replaceChildren();
  for (const [value, text] of options) {
    const option = element("option", text);
    option.value = value;
    select.append(option);
  }
  if (options.some(([value]) => String(value) === String(preferred))) select.value = preferred;
}

function status(message) { el("status").textContent = message; }
function secs(value) { return typeof value === "number" ? number.format(value) + " s" : (value || "—"); }
function signed(value) { return (value > 0 ? "+" : "") + number.format(value) + " s"; }
function time(value) {
  if (value == null) return "—";
  const minutes = Math.floor(value / 60);
  return minutes + ":" + (value % 60).toFixed(3).padStart(6, "0").replace(".", ",");
}
function tyre(compound) {
  if (!tyreNames[compound]) return element("span", "—");
  const [label, color] = tyreNames[compound];
  const span = element("span", null, "tyre");
  const icon = element("i");
  icon.style.color = color;
  icon.setAttribute("aria-hidden", "true");
  span.append(icon, document.createTextNode(label));
  return span;
}

function table(id, headers, rows) {
  const head = element("thead");
  const heading = element("tr");
  for (const header of headers) {
    const cell = element("th", header);
    cell.scope = "col";
    heading.append(cell);
  }
  head.append(heading);
  const body = element("tbody");
  for (const [values, className] of rows) {
    const row = element("tr", null, className);
    for (const value of values) {
      const cell = element("td");
      cell.append(value instanceof Node ? value : document.createTextNode(value ?? "—"));
      row.append(cell);
    }
    body.append(row);
  }
  el(id).replaceChildren(head, body);
}

function setPlaying(active) {
  clearInterval(timer);
  timer = null;
  el("play").textContent = active ? "Ⅱ Pausar" : "▶ Reproduzir";
  if (active) timer = setInterval(() => { if (!pending) move(1); }, 1050);
}

function move(delta) {
  if (!driver) return;
  const next = playbackIndex + delta;
  if (next < 0 || next >= driver.laps.length) {
    setPlaying(false);
    return;
  }
  playbackIndex = next;
  controls.lap.value = next;
  render();
}

async function loadEvents() {
  setPlaying(false);
  status("Consultando dados locais…");
  try {
    const prior = controls.event.value;
    events = await api("/api/events");
    const preferred = prior || events.find((event) => event.available)?.event;
    setOptions(controls.event, events.map((e) => [e.event, e.name + (e.available ? "" : " · aguardando dados")]), preferred);
    await changeRace();
  } catch (error) {
    status(error.message);
  }
}

async function changeRace() {
  setPlaying(false);
  pending = false;
  revision++;
  race = events.find((e) => e.event === controls.event.value);
  el("race-title").textContent = race?.name || "Selecione uma corrida";
  el("source").replaceChildren();
  el("content").hidden = true;
  for (const key of ["driver", "mode", "scenario", "horizon"]) controls[key].disabled = !race?.available;
  el("playback").hidden = !race?.available;
  el("pit-label").hidden = true;
  if (!race?.available) {
    setOptions(controls.driver, []);
    status("Aguardando importação pós-corrida. No Terminal, execute: python3 ingest.py " + (race?.event || "interlagos"));
    return;
  }
  el("source").append(document.createTextNode(race.source + " · " + race.actual_laps + " voltas registradas"));
  for (const source of race.provenance || []) {
    const link = element("a", source.name);
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    el("source").append(document.createTextNode(" · "), link);
  }
  const preferred = race.event === "mexico" ? 3 : 1;
  setOptions(controls.driver, race.drivers.map((d) => [d.number, d.name]), preferred);
  await changeDriver();
}

async function changeDriver() {
  setPlaying(false);
  const token = ++revision;
  driver = race?.drivers?.find((d) => d.number === Number(controls.driver.value));
  if (!driver) return;
  playbackIndex = 0;
  controls.lap.max = driver.laps.length - 1;
  controls.lap.min = 0;
  controls.lap.value = 0;
  try {
    const pits = await api("/api/pits", {event: race.event, driver: driver.number});
    if (token !== revision) return;
    setOptions(controls.pit, pits.map((p) => [
      p.lap, "V" + p.lap + " · " + (tyreNames[p.compound]?.[0] || "composto desconhecido") +
        (p.suspension ? " · suspensão" : " · " + secs(p.duration)),
    ]), pits.find((p) => !p.suspension)?.lap);
    changeMode();
  } catch (error) {
    if (token === revision) status(error.message);
  }
}

function changeMode() {
  setPlaying(false);
  const reviewing = controls.mode.value === "review";
  el("playback").hidden = reviewing;
  el("pit-label").hidden = !reviewing;
  el("scenario-label").hidden = reviewing;
  render();
}

async function render() {
  if (!race?.available || !driver) return;
  const token = ++revision;
  const reviewing = controls.mode.value === "review";
  const lap = driver.laps[playbackIndex];
  const args = {event: race.event, driver: driver.number, lap, scenario: controls.scenario.value, horizon: controls.horizon.value};
  el("lap-label").textContent = "V" + lap + " / " + race.actual_laps;
  if (reviewing) {
    if (!controls.pit.value) {
      el("content").hidden = true;
      status("Sem paradas registradas para este piloto.");
      return;
    }
    args.pit = controls.pit.value;
  }
  pending = true;
  try {
    const data = await api("/api/replay", args);
    if (token !== revision) return;
    status(reviewing ? "Comparação retrospectiva · controle observado e condições de pista do replay. Curvas ajustadas só com voltas anteriores à janela." :
      "Início da volta do piloto · informações disponíveis até este ponto da corrida.");
    draw(data);
    el("content").hidden = false;
  } catch (error) {
    if (token === revision) {
      setPlaying(false);
      el("content").hidden = true;
      status(error.message);
    }
  } finally {
    if (token === revision) pending = false;
  }
}

function metric(title, main, detail) {
  const card = element("div", null, "metric");
  const value = element("strong");
  value.append(main instanceof Node ? main : document.createTextNode(main));
  card.append(element("small", title), value, element("span", detail));
  return card;
}

function driverCode(id) { return race.drivers.find((d) => d.number === id)?.code || "—"; }

function draw({snapshot: s, strategy}) {
  const last = s.last_pit;
  const age = s.age != null ? s.age + " voltas no set" :
    s.stint_start != null ? "≥ " + (s.lap - s.stint_start) + " voltas no stint" : "Idade indisponível";
  el("metrics").replaceChildren(
    metric("PNEU ATUAL", tyre(s.compound), age),
    metric("ÚLTIMA PARADA", last ? "V" + last.lap_number : "—", last?.suspension ? "Com suspensão" : secs(last?.lane_duration ?? last?.pit_duration)),
    metric("À FRENTE", secs(s.gap_front), driverCode(s.front)),
    metric("ATRÁS", secs(s.gap_rear), driverCode(s.rear)),
    metric("PISTA ESTIMADA", trackNames[s.track], s.assumed_track ? "Hipótese · corrida em slicks" :
      (s.weather?.track_temperature != null ? s.weather.track_temperature + " °C" : stateNames[s.control])),
    metric("MELHOR VOLTA OBSERVADA", time(s.best?.duration), s.best ? "V" + s.best.lap + (s.last_lap ? " · última " + time(s.last_lap.duration) : "") : "Sem volta concluída"),
  );
  el("gap-note").textContent = race.timing === "lap_crossings" ?
    "Intervalos estimados na passagem mais recente em comum. A posição em pista pode mudar entre passagens." :
    "Última amostra de intervalo disponível no início da volta. Valores ausentes ou pilotos com volta perdida podem limitar a projeção.";
  table("board", ["Pos.", "Piloto", "Voltas", "Líder", "À frente"], s.board.map((row) => [
    [row.position, driverCode(row.driver) + (row.active ? "" : " · sem atualização"), row.completed, secs(row.gap), secs(row.interval)],
    row.driver === driver.number ? "selected" : "",
  ]));
  drawStrategy(strategy, s);
  drawChart(s.history);
}

function drawStrategy(strategy, snapshot) {
  const options = strategy.options;
  if (!options.length) {
    el("decision").textContent = strategy.reason || "Comparação indisponível.";
    el("strategy-note").textContent = "";
    el("strategies").replaceChildren();
    el("curves").replaceChildren();
    return;
  }
  const top = options[0];
  const reliable = top.stop != null && top.low > 0;
  el("decision").textContent = reliable ? "V" + top.stop + " · " + tyreNames[top.compound][0] + " · " + signed(top.delta) :
    top.stop == null ? "Manter o pneu lidera neste cenário" : "Parada na V" + top.stop + " lidera, com resultado sensível às premissas";
  const actual = strategy.actual_pit ? "Parada real na V" + strategy.actual_pit +
    (strategy.actual_stop?.suspension ? " durante a suspensão." : ".") + " " : "";
  el("strategy-note").textContent = actual + "Até a V" + strategy.through + " · perda base nos boxes " +
    secs(strategy.pit_loss) + (strategy.pit_samples ? " (" + strategy.pit_samples + " paradas prévias)" : " (premissa)") +
    " · ganho vs. seguir. A faixa varia desgaste e perda nos boxes. " +
    (strategy.age_estimated ? "Quilometragem anterior do jogo desconhecida. " : "") +
    (snapshot.control !== "green" ? stateNames[snapshot.control] + " no início da janela. " : "") +
    "Pista projetada: " + [...new Set(strategy.track_path)].map((t) => trackNames[t].toLowerCase()).join(" → ") + ".";
  table("strategies", ["Ação", "Composto", "Ganho", "Faixa", "Retorno est.", "Tráfego est."], options.map((row, i) => [[
    row.stop ? "Parar V" + row.stop + (row.actual ? " · real" : "") : "Seguir",
    tyre(row.compound), element("span", signed(row.delta), row.delta > 0 ? "gain" : row.delta < 0 ? "loss" : ""),
    signed(row.low) + " a " + signed(row.high),
    row.rejoin ? "P" + row.rejoin[0] + (row.rejoin[1] > row.rejoin[0] ? "–P" + row.rejoin[1] : "") : "—", secs(row.traffic),
  ], i === 0 ? "highlight" : row.actual ? "selected" : ""]));
  table("curves", ["Composto", "Desgaste¹", "Voltas", "Stints"], strategy.curves.map((row) => [[
    tyre(row.compound), (row.wear * 1000).toFixed(0) + " ms/volta" + (row.fit === "prior" ? " *" : ""),
    row.observations, row.stints,
  ]]));
  el("curves").append(element("caption", "¹ Perda de ritmo por volta de uso. * Premissa sem ajuste local.", "muted"));
}

function drawChart(history) {
  const visible = history.slice(-22);
  const laps = visible.filter((row) => row.duration < 150);
  const root = el("chart");
  if (!laps.length) {
    root.replaceChildren(element("p", "O gráfico começa depois da primeira volta concluída.", "muted"));
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, val]) => node.setAttribute(key, val));
    if (text) node.textContent = text;
    return node;
  }
  const graph = svg("svg", {viewBox: "0 0 390 164", role: "img", "aria-label": "Tempos das últimas voltas do piloto"});
  const lo = Math.min(...laps.map((r) => r.duration)) - .5;
  const hi = Math.max(...laps.map((r) => r.duration)) + .5;
  const left = visible[0].lap;
  const right = visible.at(-1).lap;
  const point = (row) => [46 + 324 * (row.lap - left) / Math.max(1, right - left), 129 - (row.duration - lo) * 103 / (hi - lo)];
  for (let line = 0; line < 3; line++) {
    const y = 26 + line * 51.5;
    graph.append(svg("line", {x1: 44, y1: y, x2: 371, y2: y, stroke: "#3a424d"}),
      svg("text", {x: 2, y: y + 4, fill: "#aeb7c3", "font-size": 10}, time(hi - line * (hi - lo) / 2).slice(0, -2)));
  }
  let previous;
  for (const row of laps) {
    const [x, y] = point(row);
    const color = tyreNames[row.compound]?.[1] || "#aeb7c3";
    if (previous && row.lap === previous.lap + 1) {
      const [px, py] = point(previous);
      graph.append(svg("line", {x1: px, y1: py, x2: x, y2: y, stroke: color, opacity: .55}));
    }
    const dot = svg("circle", {cx: x, cy: y, r: 3.6, fill: row.clean ? color : "#181b20", stroke: color});
    dot.append(svg("title", {}, "V" + row.lap + " · " + time(row.duration)));
    graph.append(dot);
    previous = row;
  }
  graph.append(svg("text", {x: 46, y: 151, fill: "#aeb7c3", "font-size": 10}, "V" + left));
  if (right !== left) graph.append(svg("text", {x: 350, y: 151, fill: "#aeb7c3", "font-size": 10}, "V" + right));
  root.replaceChildren(graph);
}

el("reload").onclick = loadEvents;
controls.event.onchange = changeRace;
controls.driver.onchange = changeDriver;
controls.mode.onchange = changeMode;
controls.scenario.onchange = render;
controls.horizon.onchange = render;
controls.pit.onchange = render;
controls.lap.oninput = () => { setPlaying(false); playbackIndex = Number(controls.lap.value); render(); };
el("play").onclick = () => {
  if (timer) setPlaying(false);
  else {
    if (driver && playbackIndex === driver.laps.length - 1) {
      playbackIndex = 0;
      controls.lap.value = 0;
      render();
    }
    setPlaying(true);
  }
};
el("prev").onclick = () => { setPlaying(false); move(-1); };
el("next").onclick = () => { setPlaying(false); move(1); };
loadEvents();
