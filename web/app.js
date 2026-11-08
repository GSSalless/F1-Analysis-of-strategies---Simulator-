const el = id => document.getElementById(id);
const compact = new Intl.NumberFormat("pt-BR", {maximumFractionDigits: 2});
const tyres = {
  SOFT: ["Macio", "#ff8278", "M"], MEDIUM: ["Médio", "#f8db76", "ME"],
  HARD: ["Duro", "#edf2f2", "D"], INTERMEDIATE: ["Intermediário", "#62dda0", "I"],
  WET: ["Chuva forte", "#79b7ff", "C"],
};
const tracks = {dry: "Seca", damp: "Úmida", wet: "Molhada", unknown: "Indeterminada"};
const tabButtons = [...document.querySelectorAll("#tabs button")];
const stored = new Map();
let race, driver, selectedTab = "overview", revision = 0;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (className) node.className = className;
  return node;
}
function add(parent, ...children) { parent.append(...children); return parent; }
function panel(title, label = "") {
  const node = element("article", null, "panel");
  if (label) node.append(element("p", label, "eyebrow"));
  return add(node, element("h3", title));
}
function note(text) { return element("p", text, "muted"); }
function num(value, unit = "") { return Number.isFinite(value) ? compact.format(value) + unit : (value ?? "—"); }
function gap(value) { return num(value, " s"); }
function lapTime(value) {
  if (!Number.isFinite(value)) return "—";
  const ms = Math.round(value*1000);
  return Math.floor(ms/60000)+":"+((ms%60000)/1000).toFixed(3).padStart(6, "0").replace(".", ",");
}
function clockTime(value) {
  return value ? new Date(value).toLocaleTimeString("pt-BR", {
    timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }) : "—";
}
function tyre(compound) {
  if (!tyres[compound]) return element("span", "—");
  const span = element("span", null, "tyre");
  const ring = element("i");
  ring.style.color = tyres[compound][1];
  ring.setAttribute("aria-hidden", "true");
  return add(span, ring, document.createTextNode(tyres[compound][0]));
}
function metric(label, value, context) {
  return add(element("div", null, "metric"), element("small", label), element("strong", value),
    element("span", context));
}
function table(headers, rows, highlight = -1, wrap = -1) {
  const header = element("tr");
  headers.forEach(label => {
    const th = element("th", label);
    th.scope = "col";
    header.append(th);
  });
  const body = element("tbody");
  rows.forEach((values, i) => {
    const row = element("tr", null, i === highlight ? "selected" : "");
    values.forEach((value, j) => {
      const cell = element("td", null, j === wrap ? "message" : "");
      cell.append(value instanceof Node ? value : document.createTextNode(value ?? "—"));
      row.append(cell);
    });
    body.append(row);
  });
  return add(element("div", null, "scroll"),
    add(element("table"), add(element("thead"), header), body));
}
function details(label, ...content) {
  return add(element("details", null, "details"), element("summary", label), ...content);
}
function setOptions(select, values, preferred) {
  select.replaceChildren();
  for (const [value, label] of values) {
    const option = element("option", label);
    option.value = value;
    select.append(option);
  }
  if (values.some(([value]) => String(value) === String(preferred))) select.value = preferred;
}
async function api(path, parameters) {
  const response = await fetch(path + (parameters ? "?" + new URLSearchParams(parameters) : ""));
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Falha ao consultar os dados.");
  return data;
}
function person(number) { return race.drivers.find(row => row.number === number); }
function code(number) { return person(number)?.code || number; }
function eventQuery() { return {event: race.event, driver: driver.number}; }

