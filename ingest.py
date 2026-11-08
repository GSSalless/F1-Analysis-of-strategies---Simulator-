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
    for row in info["Results"]:
        driver = row["Driver"]
        number = int(row["number"])
        numbers[driver["driverId"]] = number
        drivers.append(dict(driver_number=number, name_acronym=driver.get("code"),
                            full_name=f'{driver["givenName"]} {driver["familyName"]}',
                            team_name=row["Constructor"]["name"]))
        if int(row["grid"]) > 0:
            grid.append(dict(driver_number=number, position=int(row["grid"])))

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
                drivers=drivers, starting_grid=grid, laps=lap_rows, pit=pits)
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
    args = parser.parse_args()
    if args.source == "jolpica" and (DATA / f"{args.event}.json").is_file():
        existing = json.loads((DATA / f"{args.event}.json").read_text(encoding="utf-8"))
        if existing.get("source") == "OpenF1":
            parser.exit(1, "O cache completo da OpenF1 já existe. Importação parcial ignorada.\n")
    try:
        race = (openf1 if args.source == "openf1" else jolpica)(args.event)
        save(args.event, race)
    except (ImportFailure, KeyError, ValueError, IndexError) as exc:
        parser.exit(1, f"Importação indisponível: {exc}\n")
    print(f'{race["name"]}: {race["actual_laps"]} voltas, {race["source"]} → {DATA / (args.event + ".json")}')


if __name__ == "__main__":
    main()
