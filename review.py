"""Compare one pit decision at a time with observed race data and resampling."""
from collections import defaultdict
from functools import lru_cache
from math import sqrt
from random import Random
from statistics import median

from race import COMPOUNDS, SLICKS, numeric
from strategy import PACE, DEFAULT_PIT, Sample, clamp, fit_curves, rejoin

TRIALS = 500
WINDOW = 8


def quantile(values, fraction):
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


class RaceReview:
    def __init__(self, facts):
        self.facts = facts
        self.race = facts.race
        self.samples = defaultdict(list)
        self.losses = defaultdict(list)
        anchors = facts.starts
        wear_samples = defaultdict(list)
        observed = []
        for driver, laps in self.race.laps.items():
            pit_numbers = {pit["lap_number"] for _, pit in self.race.pits[driver]}
            for n, lap in laps.items():
                if not self.race.clean(lap, float("inf"), pit_numbers):
                    continue
                compound, age, first = self.race.tyre(driver, n)
                if not compound or n not in anchors:
                    continue
                condition = self.condition(n)
                if condition["track"] not in PACE:
                    continue
                age = age if age is not None else n-first
                key = condition["track"], compound
                wear_samples[key].append(Sample(driver, first, age, n, lap.duration))
                observed.append((key, n, driver, age, lap.duration, condition))
        self.curves = fit_curves(wear_samples)
        for key, n, driver, age, duration, condition in observed:
            adjusted = duration - self.curves[key].wear * age
            self.samples[key].append((n, driver, adjusted, condition))
        for stops in self.race.pits.values():
            for at, row in stops:
                lane = numeric(row.get("lane_duration", row.get("pit_duration")))
                state = self.race.control.latest(at)
                if lane is not None and 15 <= lane <= 38 and not row.get("suspension"):
                    self.losses[state].append(lane - 3.0)

    @lru_cache(maxsize=100)
    def condition(self, lap):
        return self.facts.condition(self.facts.starts[lap] + 25)

    def neighbors(self, driver, lap):
        snapshot = self.race.snapshot(driver, lap)
        if not snapshot:
            return []
        own = next((row for row in snapshot["board"] if row["driver"] == driver), None)
        if not own:
            return []
        position = own["position"]
        at = self.race.laps[driver][lap].start
        field = []
        for row in snapshot["board"]:
            if not row["active"] or not 0 < abs(row["position"] - position) <= 5:
                continue
            rival = row["driver"]
            in_progress = row["completed"] + 1
            compound, age, _ = self.race.tyre(rival, in_progress)
            stops = self.race.past_stops(rival, at)
            pit_laps = {p["lap_number"] for _, p in stops}
            recent = [entry.duration for n, entry in self.race.laps[rival].items()
                      if in_progress-6 <= n < in_progress and self.race.clean(entry, at, pit_laps)]
            field.append(dict(**row, compound=compound, age=age,
                              recent=round(median(recent[-3:]), 3) if recent else None,
                              last_stop=stops[-1][1]["lap_number"] if stops else None))
        return field

    def local_model(self, driver, peer_ids, lap, compound, fallback_compound):
        condition = self.condition(lap)
        track = condition["track"]
        if track not in PACE:
            return None
        climate = (condition.get("temperature"), condition.get("wind"))

        def match(row):
            n, _, _, weather = row
            delta = abs(lap - n)
            for current, key, scale in zip(climate, ("temperature", "wind"), (0.20, 0.40)):
                other = weather.get(key)
                if current is not None and other is not None:
                    delta += min(4, abs(current-other) * scale)
            return delta

        def samples(tyre):
            nearby = [row for row in self.samples[track, tyre] if row[1] != driver and abs(row[0] - lap) <= 8]
            peers = [row for row in nearby if row[1] in peer_ids]
            subset = peers if len(peers) >= 5 and len({row[1] for row in peers}) >= 3 else nearby
            subset = sorted(subset, key=match)[:24]
            # Remove lap-to-lap fuel mass trend before comparing nearby laps.
            return [value + .045 * (n - lap) for n, _, value, _ in subset], len({row[1] for row in subset})

        values, drivers = samples(compound)
        if values:
            center = median(values)
            return center, [clamp(value-center, -7, 7) for value in values], drivers >= 3
        references, _ = samples(fallback_compound)
        if not references:
            for reference in COMPOUNDS:
                references, _ = samples(reference)
                if references:
                    fallback_compound = reference
                    break
        if not references:
            return None
        difference = PACE[track][compound] - PACE[track][fallback_compound]
        return median(references) + difference, [], False

    def projected_position(self, driver, gain):
        rows = self.facts.classification
        target = next((row for row in rows if row["driver_number"] == driver), None)
        if not target or target.get("estimated") or target.get("dnf") or target.get("dsq"):
            return None
        actual = target.get("position")
        duration = numeric(target.get("duration"))
        if not actual or duration is None:
            return None
        ahead = behind = 0
        for row in rows:
            position = row.get("position")
            if row.get("number_of_laps") != target.get("number_of_laps") or row.get("dnf") or row.get("dsq"):
                continue
            other = numeric(row.get("duration"))
            if position is None or other is None or position == actual:
                continue
            if position < actual and duration - gain < other:
                ahead += 1
            if position > actual and duration - gain > other:
                behind += 1
        return actual - ahead + behind

    def pit_window(self, driver, actual, next_stop):
        lap_number = actual["lap_number"]
        laps = self.race.laps[driver]
        first = max(1, lap_number - 2)
        end = min(max(laps), lap_number + WINDOW, next_stop - 1)
        if actual.get("suspension") or end <= lap_number or first not in laps:
            return None
        observed, current_age, first_stint = self.race.tyre(driver, first)
        fitted, new_age, _ = self.race.tyre(driver, lap_number + 1)
        if observed not in COMPOUNDS or fitted not in COMPOUNDS:
            return None
        lane = numeric(actual.get("lane_duration", actual.get("pit_duration")))
        if lane is None or not 12 <= lane <= 45:
            return None
        # Avoid merging two unrelated real stops into one counterfactual.
        if any(first <= row["lap_number"] < lap_number for _, row in self.race.pits[driver]):
            first = lap_number
            observed, current_age, first_stint = self.race.tyre(driver, first)
            if observed not in COMPOUNDS:
                return None
        current_age = current_age if current_age is not None else first-first_stint
        neighbors = self.neighbors(driver, first)
        peer_ids = {row["driver"] for row in neighbors}
        if any(n not in self.facts.starts or n not in laps for n in range(first, end+1)):
            return None
        if any(self.race.control.latest(laps[n].start) in ("red", "closed") for n in range(first, end+1)):
            return None

        @lru_cache(maxsize=None)
        def model(n, compound):
            fallback = observed if n <= lap_number else fitted
            return self.local_model(driver, peer_ids, n, compound, fallback)

        options = []
        actual_snap = self.race.snapshot(driver, lap_number)
        _, actual_traffic = rejoin(actual_snap, driver, lane-3) if actual_snap else (None, None)
        for stop in range(first, min(end, lap_number+3)):
            state = self.race.control.latest(laps[stop].start)
            track = self.condition(stop+1)["track"]
            possible = SLICKS if track == "dry" else ("INTERMEDIATE", "WET") if track == "wet" else COMPOUNDS
            compounds = {tyre for tyre in possible
                         if model(stop+1, tyre) is not None and model(stop+1, tyre)[2]}
            compounds.add(fitted)
            pit_samples = self.losses[state]
            replacement_loss = (lane-3.0 if stop == lap_number else median(pit_samples) if pit_samples
                                else DEFAULT_PIT[self.race.data["event"]] * {"sc": .62, "vsc": .73}.get(state, 1))
            stop_snap = self.race.snapshot(driver, stop)
            rejoin_range, traffic = rejoin(stop_snap, driver, replacement_loss) if stop_snap else (None, None)
            traffic_gain = actual_traffic - traffic if actual_traffic is not None and traffic is not None else 0
            for compound in sorted(compounds):
                if stop == lap_number and compound == fitted:
                    continue
                gain = lane - 3.0 - replacement_loss + traffic_gain
                support = 0
                differences = 0
                residuals = []
                for n in range(first, end + 1):
                    old_tyre, old_age = ((observed, current_age+n-first) if n <= lap_number
                                         else (fitted, (new_age or 0)+n-lap_number-1))
                    alternative, age = ((observed, current_age+n-first) if n <= stop
                                        else (compound, (new_age or 0)+n-stop-1 if compound == fitted else n-stop-1))
                    track_now = self.condition(n)["track"]
                    if track_now not in PACE:
                        break
                    old_wear = self.curves[track_now, old_tyre].wear
                    new_wear = self.curves[track_now, alternative].wear
                    if old_tyre == alternative:
                        gain += old_wear * (old_age-age)
                        if old_age != age:
                            differences += 1
                            reference = model(n, old_tyre)
                            if reference:
                                support += int(reference[2])
                                residuals.extend(value * .35 for value in reference[1])
                        continue
                    old = model(n, old_tyre)
                    new = model(n, alternative)
                    if old is None or new is None:
                        break
                    gain += old[0] + old_wear * old_age - new[0] - new_wear * age
                    differences += 1
                    support += int(old[2] and new[2])
                    residuals.extend(old[1])
                    residuals.extend(new[1])
                else:
                    option = self.simulate(driver, lap_number, stop, compound, gain, differences,
                                           support, residuals, pit_samples, stop != lap_number,
                                           len(peer_ids), lane)
                    option.update(rejoin=rejoin_range, traffic=round(traffic, 2) if traffic is not None else None)
                    options.append(option)
        options.sort(key=lambda row: (row["band"] is None, -row["gain"]))
        return dict(lap=lap_number, before=observed, actual=fitted, lane=lane, anchor=first,
                    through=end, neighbors=neighbors, conditions=[dict(lap=n, **self.condition(n)) for n in range(first, end+1)],
                    alternatives=options)

    def simulate(self, driver, actual, stop, compound, gain, differences, support,
                 residuals, pit_samples, moved, peers, actual_lane):
        pos = self.projected_position(driver, gain)
        baseline = self.projected_position(driver, 0)
        # Resample observed comparable pace and pit variability. Probabilities are
        # conditional frequencies, suppressed where comparable evidence is sparse.
        supported = (not differences or (support / differences >= .67 and len(residuals) >= 12))
        supported = supported and peers >= 4 and (not moved or len(pit_samples) >= 5)
        band = chance = position_chance = None
        if supported:
            rng = Random(f"{driver}:{actual}:{stop}:{compound}")
            pit_center = median(pit_samples) if pit_samples else actual_lane-3
            residual_scale = sqrt(max(1, differences))
            outcomes = []
            for _ in range(TRIALS):
                pace_error = rng.choice(residuals) * residual_scale if residuals else 0
                box_error = rng.choice(pit_samples) - pit_center if moved and pit_samples else 0
                # A bounded model error accounts for tyre age and rejoin effects
                # that cannot be measured for an unrun strategy.
                unknown = rng.triangular(-2.5, 2.5) * (1 + .10 * differences)
                outcomes.append(gain + pace_error - box_error + unknown)
            band = [round(quantile(outcomes, q), 2) for q in (.1, .9)]
            chance = round(100 * sum(value > 0 for value in outcomes) / TRIALS)
            if baseline is not None:
                position_chance = round(100 * sum(self.projected_position(driver, v) < baseline
                                                  for v in outcomes) / TRIALS)
        return dict(lap=stop, compound=compound, gain=round(gain, 2), band=band,
                    position=pos if supported else None, baseline_position=baseline, chance=chance,
                    position_chance=position_chance, comparable_laps=support, changed_laps=differences)

    def report(self, driver):
        windows = []
        stops = [row for _, row in self.race.pits[driver]]
        for i, stop in enumerate(stops):
            next_stop = stops[i+1]["lap_number"] if i+1 < len(stops) else self.race.data["actual_laps"]+1
            window = self.pit_window(driver, stop, next_stop)
            if window:
                windows.append(window)
        return dict(driver=driver, windows=windows, excluded=len(stops)-len(windows), draws=TRIALS)