async function loadEvents() {
  const prior = el("event").value;
  el("status").textContent = "Lendo as corridas locais…";
  try {
    const events = await api("/api/events");
    const valid = events.filter(event => event.available);
    const choices = events.map(event => [event.event, event.name + (event.available ? "" : " · aguardando dados")]);
    setOptions(el("event"), choices, prior || valid[0]?.event);
    await loadRace();
  } catch (error) {
    el("status").textContent = error.message;
  }
}
async function loadRace() {
  const token = ++revision;
  const event = el("event").value;
  const previousDriver = driver?.number;
  el("status").textContent = "Carregando a corrida…";
  el("content").hidden = true;
  el("analyze").disabled = true;
  el("driver").disabled = true;
  try {
    const data = await api("/api/race", {event});
    if (token !== revision) return;
    race = data;
    stored.clear();
    el("race-title").textContent = race.name;
    el("source").replaceChildren(document.createTextNode(race.source + " · " + race.actual_laps + " voltas"));
    for (const source of race.provenance) {
      const link = element("a", source.name);
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      el("source").append(document.createTextNode(" · "), link);
    }
    const drivers = race.classification.map(row => person(row.driver_number)).filter(Boolean);
    setOptions(el("driver"), drivers.map(d => [d.number, d.name]), previousDriver);
    driver = person(Number(el("driver").value));
    el("driver").disabled = false;
    el("analyze").disabled = !driver;
    el("status").textContent = "";
    el("content").hidden = false;
    openTab("overview");
  } catch (error) {
    if (token !== revision) return;
    el("race-title").textContent = el("event").selectedOptions[0]?.textContent || "Corrida";
    el("source").textContent = "";
    el("status").textContent = error.message;
  }
}

function strip() {
  const row = element("div", null, "track-strip");
  for (const phase of race.phases) {
    const part = element("span", null, "track-" + phase.track);
    part.style.flex = "1";
    part.title = "Volta " + phase.lap + " · " + tracks[phase.track] +
      " · pneus de chuva " + (phase.wet_share == null ? "—" : Math.round(phase.wet_share*100)+"%");
    row.append(part);
  }
  const legend = element("div", null, "legend");
  for (const [name, label] of Object.entries(tracks)) {
    const sample = element("span", label);
    sample.style.setProperty("--key", {dry:"#b8dc5a",damp:"#71bfbb",wet:"#669eff",unknown:"#495257"}[name]);
    legend.append(sample);
  }
  return add(element("div"), row, legend);
}

function overview() {
  const winner = race.classification[0];
  const best = [...race.drivers].filter(d => d.best).sort((a,b) => a.best.time-b.best.time)[0];
  const metrics = add(element("div", null, "metrics"),
    metric("VENCEDOR", person(winner?.driver_number)?.name || "—", lapTime(winner?.duration)),
    metric("VOLTA MAIS RÁPIDA", lapTime(best?.best.time), best ? code(best.number)+" · V"+best.best.n : "—"),
    metric("PILOTOS", String(race.drivers.length), race.actual_laps+" voltas da prova"),
    metric("REGISTROS DE BOX", String(race.pits.length), "Veja compostos em Pneus e boxes"));
  const conditions = add(panel("Condição estimada por volta", "LINHA DA CORRIDA"), strip(),
    note("A estimativa cruza a chuva medida, os avisos de aderência e os compostos observados no pelotão."));
  const ranking = add(panel("Classificação da corrida", "RESULTADO"),
    table(["Pos.", "Piloto", "Equipe", "Grid", "Voltas", "Tempo / Diferença", "Pontos"],
      race.classification.map(r => [
        r.dsq ? "DSQ" : r.dns ? "DNS" : r.dnf ? "DNF" : r.position,
        person(r.driver_number)?.name, person(r.driver_number)?.team, person(r.driver_number)?.pit_start ? "Box" : person(r.driver_number)?.grid,
        r.number_of_laps, r.position === 1 ? lapTime(r.duration) : gap(r.gap_to_leader), r.points,
      ]), race.classification.findIndex(r => r.driver_number === driver?.number)));
  if (winner?.estimated) ranking.append(note("Ordem reconstruída pelos tempos de volta da fonte disponível."));
  return add(element("div", null, "stack"), metrics, conditions, ranking);
}

