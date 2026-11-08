"""Observed race data for the dashboard and race-wide time alignment."""
from bisect import bisect_right
from collections import Counter, defaultdict
from functools import cached_property

from race import COMPOUNDS, iso, timestamp


def race_end(race):
    flag = next((at for at, row in race.messages.events if row.get("flag") == "CHEQUERED"
                 and at > race.start), None)
    return flag or race.finish


class RaceFacts:
    def __init__(self, race):
        self.race = race
        self.starts = {}
        self.timelines = {}
        for driver, laps in race.laps.items():
            timed = sorted(laps.values(), key=lambda row: row.start)
            self.timelines[driver] = ([row.start for row in timed], timed)
            for row in timed:
                self.starts[row.number] = min(self.starts.get(row.number, row.start), row.start)
        self.lap_times = sorted((at, lap) for lap, at in self.starts.items())
        self.times = [at for at, _ in self.lap_times]
        self.raw_laps = {(row["driver_number"], row["lap_number"]): row for row in race.data["laps"]}
        self.low_grip = []
        for at, row in race.messages.events:
            message = row.get("message", "").upper()
            if "NORMAL GRIP" in message:
                self.low_grip.append((at, False))
            elif "LOW GRIP" in message:
                if "INACTIVE" in message or "DISABLED" in message or "OFF" in message:
                    self.low_grip.append((at, False))
                elif "ACTIVE" in message or "ENABLED" in message:
                    self.low_grip.append((at, True))

    def lap_at(self, at):
        index = bisect_right(self.times, at) - 1
        return self.lap_times[index][1] if index >= 0 else None

    def field_tyres(self, at):
        counts = Counter()
        for driver, (times, laps) in self.timelines.items():
            index = bisect_right(times, at) - 1
            if index < 0:
                continue
            lap = laps[index]
            if not lap.duration or at > lap.end + 5:
                continue
            compound = self.race.tyre(driver, lap.number)[0]
            if compound in COMPOUNDS:
                counts[compound] += 1
        return counts

    def condition(self, at):
        sensor, weather = self.race.track_at(at)
        counts = self.field_tyres(at)
        total = sum(counts.values())
        wet = counts["INTERMEDIATE"] + counts["WET"]
        ratio = wet / total if total else None
        low = next((state for stamp, state in reversed(self.low_grip) if stamp <= at), False)
        # The rain sensor reports precipitation. The tyre mix and race-control
        # notices provide separate evidence about moisture on the track.
        if sensor == "wet" or (total >= 4 and ratio >= .78):
            track = "wet"
        elif sensor == "damp" or (total >= 4 and ratio >= .15) or low:
            track = "damp"
        elif total >= 4 and sensor != "wet":
            track = "dry"
        else:
            track = sensor
        return dict(track=track, rain=weather.get("rainfall") if weather else None,
                    wet_share=round(ratio, 3) if ratio is not None else None, low_grip=low,
                    wind=weather.get("wind_speed") if weather else None,
                    temperature=weather.get("track_temperature") if weather else None)

    @cached_property
    def classification(self):
        race = self.race
        if race.data.get("session_result"):
            return sorted(race.data["session_result"], key=lambda row: row.get("position") or 999)
        completed = [(driver, max((lap for lap in laps.values() if lap.duration),
                                 key=lambda row: row.number, default=None))
                     for driver, laps in race.laps.items()]
        completed = [(driver, lap) for driver, lap in completed if lap]
        completed.sort(key=lambda item: (-item[1].number, item[1].end))
        lead = completed[0][1]
        return [dict(driver_number=driver, position=position, number_of_laps=lap.number,
                     duration=round(lap.end - race.start, 3),
                     gap_to_leader=round(lap.end - lead.end, 3) if lap.number == lead.number else f"+{lead.number-lap.number} V",
                     dnf=lap.end < lead.end - 180, estimated=True)
                for position, (driver, lap) in enumerate(completed, 1)]

    def pit_rows(self, driver=None):
        race = self.race
        return [dict(driver=number, lap=row["lap_number"], at=iso(at),
                     lane=row.get("lane_duration", row.get("pit_duration")),
                     stationary=row.get("stop_duration"), suspension=bool(row.get("suspension")),
                     before=race.tyre(number, row["lap_number"])[0],
                     after=race.tyre(number, row["lap_number"]+1)[0])
                for number, stops in race.pits.items() if driver is None or driver == number
                for at, row in stops]

    def report(self):
        race = self.race
        end = race_end(race)
        driver_data = []
        for number, row in race.drivers.items():
            laps = []
            for n, lap in race.laps[number].items():
                raw = self.raw_laps[number, n]
                timing = race.positions.get(number)
                position = timing.latest(lap.end) if timing and lap.duration else None
                intervals = race.intervals.get(number)
                gap = intervals.latest(lap.end, max_age=15) if intervals and lap.duration else None
                compound, age, _ = race.tyre(number, n)
                laps.append(dict(n=n, time=lap.duration, position=position["position"] if position else lap.position,
                                 gap=gap.get("gap_to_leader") if gap else None,
                                 interval=gap.get("interval") if gap else None, compound=compound,
                                 age=age, sectors=[raw.get(f"duration_sector_{i}") for i in (1, 2, 3)],
                                 speed=raw.get("st_speed"), out=lap.outlap))
            best = min((lap for lap in laps if lap["time"] and lap["time"] > 0),
                       key=lambda lap: lap["time"], default=None)
            driver_data.append(dict(number=number, code=row.get("name_acronym") or str(number),
                                    name=row.get("full_name"), team=row.get("team_name"),
                                    color=row.get("team_colour"), grid=race.grid.get(number),
                                    pit_start=any(g["driver_number"] == number and g["position"] == 0
                                                  for g in race.data.get("starting_grid", [])),
                                    best=best, laps=laps, stints=list(race.stints[number].values())))
        weather = [dict(date=row["date"], lap=self.lap_at(at), minute=round((at-race.start)/60, 2),
                        rain=row.get("rainfall"), air=row.get("air_temperature"), track=row.get("track_temperature"),
                        humidity=row.get("humidity"), pressure=row.get("pressure"),
                        wind=row.get("wind_speed"), direction=row.get("wind_direction"))
                   for at, row in race.weather.events if race.start - 900 <= at <= end + 300]
        phases = [dict(lap=lap, **self.condition(at + 18)) for at, lap in self.lap_times]
        return dict(name=race.data["name"], event=race.data["event"], source=race.data["source"],
                    start=iso(race.start), finish=iso(end), actual_laps=race.data["actual_laps"],
                    drivers=driver_data, classification=self.classification, pits=self.pit_rows(),
                    phases=phases, weather=weather, telemetry=race.native,
                    messages=[dict(date=iso(at), lap=row.get("lap_number"), message=row.get("message"),
                                   category=row.get("category"), flag=row.get("flag"))
                              for at, row in race.messages.events],
                    overtakes=[dict(date=row["date"], lap=self.lap_at(timestamp(row["date"])),
                                    ahead=row.get("overtaking_driver_number"), behind=row.get("overtaken_driver_number"),
                                    position=row.get("position")) for row in race.data.get("overtakes", []) if row.get("date")],
                    radio=[dict(date=row["date"], driver=row["driver_number"], url=row.get("recording_url"))
                           for row in race.data.get("team_radio", []) if row.get("date")],
                    provenance=race.data.get("provenance", []))
