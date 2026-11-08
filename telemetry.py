"""Fetch a single lap from OpenF1 and keep it in a local cache."""
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

from ingest import DATA, ImportFailure, fetch
from race import iso, timestamp

BASE = "https://api.openf1.org/v1/"


def load_lap(race, driver, number):
    laps = race.laps.get(driver, {})
    if not laps:
        raise ValueError("Sem voltas para esse piloto.")
    if number is None:
        best = min((lap for lap in laps.values() if lap.duration),
                   key=lambda lap: lap.duration, default=None)
    else:
        best = laps.get(number)
    if not best or not best.duration:
        raise ValueError("Volta sem cronometragem.")
    if not race.native:
        return dict(lap=best.number, car=[], map=[], reason="Importe esta corrida da OpenF1 para consultar telemetria.")
    key = race.data["session"]["session_key"]
    file = DATA / "telemetry" / str(key) / f"{driver}-{best.number}.json"
    if file.is_file():
        return json.loads(file.read_text(encoding="utf-8"))
    if best.duration > 200 or best.end - best.start > 210:
        return dict(lap=best.number, car=[], map=[], reason="A volta contém uma interrupção longa.")
    filters = {"session_key": key, "driver_number": driver,
               "date>": iso(best.start), "date<": iso(best.end)}

    def field(name):
        try:
            return fetch(BASE, name, missing_ok=True, **filters), None
        except (ImportFailure, TimeoutError) as exc:
            return [], str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        car_future = pool.submit(field, "car_data")
        location_future = pool.submit(field, "location")
        car, car_error = car_future.result()
        locations, location_error = location_future.result()
    car_fields = ("speed", "throttle", "brake", "n_gear", "rpm", "drs")
    result = dict(lap=best.number, duration=best.duration,
                  car=[dict(t=round(timestamp(row["date"])-best.start, 3),
                            **{field: row.get(field) for field in car_fields}) for row in car],
                  map=[[row.get("x"), row.get("y")] for row in locations
                       if row.get("x") is not None and row.get("y") is not None],
                  reason=car_error or location_error)
    if car and not result["reason"]:
        file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=file.parent, delete=False) as out:
            try:
                json.dump(result, out, ensure_ascii=False, separators=(",", ":"))
                out.close()
                os.replace(out.name, file)
            finally:
                from pathlib import Path
                Path(out.name).unlink(missing_ok=True)
    return result