function lapSeries(d, field, name = d.code, color) {
  return {name, color, points: d.laps.map(row => [row.n, field(row)])};
}
function pace() {
  const final = race.classification.findIndex(r => r.driver_number === driver.number);
  const nearest = race.classification.slice(Math.max(0, final-2), final+3)
    .map(row => person(row.driver_number)).filter(d => d && d.number !== driver.number);
  const field = [driver, ...nearest];
  const markers = race.pits.filter(p => p.driver === driver.number).map(p => p.lap);
  const lapLabel = n => "V" + Math.round(n);
  const positions = lineChart("Posição ao longo da corrida", field.map(d => lapSeries(d, r => r.position)),
    {reverse:true, ymin:1, ymax:race.drivers.length, xmin:1, xmax:race.actual_laps, xLabel:lapLabel});
  const times = lineChart("Comparativo dos tempos de volta",
    field.map(d => lapSeries(d, r => r.time < 155 ? r.time : null)), {xLabel:lapLabel, yLabel:gap, markers});
  const deltas = lineChart("Diferença para o líder", field.map(d => lapSeries(d, r => r.gap)),
    {xLabel:lapLabel, yLabel:gap, markers});
  const sectors = lineChart("Setores", [0,1,2].map(i => lapSeries(driver, r => r.sectors[i], "Setor "+(i+1))),
    {xLabel:lapLabel, yLabel:gap, markers});
  return add(element("div", null, "stack"),
    add(element("div", null, "columns"), add(panel("Posições"), positions), add(panel("Tempos por volta"), times)),
    add(element("div", null, "columns"), add(panel("Intervalo para o líder"), deltas), add(panel("Setores do piloto"), sectors)),
    add(panel("Cronometragem do piloto"), note("As linhas tracejadas nos gráficos marcam as paradas observadas. Voltas acima de 155 s aparecem na tabela."),
      table(["Volta", "Tempo", "S1", "S2", "S3", "Vel. máxima medida", "Composto", "Idade", "Pos.", "À frente", "Ao líder"],
        driver.laps.map(r => [r.n,lapTime(r.time),gap(r.sectors[0]),gap(r.sectors[1]),gap(r.sectors[2]),
          num(r.speed, " km/h"),tyre(r.compound),num(r.age," V"),r.position,gap(r.interval),gap(r.gap)]))));
}

function pits() {
  const plot = element("div", null, "stints");
  for (const finish of race.classification) {
    const d = person(finish.driver_number);
    if (!d) continue;
    const label = element("button", d.code, d.number === driver.number ? "selected" : "");
    label.type = "button";
    label.setAttribute("aria-label", "Selecionar "+d.name);
    label.onclick = () => selectDriver(d.number);
    const bar = element("div", null, "bar");
    for (const row of d.stints) {
      if (!tyres[row.compound]) continue;
      const last = Math.min(row.lap_end || race.actual_laps, race.actual_laps);
      const span = element("span", tyres[row.compound][2]);
      span.style.left = (row.lap_start-1) / race.actual_laps * 100+"%";
      span.style.width = Math.max(0,(last-row.lap_start+1)/race.actual_laps*100)+"%";
      span.style.background = tyres[row.compound][1];
      span.title = d.code+" · "+tyres[row.compound][0]+" · V"+row.lap_start+"–"+last;
      bar.append(span);
    }
    plot.append(add(element("div", null, "stint-row"), label, bar));
  }
  const selected = race.pits.filter(p => p.driver === driver.number);
  const rows = list => list.map(p => [code(p.driver),p.lap,clockTime(p.at),tyre(p.before),tyre(p.after),
    p.suspension ? "Suspensão" : gap(p.lane),gap(p.stationary)]);
  const headers = ["Piloto","Volta","Horário","Antes","Depois","Pit lane","Carro parado"];
  return add(element("div", null, "stack"),
    add(panel("Estratégia que cada piloto usou"), note("Cada barra representa um jogo de pneus ao longo da corrida. Clique na sigla para trocar o piloto."),
      add(element("div", null, "scroll"), plot)),
    add(panel("Paradas de "+driver.name), selected.length ? table(headers,rows(selected)) : note("Nenhuma parada registrada."),
      details("Ver paradas de todo o pelotão",table(headers,rows([...race.pits].sort((a,b)=>a.lap-b.lap))))));
}

