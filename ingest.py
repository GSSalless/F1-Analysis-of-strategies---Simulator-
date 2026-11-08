"""Download completed races into the local, shared replay format."""
import argparse
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import mexico_context

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
EVENTS = {
    "interlagos": ("GP de São Paulo 2026", "BRA", 20, 71),
    "mexico": ("GP da Cidade do México 2026", "MEX", 19, 71),
}
ENDPOINTS = ("drivers", "starting_grid", "laps", "stints", "pit",
             "weather", "position", "intervals", "race_control")


class ImportFailure(Exception):
    pass


def fetch(base, path, *, missing_ok=False, **params):
    url = base + path + ("?" + urlencode(params) if params else "")
    request = Request(url, headers={"User-Agent": "InterlagosStrategyLab/0.1", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return []
            if exc.code in (401, 403) and "openf1" in base:
                raise ImportFailure("OpenF1 restrita no momento. Tente após a janela de 30 minutos da sessão ao vivo.") from exc
            if exc.code != 429 and exc.code < 500:
                raise ImportFailure(f"{path}: HTTP {exc.code}") from exc
            retry = exc.headers.get("Retry-After", "")
            delay = min(int(retry), 30) if retry.isdigit() else 2 ** (attempt + 1)
        except URLError as exc:
            delay = 2 ** (attempt + 1)
        if attempt < 2:
            time.sleep(delay)
    raise ImportFailure(f"{path}: serviço indisponível após três tentativas.")


def openf1(event):
    title, country, _, scheduled = EVENTS[event]
    base = "https://api.openf1.org/v1/"
    sessions = fetch(base, "sessions", year=2026, country_code=country, session_name="Race")
    active = [row for row in sessions if not row.get("is_cancelled")]
    if len(active) != 1:
        raise ImportFailure("A sessão da corrida ainda não está identificada de forma inequívoca.")
    session = active[0]
    key = session["session_key"]
    results = fetch(base, "session_result", session_key=key)
    winner = next((row for row in results if row.get("position") == 1), {})
    actual = winner.get("number_of_laps") or 0
    if not actual:
        raise ImportFailure("A classificação final ainda não está disponível.")
    race = dict(name=title, event=event, source="OpenF1", scheduled_laps=scheduled,
                actual_laps=actual, session=session, session_result=results,
                provenance=[dict(name="OpenF1 · documentação dos dados", url="https://openf1.org/docs/")])
    for endpoint in ENDPOINTS:
        time.sleep(0.4)
        race[endpoint] = fetch(base, endpoint, session_key=key, missing_ok=endpoint == "starting_grid")
        print(f"  {endpoint}: {len(race[endpoint])} registros", flush=True)
    winner_laps = {row["lap_number"] for row in race["laps"]
                   if row["driver_number"] == winner.get("driver_number") and row.get("lap_duration")}
    if len(winner_laps) < max(2, actual - 1) or not race["drivers"] or not race["stints"]:
        raise ImportFailure("Voltas, pilotos ou stints ainda estão incompletos. Cache anterior preservado.")
    return enrich(race)


def enrich(race):
    """Add small optional datasets to an existing OpenF1 cache."""
    if race["source"] != "OpenF1":
        raise ImportFailure("Os dados extras exigem uma corrida importada da OpenF1.")
    key = race["session"]["session_key"]
    for endpoint in ("overtakes", "team_radio"):
        try:
            race[endpoint] = fetch("https://api.openf1.org/v1/", endpoint, missing_ok=True, session_key=key)
        except (ImportFailure, TimeoutError) as exc:
            print(f"  {endpoint}: {exc}", flush=True)
    if not race.get("starting_grid"):
        _, _, round_number, _ = EVENTS[race["event"]]
        base = f"https://api.jolpi.ca/ergast/f1/2026/{round_number}/"
        try:
            records = fetch(base, "results/")["MRData"]["RaceTable"]["Races"]
            if records:
                race["starting_grid"] = [dict(driver_number=int(row["number"]), position=int(row["grid"]))
                                         for row in records[0]["Results"]
                                         if row.get("number") is not None and row.get("grid") is not None]
                if race["starting_grid"]:
                    source = dict(name="Jolpica · grid", url=base + "results/")
                    if source not in race.setdefault("provenance", []):
                        race["provenance"].append(source)
        except (ImportFailure, TimeoutError, KeyError, ValueError) as exc:
            print(f"  Grid alternativo indisponível: {exc}", flush=True)
    if not race.get("starting_grid") and race["event"] == "interlagos":
        grid = (1, 12, 30, 27, 6, 87, 63, 14, 23, 81, 51, 55, 43, 16, 10, 18, 77, 41, 5, 44, 3, 11)
        race["starting_grid"] = [dict(driver_number=number, position=pos) for pos, number in enumerate(grid, 1)]
        race["provenance"] = [row for row in race.get("provenance", []) if row["name"] != "Jolpica · grid"]
        race["provenance"].append(dict(name="F1 · grid oficial",
                                       url="https://www.formula1.com/en/results/2026/races/1299/brazil/starting-grid"))
    return race


def seconds(value):
    total = 0.0
    for piece in value.split(":"):
        total = total * 60 + float(piece)
    return total


def jolpica(event):
    title, _, rnd, scheduled = EVENTS[event]
    base = f"https://api.jolpi.ca/ergast/f1/2026/{rnd}/"
    results = fetch(base, "results/")["MRData"]["RaceTable"]["Races"]
    if not results or not results[0]["Results"]:
        raise ImportFailure("Jolpica ainda não publicou o resultado da corrida.")
    info = results[0]
    drivers, grid, numbers = [], [], {}
    classification = []
    for row in info["Results"]:
        driver = row["Driver"]
        number = int(row["number"])
        numbers[driver["driverId"]] = number
        drivers.append(dict(driver_number=number, name_acronym=driver.get("code"),
                            full_name=f'{driver["givenName"]} {driver["familyName"]}',
                            team_name=row["Constructor"]["name"]))
        if row.get("grid") is not None:
            grid.append(dict(driver_number=number, position=int(row["grid"])))
        status = row.get("status") or ""
        elapsed = (row.get("Time") or {}).get("millis")
        difference = (row.get("Time") or {}).get("time")
        if difference and difference.startswith("+"):
            difference = seconds(difference[1:])
        classification.append(dict(driver_number=number, position=int(row["position"]),
                                   number_of_laps=int(row["laps"]), points=float(row["points"]),
                                   duration=int(elapsed)/1000 if elapsed else None,
                                   gap_to_leader=0 if row["position"] == "1" else
                                   difference if isinstance(difference, float) else
                                   status if status.startswith("+") else None,
                                   dnf=not (status == "Finished" or status.startswith("+")) and row.get("positionText") not in ("D", "W"),
                                   dsq=row.get("positionText") == "D", dns=row.get("positionText") == "W"))

    lap_rows = []
    offset = 0
    while True:
        page = fetch(base, "laps/", limit=100, offset=offset)["MRData"]
        for lap in page["RaceTable"]["Races"][0]["Laps"] if page["RaceTable"]["Races"] else []:
            for row in lap["Timings"]:
                lap_rows.append(dict(driver_number=numbers[row["driverId"]],
                                     lap_number=int(lap["number"]), lap_duration=seconds(row["time"]),
                                     position=int(row["position"])))
        offset += int(page["limit"])
        if offset >= int(page["total"]):
            break
        time.sleep(0.28)
    actual = int(info["Results"][0]["laps"])
    if not lap_rows or max(row["lap_number"] for row in lap_rows) < actual:
        raise ImportFailure("Jolpica ainda não publicou todas as voltas.")

    pit_data = fetch(base, "pitstops/", limit=100)["MRData"]["RaceTable"]["Races"]
    pits = [dict(driver_number=numbers[row["driverId"]], lap_number=int(row["lap"]),
                 lane_duration=seconds(row["duration"]), local_time=row["time"])
            for row in (pit_data[0]["PitStops"] if pit_data else [])]
    race = dict(name=title, event=event, source="Jolpica F1", scheduled_laps=scheduled,
                actual_laps=actual, session=dict(date_start=f'{info["date"]}T{info["time"]}'),
                drivers=drivers, starting_grid=grid, laps=lap_rows, pit=pits, session_result=classification)
    if event == "mexico":
        mexico_context.enrich(race)
    return race


def save(event, race):
    DATA.mkdir(exist_ok=True)
    race["imported_at"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA,
                                     suffix=".tmp", delete=False) as output:
        temp = Path(output.name)
        try:
            json.dump(race, output, ensure_ascii=False, separators=(",", ":"))
            output.close()
            os.replace(temp, DATA / f"{event}.json")
        finally:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event", choices=EVENTS)
    parser.add_argument("--source", choices=("openf1", "jolpica"), default="openf1")
    parser.add_argument("--extras", action="store_true", help="Atualizar grid, trocas de posição e rádios no cache.")
    args = parser.parse_args()
    if args.source == "jolpica" and (DATA / f"{args.event}.json").is_file():
        existing = json.loads((DATA / f"{args.event}.json").read_text(encoding="utf-8"))
        if existing.get("source") == "OpenF1":
            parser.exit(1, "O cache completo da OpenF1 já existe. Importação parcial ignorada.\n")
    try:
        if args.extras:
            source = DATA / f"{args.event}.json"
            if not source.exists():
                raise ImportFailure("Importe a corrida antes de atualizar os dados extras.")
            race = enrich(json.loads(source.read_text(encoding="utf-8")))
        else:
            race = (openf1 if args.source == "openf1" else jolpica)(args.event)
        save(args.event, race)
    except (ImportFailure, KeyError, ValueError, IndexError, TypeError, TimeoutError) as exc:
        parser.exit(1, f"Importação indisponível: {exc}\n")
    print(f'{race["name"]}: {race["actual_laps"]} voltas, {race["source"]} → {DATA / (args.event + ".json")}')


if __name__ == "__main__":
    main()
