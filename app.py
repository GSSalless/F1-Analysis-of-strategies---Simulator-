"""Run the local replay dashboard with Python's standard library."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from dashboard import RaceFacts
from ingest import DATA, EVENTS
from race import Race
from review import RaceReview
from strategy import compare
from telemetry import load_lap

WEB = Path(__file__).resolve().parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css"), "/charts.js": ("charts.js", "text/javascript")}
CACHE = {}
CACHE_LOCK = Lock()


def load(event):
    path = DATA / f"{event}.json"
    with CACHE_LOCK:
        try:
            stamp = path.stat().st_mtime_ns
        except FileNotFoundError:
            return None
        if event not in CACHE or CACHE[event][0] != stamp:
            with path.open(encoding="utf-8") as source:
                race = Race(json.load(source))
                race.facts = RaceFacts(race)
                CACHE[event] = (stamp, race)
        return CACHE[event][1]


def overview():
    events = []
    for event, (title, *_) in EVENTS.items():
        race = load(event)
        if race:
            events.append(dict(available=True, **race.metadata()))
        else:
            events.append(dict(event=event, name=title, available=False))
    return events


def analyze(race, driver, lap, scenario, horizon, pit):
    if driver not in race.drivers:
        raise ValueError("Piloto indisponível.")
    if not 4 <= horizon <= 24 or scenario not in ("hold", "drying", "rain"):
        raise ValueError("Escolha um cenário válido e um horizonte entre 4 e 24 voltas.")
    if pit is not None:
        if not any(row["lap_number"] == pit for _, row in race.pits[driver]):
            raise ValueError("O piloto não tem parada registrada nessa volta.")
        lap = max(1, pit - 1)
    snap = race.snapshot(driver, lap)
    if snap is None:
        raise ValueError("Sem carimbo de tempo para esse piloto e volta.")
    actual_stop = next((row for _, row in race.pits[driver] if row["lap_number"] == pit), None)
    if actual_stop and actual_stop.get("suspension"):
        result = dict(reason="Parada registrada junto à suspensão. Tempo parado e troca sob bandeira vermelha exigem outro modelo.",
                      options=[], curves=[])
    else:
        result = compare(race, driver, snap, scenario, horizon, pit)
    if pit is not None:
        result["actual_pit"] = pit
        result["actual_compound"] = race.tyre(driver, pit + 1)[0]
        result["actual_stop"] = actual_stop
    return dict(snapshot=snap, strategy=result)


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json(self, result, status=200):
        self.send(status, json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), "application/json")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in STATIC:
            filename, content_type = STATIC[url.path]
            self.send(200, (WEB / filename).read_bytes(), content_type)
            return
        try:
            if url.path == "/api/events":
                self.json(overview())
                return
            if url.path not in ("/api/race", "/api/analysis", "/api/telemetry", "/api/replay", "/api/pits"):
                self.json({"error": "Rota inexistente."}, 404)
                return
            args = {key: values[-1] for key, values in parse_qs(url.query).items()}
            event = args.get("event")
            if event not in EVENTS:
                raise ValueError("Corrida inválida.")
            race = load(event)
            if race is None:
                self.json({"error": "Corrida aguardando importação."}, 404)
                return
            if url.path == "/api/race":
                self.json(race.facts.report())
                return
            driver = int(args.get("driver", 0))
            if url.path in ("/api/analysis", "/api/telemetry") and driver not in race.drivers:
                raise ValueError("Piloto indisponível.")
            if url.path == "/api/analysis":
                self.json(RaceReview(race.facts).report(driver))
                return
            if url.path == "/api/telemetry":
                self.json(load_lap(race, driver, int(args["lap"]) if "lap" in args else None))
                return
            if url.path == "/api/pits":
                if driver not in race.drivers:
                    raise ValueError("Piloto indisponível.")
                self.json([dict(lap=row["lap_number"], duration=row.get("lane_duration", row.get("pit_duration")),
                                suspension=bool(row.get("suspension")),
                                compound=race.tyre(driver, row["lap_number"] + 1)[0])
                           for _, row in race.pits[driver]])
                return
            pit = int(args["pit"]) if "pit" in args else None
            self.json(analyze(race, driver, int(args.get("lap", 1)), args.get("scenario", "hold"),
                              int(args.get("horizon", 12)), pit))
        except ValueError as exc:
            self.json({"error": str(exc)}, 400)
        except OSError as exc:
            self.log_error("%s", exc)
            self.json({"error": "Não foi possível ler o cache local."}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Replay local em http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