function weather() {
  const points = race.weather;
  const from = (name, field) => ({name, points: points.map(p => [p.minute,p[field]])});
  const opts = {xLabel:n=>Math.round(n)+" min"};
  const data = points.length ? add(element("div", null, "stack"),
    add(element("div", null, "columns"),
      add(panel("Temperatura"),lineChart("Temperatura do ar e da pista",[from("Ar °C","air"),from("Pista °C","track")],opts)),
      add(panel("Chuva registrada"),lineChart("Precipitação detectada",[from("Sensor","rain")],
        {...opts,ymin:0,ymax:1,yLabel:n=>n===0?"Não":n===1?"Sim":""}))),
    add(element("div", null, "columns"),
      add(panel("Vento"),lineChart("Velocidade do vento",[from("Vento m/s","wind")],opts)),
      add(panel("Umidade"),lineChart("Umidade relativa",[from("Umidade %","humidity")],opts))),
    add(panel("Amostras meteorológicas"), note("Horário de São Paulo. A OpenF1 mede chuva e temperatura, mas não fornece insolação ou cobertura de nuvens."),
      details("Ver leituras de chuva, vento, direção e pressão",
        table(["Horário","Volta","Chuva","Ar","Pista","Vento","Direção","Umidade","Pressão"],points.map(p=>[
          clockTime(p.date),p.lap,p.rain===1?"Sim":p.rain===0?"Não":"—",num(p.air," °C"),num(p.track," °C"),
          num(p.wind," m/s"),num(p.direction,"°"),num(p.humidity,"%"),num(p.pressure," mbar")]))))) :
    note("A fonte carregada não contém medições meteorológicas.");
  return add(element("div", null, "stack"),
    add(panel("Aderência estimada"),strip(),note("Chuva no sensor é diferente de pista molhada. A faixa também usa pneus do pelotão e mensagens de aderência.")),data);
}

async function telemetry(token, number) {
  const laps = driver.laps.filter(row => row.time && row.time < 200);
  const shell = panel("Telemetria de "+driver.name, "DADOS DO CARRO");
  const label = element("label", "Volta observada");
  const select = element("select");
  select.id = "telemetry-lap";
  setOptions(select,laps.map(r=>[r.n,"Volta "+r.n+" · "+lapTime(r.time)]),number ?? driver.best?.n);
  select.onchange = () => openTab("telemetry", Number(select.value));
  const loading = note("Consultando a volta na OpenF1…");
  shell.append(add(label,select),loading);
  el("view").replaceChildren(shell);
  if (!race.telemetry || !select.value) {
    select.disabled = true;
    loading.textContent = race.telemetry ? "Sem volta cronometrada." : "A fonte carregada para esta corrida não inclui telemetria.";
    return;
  }
  const parameters = {...eventQuery(), lap:select.value};
  const key = JSON.stringify(parameters);
  try {
    const result = stored.get(key) || await api("/api/telemetry",parameters);
    if (!result.reason && (result.car.length || result.map.length)) stored.set(key,result);
    if (token !== revision) return;
    loading.textContent = result.reason || (result.car.length ? result.car.length+" amostras · V"+result.lap : "Sem amostras do carro nesta volta.");
    const from = (name, field) => ({name, points:result.car.map(row=>[row.t,row[field]])});
    const opts = {xLabel:n=>Math.round(n)+" s"};
    const map = add(panel("Traçado aproximado"),add(element("div",null,"map"),trackMap(result.map)));
    el("view").replaceChildren(add(element("div",null,"stack"),shell,
      add(element("div",null,"columns"),add(panel("Velocidade"),lineChart("Velocidade do carro",[from("km/h","speed")],opts)),map),
      add(element("div",null,"columns"),
        add(panel("Acelerador e freio"),lineChart("Acelerador e freio",[from("Acelerador %","throttle"),from("Freio ativo","brake")],opts)),
        add(panel("RPM e marchas"),lineChart("RPM",[from("RPM","rpm")],opts),
          lineChart("Marcha",[from("Marcha","n_gear")],opts),lineChart("DRS",[from("Código DRS","drs")],opts)))));
  } catch (error) {
    if (token === revision) loading.textContent = error.message;
  }
}

