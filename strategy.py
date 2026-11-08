"""Causal tyre curves and pit timing scenarios. All time costs are in seconds."""
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from statistics import median

from race import COMPOUNDS, SLICKS, numeric

REGIMES = ("dry", "damp", "wet")
FUEL_GAIN = 0.045
# Engineering assumptions for the prototype. The model shrinks toward these with sparse data.
DEG = dict(SOFT=0.090, MEDIUM=0.060, HARD=0.041, INTERMEDIATE=0.065, WET=0.053)
PACE = {
    "dry": dict(SOFT=0.0, MEDIUM=0.35, HARD=0.85, INTERMEDIATE=5.5, WET=10.0),
    "damp": dict(SOFT=2.5, MEDIUM=3.0, HARD=4.0, INTERMEDIATE=0.0, WET=4.5),
    "wet": dict(SOFT=17.0, MEDIUM=18.0, HARD=20.0, INTERMEDIATE=1.4, WET=0.0),
}
DEFAULT_PIT = dict(interlagos=20.5, mexico=21.0)


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Curve:
    compound: str
    track: str
    wear: float
    observations: int
    stints: int
    fit: str
    offset: float
    paired_drivers: int


@dataclass(frozen=True)
class Sample:
    driver: int
    stint: int
    age: int
    lap: int
    time: float

    @property
    def fuel_adjusted(self):
        return self.time + FUEL_GAIN * self.lap


def observations(race, at):
    samples = defaultdict(list)
    for driver, laps in race.laps.items():
        pit_laps = {row["lap_number"] for _, row in race.past_stops(driver, at)}
        for lap in laps.values():
            if not race.clean(lap, at, pit_laps):
                continue
            compound, age, stint = race.tyre(driver, lap.number)
            if compound is None:
                continue
            track, _ = race.track_at(lap.start)
            end_track, _ = race.track_at(lap.end)
            if track not in REGIMES or end_track != track:
                continue
            age = age if age is not None else lap.number - stint
            if age >= 1:
                samples[track, compound].append(Sample(driver, stint, age, lap.number, lap.duration))
    return samples


def fit_curves(samples):
    curves = {}
    for track in REGIMES:
        intercepts = {}
        for compound in COMPOUNDS:
            rows = samples[track, compound]
            groups = defaultdict(list)
            for row in rows:
                groups[row.driver, row.stint].append(row)
            slopes = []
            for stint in groups.values():
                if len(stint) < 4:
                    continue
                pairs = [(b.fuel_adjusted - a.fuel_adjusted) / (b.age - a.age)
                         for a, b in combinations(sorted(stint, key=lambda row: row.age), 2)
                         if b.age - a.age >= 3]
                if pairs:
                    slopes.append(median(pairs))
            prior = DEG[compound] + (0.10 if track == "dry" and compound in ("INTERMEDIATE", "WET") else 0)
            fitted = clamp(median(slopes), 0.0, 0.45) if slopes else prior
            weight = min(0.90, len(slopes) / (len(slopes) + 3))
            wear = prior * (1 - weight) + fitted * weight
            curves[track, compound] = Curve(compound, track, wear, len(rows), len(slopes),
                                            "mixed" if slopes else "prior", PACE[track][compound], 0)
            by_driver = defaultdict(list)
            for row in rows:
                by_driver[row.driver].append(row.fuel_adjusted - wear * row.age)
            intercepts[compound] = {driver: median(values) for driver, values in by_driver.items()
                                     if len(values) >= 3}

        reference = min(COMPOUNDS, key=PACE[track].get)
        for compound in COMPOUNDS:
            if compound == reference:
                continue
            pairs = [value - intercepts[reference][driver]
                     for driver, value in intercepts[compound].items() if driver in intercepts[reference]]
            if pairs:
                old = curves[track, compound]
                weight = min(0.75, len(pairs) / (len(pairs) + 4))
                offset = old.offset * (1 - weight) + clamp(median(pairs), -3, 24) * weight
                curves[track, compound] = Curve(old.compound, old.track, old.wear, old.observations,
                                                old.stints, old.fit, offset, len(pairs))
    return curves


def pit_loss(race, at):
    measured = []
    for driver in race.drivers:
        for stamp, row in race.past_stops(driver, at):
            lane = numeric(row.get("lane_duration", row.get("pit_duration")))
            if lane is not None and 15 <= lane <= 38 and race.control.latest(stamp) == "green":
                measured.append(lane)
    # Time in lane includes the stop. Subtract an estimate of time on the bypassed track.
    return (clamp(median(measured) - 3.0, 14, 29) if measured else DEFAULT_PIT[race.data["event"]],
            len(measured))


def rejoin(snapshot, driver, loss):
    own = next((row for row in snapshot["board"] if row["driver"] == driver), None)
    gap = numeric(own["gap"]) if own else None
    if gap is None or snapshot["control"] != "green":
        return None, None
    field = [row for row in snapshot["board"] if row["active"] and row["position"] > own["position"]
             and own["completed"] - row["completed"] < 2]
    deltas = [value - gap for row in field if (value := numeric(row["gap"])) is not None and value > gap]
    passed = [delta for delta in deltas if delta < loss]
    nearby = min([loss] + [loss - delta for delta in passed])
    traffic = max(0, 1.6 - nearby) * 1.3
    if not deltas and field:
        return None, None
    known = own["position"] + len(passed)
    return [known, known + len(field) - len(deltas)], traffic


