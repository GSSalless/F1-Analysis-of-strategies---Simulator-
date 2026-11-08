const palette = ["#c9fd56", "#8ebdff", "#ff806f", "#e5a5ff", "#ffc875"];
const svgNS = "http://www.w3.org/2000/svg";
function svg(tag, attributes = {}, value) {
  const node = document.createElementNS(svgNS, tag);
  for (const [name, item] of Object.entries(attributes)) node.setAttribute(name, item);
  if (value != null) node.textContent = value;
  return node;
}

function lineChart(title, series, options = {}) {
  const active = series.filter(item => item.points.some(point => Number.isFinite(point[1])));
  const block = element("div", null, "chart");
  if (!active.length) {
    block.append(element("p", "Sem dados para este gráfico.", "muted"));
    return block;
  }
  const points = active.flatMap(item => item.points.filter(point => Number.isFinite(point[1])));
  const xs = points.map(point => point[0]);
  const ys = points.map(point => point[1]);
  const xmin = options.xmin ?? Math.min(...xs);
  const xmax = options.xmax ?? Math.max(...xs);
  const ymin = options.ymin ?? Math.min(...ys);
  const ymax = options.ymax ?? Math.max(...ys);
  const bounds = {left: 56, right: 700, top: 16, bottom: 217};
  const x = n => bounds.left + (n-xmin) / (xmax-xmin || 1) * (bounds.right-bounds.left);
  const y = n => bounds.bottom - (options.reverse ? (ymax-n) : (n-ymin)) /
    (ymax-ymin || 1) * (bounds.bottom-bounds.top);
  const graph = svg("svg", {viewBox: "0 0 725 250", role: "img", "aria-label": title});
  for (let i = 0; i <= 4; i++) {
    const value = ymin + (ymax-ymin)*i/4;
    const yy = y(value);
    graph.append(svg("line", {x1: bounds.left, x2: bounds.right, y1: yy, y2: yy, class: "chart-grid"}),
      svg("text", {x: bounds.left-9, y: yy+4, "text-anchor": "end", class: "chart-label"},
        options.yLabel ? options.yLabel(value) : compact.format(value)));
  }
  for (let i = 0; i <= 5; i++) {
    const value = xmin+(xmax-xmin)*i/5;
    graph.append(svg("text", {x: x(value), y: 239, "text-anchor": "middle", class: "chart-label"},
      options.xLabel ? options.xLabel(value) : String(Math.round(value))));
  }
  for (const marker of options.markers || []) {
    if (marker < xmin || marker > xmax) continue;
    graph.append(svg("line", {x1: x(marker), x2: x(marker), y1: bounds.top, y2: bounds.bottom,
      stroke: "#a3afb9", opacity: ".42", "stroke-dasharray": "4 4"}));
  }
  active.forEach((item, index) => {
    const color = item.color || palette[index % palette.length];
    let path = "";
    let connected = false;
    for (const [key, value] of item.points) {
      if (!Number.isFinite(value)) { connected = false; continue; }
      path += (connected ? "L" : "M") + x(key).toFixed(2) + " " + y(value).toFixed(2) + " ";
      connected = true;
    }
    graph.append(svg("path", {d: path, fill: "none", stroke: color, "stroke-width": 2.2,
      "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke"}));
    if (points.length < 340) {
      for (const [key, value] of item.points) {
        if (!Number.isFinite(value)) continue;
        const dot = svg("circle", {cx: x(key), cy: y(value), r: 2.7, fill: color});
        dot.append(svg("title", {}, item.name + " · " + (options.xLabel?.(key) || key) + " · " +
          (options.yLabel?.(value) || compact.format(value))));
        graph.append(dot);
      }
    }
  });
  const legend = element("div", null, "legend");
  active.forEach((item, index) => {
    const key = element("span", item.name);
    key.style.setProperty("--key", item.color || palette[index % palette.length]);
    legend.append(key);
  });
  block.append(graph, legend);
  return block;
}

function trackMap(points) {
  if (!points.length) return element("p", "Traçado desta volta indisponível.", "muted");
  const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const scale = Math.min(350/(xmax-xmin || 1), 230/(ymax-ymin || 1));
  const dx = (400-(xmax-xmin)*scale)/2, dy = (270-(ymax-ymin)*scale)/2;
  const coords = points.map(([x,y]) => [dx+(x-xmin)*scale, 270-dy-(y-ymin)*scale]);
  const track = svg("svg", {viewBox: "0 0 400 270", role: "img", "aria-label": "Traçado aproximado da volta"});
  const path = coords.map(([x,y]) => x.toFixed(1)+","+y.toFixed(1)).join(" ");
  for (const [color, width] of [["#334738", 12], ["#c9fd56", 3]]) {
    track.append(svg("polyline", {points: path, stroke: color, "stroke-width": width, fill: "none",
      "stroke-linejoin": "round", "stroke-linecap": "round"}));
  }
  track.append(svg("circle", {cx: coords[0][0], cy: coords[0][1], r: 5, fill: "#fff"}));
  return track;
}