function control() {
  const messages = add(panel("Mensagens da direção de prova"), note("Horário de São Paulo e volta conforme o registro da fonte."),
    race.messages.length ? table(["Hora","Volta","Categoria","Bandeira","Mensagem"],
      race.messages.map(row=>[clockTime(row.date),row.lap,row.category,row.flag,row.message]),-1,4) :
      note("Sem mensagens na fonte carregada."));
  const changes = add(panel("Trocas de posição registradas"), note("A fonte inclui trocas em pista e mudanças de ordem causadas por boxes ou punições."),
    (race.overtakes || []).length ? details("Ver "+(race.overtakes || []).length+" registros",
      table(["Hora","Volta","Ganhou a posição","Perdeu a posição","Pos."],
        race.overtakes.map(row=>[clockTime(row.date),row.lap,code(row.ahead),code(row.behind),row.position]))) :
      note("Sem registros desta fonte."));
  const radios = add(panel("Rádios publicados"), note("A disponibilidade depende dos clipes divulgados pela fonte."));
  if ((race.radio || []).length) {
    const rows = race.radio.map(row => {
      const audio = element("a","Ouvir clipe");
      if (row.url?.startsWith("https://livetiming.formula1.com/")) {
        audio.href = row.url;
        audio.target = "_blank";
        audio.rel = "noreferrer";
      }
      return [clockTime(row.date),code(row.driver),audio];
    });
    radios.append(details("Ver "+rows.length+" clipes",table(["Hora","Piloto","Áudio"],rows)));
  } else radios.append(note("Sem clipes disponíveis nesta corrida."));
  return add(element("div",null,"stack"),changes,radios,messages);
}