def forecast(track, scenario, step):
    index = REGIMES.index(track)
    steps = step // 2
    if scenario == "drying":
        index = max(0, index - steps)
    elif scenario == "rain":
        index = min(2, index + steps)
    return REGIMES[index]


def running_cost(curve, age, variant):
    wear = curve.wear * variant
    cliff_start = 25 if curve.compound == "SOFT" else 35
    cliff = 0.0018 * max(0, age - cliff_start) ** 2
    return curve.offset + wear * age + cliff


def compare(race, driver, snapshot, scenario="hold", horizon=12, actual_pit=None):
    start = snapshot["lap"]
    at = race.laps[driver][start].start
    retrospective = actual_pit is not None
    if snapshot["compound"] is None:
        return dict(reason="Sem registro de composto neste ponto.", options=[], curves=[])
    if snapshot["track"] not in REGIMES:
        return dict(reason="Sem informação suficiente de chuva neste ponto.", options=[], curves=[])
    if snapshot["control"] in ("red", "closed") and not retrospective:
        return dict(reason="Corrida suspensa ou boxes fechados neste ponto.", options=[], curves=[])

    number_of_laps = race.data["scheduled_laps"] if not retrospective else max(race.laps[driver])
    end = min(number_of_laps, start + horizon - 1)
    current = snapshot["compound"]
    current_age = snapshot["age"] if snapshot["age"] is not None else start - snapshot["stint_start"]
    pit_cost, pit_samples = pit_loss(race, at)
    curves = fit_curves(observations(race, at))
    conditions = []
    for n in range(start, end + 1):
        if retrospective and n in race.laps[driver]:
            lap = race.laps[driver][n]
            condition, _ = race.track_at(lap.start)
            if race.control.latest(lap.start) == "red" or any(
                    state == "red" for _, state in race.control.between(lap.start, lap.end if lap.duration else lap.start)):
                break
            pit_at = lap.end - 2 if lap.duration else lap.start
            conditions.append((condition, race.control.latest(max(lap.start, pit_at))))
        else:
            state = snapshot["control"] if n == start else "green"
            conditions.append((forecast(snapshot["track"], scenario, n - start), state))
    end = start + len(conditions) - 1
    if retrospective and actual_pit >= end:
        return dict(reason="A janela termina na suspensão, no fim da corrida ou sem volta útil após a parada.",
                    options=[], curves=[])
    if any(track not in REGIMES for track, _ in conditions):
        return dict(reason="A janela retrospectiva tem lacunas nos dados de chuva.", options=[], curves=[])

    def score(stop, compound, wear_factor, pit_error):
        total = 0.0
        exit_position = None
        traffic = None
        for n, (track, state) in enumerate(conditions, start):
            if stop is None or n <= stop:
                total += running_cost(curves[track, current], current_age + n - start, wear_factor)
            else:
                total += running_cost(curves[track, compound], n - stop - 1, wear_factor)
            if n == stop:
                factor = {"green": 1.0, "vsc": 0.73, "sc": 0.62}[state]
                loss = (pit_cost + pit_error) * factor
                # Keep rival estimates fixed at the decision time across alternatives.
                if state == "green":
                    exit_position, traffic = rejoin(snapshot, driver, loss)
                warmup = 1.3 if compound in SLICKS else 0.7
                total += loss + warmup + (traffic or 0.0)
        return total, exit_position, traffic

    central = (1.0, 0.0)
    variants = [central] + [(wear, loss) for wear in (0.70, 1.30) for loss in (-1.5, 1.5)]
    baseline = {v: score(None, current, *v)[0] for v in variants}
    options = [dict(stop=None, compound=current, delta=0.0, low=0.0, high=0.0, rejoin=None, traffic=None)]
    candidates = (actual_pit - 1, actual_pit, actual_pit + 1) if retrospective else range(start, start + 3)
    for stop in candidates:
        if not start <= stop < end:
            continue
        if conditions[stop - start][1] in ("red", "closed"):
            continue
        next_track = conditions[stop - start + 1][0]
        compounds = COMPOUNDS if next_track == "damp" else SLICKS if next_track == "dry" else ("INTERMEDIATE", "WET")
        actual_compound = race.tyre(driver, actual_pit + 1)[0] if retrospective else None
        if actual_compound and actual_compound not in compounds:
            compounds = compounds + (actual_compound,)
        for compound in compounds:
            results = {v: score(stop, compound, *v) for v in variants}
            deltas = {variant: baseline[variant] - results[variant][0] for variant in variants}
            _, position, traffic = results[central]
            options.append(dict(stop=stop, compound=compound, delta=round(deltas[central], 2),
                                low=round(min(deltas.values()), 2), high=round(max(deltas.values()), 2),
                                rejoin=position, traffic=round(traffic, 2) if traffic is not None else None,
                                actual=retrospective and stop == actual_pit and compound == actual_compound))
    options.sort(key=lambda row: -row["delta"])
    current_curves = [asdict(curves[snapshot["track"], compound]) for compound in COMPOUNDS]
    return dict(options=options, curves=current_curves, horizon=end - start + 1, through=end,
                pit_loss=round(pit_cost, 2), pit_samples=pit_samples, retrospective=retrospective,
                track_path=[track for track, _ in conditions],
                age_estimated=snapshot["age"] is None,
                controls=[state for _, state in conditions])
