"""Mexico 2026 fallback annotations from Pirelli's published stint chart and FIA timing."""
from datetime import datetime, timezone

PIRELLI = "https://press.pirelli.com/the-champions-podium-verstappen-wins-in-mexico-as-kimi-secures-the-title/"
FIA = "https://www.fia.com/events/fia-formula-one-world-championship/season-2026/mexico-city-grand-prix/event-timing"
# (last lap on set, compound); lowercase means used, with prior mileage unpublished.
SETS = {
    "VER": [(27, "M"), (45, "S"), (71, "s")],
    "HAM": [(28, "s"), (44, "M"), (45, "S"), (71, "s")],
    "ANT": [(43, "S"), (45, "M"), (71, "s")],
    "LEC": [(27, "S"), (45, "M"), (71, "s")],
    "NOR": [(39, "S"), (45, "M"), (71, "s")],
    "RUS": [(33, "s"), (44, "M"), (45, "S"), (71, "s")],
    "PIA": [(26, "S"), (45, "M"), (71, "S")],
    "COL": [(34, "M"), (45, "S"), (71, "s")],
    "LAW": [(11, "M"), (42, "s"), (44, "S"), (71, "s")],
    "GAS": [(17, "S"), (44, "M"), (45, "S"), (71, "s")],
    "BOR": [(38, "M"), (45, "S"), (71, "s")],
    "HAD": [(7, "s"), (41, "M"), (45, "s"), (71, "s")],
    "HIR": [(35, "M"), (43, "S"), (44, "s"), (59, "s"), (71, "s")],
    "ALB": [(18, "S"), (41, "S"), (44, "M"), (71, "s")],
    "SAI": [(36, "S"), (44, "M"), (71, "S")],
    "HUL": [(31, "M"), (45, "S"), (59, "s"), (71, "s")],
    "PER": [(30, "S"), (43, "M"), (59, "S"), (71, "s")],
    "LIN": [(35, "S"), (45, "M"), (58, "s")],
    "BEA": [(40, "S"), (45, "M"), (47, "s")],
    "BOT": [(30, "S"), (42, "M")],
    "STR": [(3, "S"), (5, "S")],
    "ALO": [(3, "S"), (5, "S")],
}


def utc(clock):
    return datetime.fromisoformat(f"2026-11-01T{clock}-06:00").astimezone(timezone.utc).isoformat()


def enrich(race):
    # Race control timestamps are published at minute resolution. First crossing
    # and Jolpica's lap 1 time anchor the race clock to approximately 14:03:25.
    race["session"]["date_start"] = utc("14:03:25")
    race["weather_assumption"] = "dry"
    race["provenance"] = [
        dict(name="Jolpica F1 · voltas, grid e pit lane", url="https://api.jolpi.ca/ergast/f1/2026/19/results/"),
        dict(name="Pirelli · compostos e sets", url=PIRELLI),
        dict(name="FIA · cronometragem e controle de corrida", url=FIA),
    ]
    race["race_control"] = [
        dict(date=utc(clock), state=state, message=label)
        for clock, state, label in (
            ("14:03:25", "green", "Largada"),
            ("14:12:00", "vsc", "VSC acionado"),
            ("14:14:00", "green", "Fim do VSC"),
            ("15:04:00", "sc", "Safety car acionado"),
            ("15:06:00", "red", "Corrida suspensa"),
            ("15:45:00", "sc", "Retomada atrás do safety car"),
            ("15:48:00", "green", "Relargada"),
            ("16:05:00", "sc", "Safety car acionado"),
            ("16:12:00", "green", "Fim do safety car"),
        )
    ]
    race["stints"] = []
    for driver in race["drivers"]:
        sets = SETS[driver["name_acronym"]]
        first = 1
        for i, (last, compound) in enumerate(sets, 1):
            race["stints"].append(dict(driver_number=driver["driver_number"], stint_number=i,
                                       lap_start=first, lap_end=last,
                                       compound={"S": "SOFT", "M": "MEDIUM"}[compound.upper()],
                                       tyre_age_at_start=0 if compound.isupper() else None))
            first = last + 1
    for pit in race["pit"]:
        pit["date"] = utc(pit.pop("local_time"))
        if pit["lane_duration"] > 45 and pit["lap_number"] in (44, 45):
            pit["suspension"] = True