function chance(value) { return value == null ? "Amostra baixa" : value === 100 ? ">99%" : value === 0 ? "<1%" : value+"%"; }
function delta(value) { return element("span", (value>0?"+":"")+gap(value), value>0?"gain":value<0?"loss":""); }
function windowPanel(window) {
  const node = panel("Parada real na volta "+window.lap, "OPORTUNIDADE DE ESTRATÉGIA");
  const move = add(element("div",null,"window-head"),
    add(element("div"),tyre(window.before),document.createTextNode(" → "),tyre(window.actual)),
    element("span","Pit lane "+gap(window.lane)+" · Janela V"+window.anchor+"–V"+window.through,"pill"));
  const best = window.alternatives.find(row=>row.chance!=null && row.gain>0 && row.chance>=60);
  const original = window.conditions.find(p=>p.lap===window.lap);
  node.append(move,element("p",best ? "Melhor alternativa com amostra · V"+best.lap+" · "+tyres[best.compound][0] :
    "A amostra não sustenta uma alternativa melhor.", "kicker"),
    note(window.neighbors.length+" rivais na janela · pista "+(tracks[original?.track] || "indeterminada").toLowerCase()+
      " estimada no início da volta da parada · vento "+num(original?.wind," m/s")+"."));
  if (window.alternatives.length) {
    const comparison = table(["Parar na","Pneu","Ganho vs. real","Faixa central 80%","Chance de ganhar tempo","Retorno do box","Chegada estimada","Chance de subir"],
      window.alternatives.map(row=>["V"+row.lap,tyre(row.compound),delta(row.gain),
        row.band ? gap(row.band[0])+" a "+gap(row.band[1]) : "—",chance(row.chance),
        row.rejoin ? "P"+row.rejoin[0]+(row.rejoin[1]!==row.rejoin[0]?"–P"+row.rejoin[1]:"") : "—",
        row.position != null ? "P"+row.baseline_position+" → P"+row.position : "—",
        row.position_chance == null ? "—" : chance(row.position_chance)]),
      best ? window.alternatives.indexOf(best) : -1);
    comparison.classList.add("analysis-table");
    node.append(comparison);
    if (best?.band[0] < 0) node.append(note("A faixa estimada inclui perda de tempo. O ganho é incerto."));
  }
  node.append(details("Ver pilotos próximos e condição volta a volta",
    table(["Pos.","Piloto","Ao líder","À frente","Pneu","Idade","Última parada","Ritmo recente"],
      window.neighbors.map(r=>[r.position,code(r.driver),gap(r.gap),gap(r.interval),
        tyre(r.compound),num(r.age," V"),r.last_stop?"V"+r.last_stop:"—",lapTime(r.recent)])),
    table(["Volta","Pista estimada","Chuva detectada","Pista °C","Vento"],
      window.conditions.map(p=>[p.lap,tracks[p.track],p.rain===1?"Sim":p.rain===0?"Não":"—",num(p.temperature," °C"),num(p.wind," m/s")]))));
  return node;
}
async function analysis(token) {
  const shell = add(panel("Análise de "+driver.name,"SIMULAÇÃO EM PYTHON"), note("Calculando a partir dos dados locais…"));
  el("view").replaceChildren(shell);
  const params = eventQuery();
  const key = "analysis:"+JSON.stringify(params);
  try {
    const result = stored.get(key) || await api("/api/analysis",params);
    stored.set(key,result);
    if (token !== revision) return;
    const method = add(panel("Análise de "+driver.name,"SIMULAÇÃO EM PYTHON"),
      note("A análise compara até duas voltas antes e duas depois de cada parada real. O modelo cruza ritmo, desgaste, clima, tempos de box e até cinco pilotos à frente e cinco atrás."),
      details("Como ler os percentuais",note(result.draws+" sorteios por alternativa com amostra suficiente. As frequências refletem o cenário em que os rivais mantêm a corrida observada e a troca muda uma parada por vez. A projeção de chegada compara pilotos na mesma volta final.")));
    const pick = result.windows.flatMap(window => window.alternatives.map(row => ({...row, actual:window.lap})))
      .filter(row => row.chance >= 60 && row.gain > 0).sort((a,b) => b.gain-a.gain)[0];
    if (pick) {
      const position = pick.position != null ? " · P"+pick.baseline_position+" → P"+pick.position : "";
      method.append(element("p","Maior ganho estimado · V"+pick.actual+" → V"+pick.lap+" · "+tyres[pick.compound][0]+
        " · "+gap(pick.gain)+position,"kicker"));
    }
    const blocks = result.windows.length ? result.windows.map(windowPanel) : [add(panel("Sem janela comparável"),note("Este piloto não teve uma parada com os dados necessários para a análise."))];
    if (result.excluded) method.append(note(result.excluded+" parada(s) sem janela comparável, por suspensão, fim da prova ou dados incompletos."));
    el("view").replaceChildren(add(element("div",null,"stack"),method,...blocks));
  } catch (error) {
    if (token === revision) shell.append(note(error.message));
  }
}
function openTab(name, telemetryLap) {
  if (!race || !driver) return;
  selectedTab = name;
  const token = ++revision;
  for (const button of tabButtons) {
    if (button.dataset.tab === name) button.setAttribute("aria-current","page");
    else button.removeAttribute("aria-current");
  }
  if (name === "telemetry") return telemetry(token,telemetryLap);
  if (name === "analysis") return analysis(token);
  const render = {overview,pace,pits,weather,control};
  el("view").replaceChildren(render[name]());
}
function selectDriver(number) {
  driver = person(Number(number));
  el("driver").value = driver.number;
  openTab(selectedTab);
}
tabButtons.forEach(button=>button.onclick=()=>openTab(button.dataset.tab));
el("reload").onclick=loadEvents;
el("event").onchange=loadRace;
el("driver").onchange=event=>selectDriver(event.target.value);
el("analyze").onclick=()=>openTab("analysis");
loadEvents();
