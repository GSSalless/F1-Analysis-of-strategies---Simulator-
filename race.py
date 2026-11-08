"""Common race timeline for OpenF1 and lap-level fallback data."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

SLICKS = ("SOFT", "MEDIUM", "HARD")
COMPOUNDS = SLICKS + ("INTERMEDIATE", "WET")


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() if value else None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def numeric(value):
    return float(value) if isinstance(value, (int, float)) else None


class Timeline:
    def __init__(self, events):
        self.events = sorted(events, key=lambda item: item[0])
        self.times = [at for at, _ in self.events]

    def through(self, at):
        return self.events[:bisect_right(self.times, at)]

    def latest(self, at, max_age=None):
        index = bisect_right(self.times, at) - 1
        if index < 0:
            return None
        stamp, value = self.events[index]
        return value if max_age is None or at - stamp <= max_age else None

    def between(self, start, end):
        return self.events[bisect_right(self.times, start):bisect_right(self.times, end)]


@dataclass
class Lap:
    driver: int
    number: int
    start: float
    duration: float
    outlap: bool
    position: int
    crossing: float = None

    @property
    def end(self):
        return self.crossing if self.crossing is not None else self.start + self.duration


def control_state(row, previous):
    message = row.get("message", "").upper()
    flag = (row.get("flag") or "").upper()
    scope = (row.get("scope") or "").upper()
    if (flag == "RED" and scope in ("TRACK", "")) or "RACE SUSPENDED" in message:
        return "red"
    if "PIT EXIT CLOSED" in message or "PIT LANE CLOSED" in message:
        return "closed"
    if "VSC DEPLOYED" in message or "VIRTUAL SAFETY CAR DEPLOYED" in message:
        return "vsc"
    if "SAFETY CAR DEPLOYED" in message or "RESUMED BEHIND THE SAFETY CAR" in message:
        return "sc"
    if (flag == "GREEN" and scope in ("TRACK", "")) or "GREEN LIGHT - PIT EXIT OPEN" in message:
        return "green"
    if "STANDING START" == message or ("TRACK CLEAR" == message and previous == "vsc"):
        return "green"
    if message in ("PIT EXIT OPEN", "PIT LANE OPEN") and previous == "closed":
        return "green"
    return previous


class Race:
    def __init__(self, data):
        self.data = data
        self.native = data["source"] == "OpenF1"
        self.start = timestamp(data["session"]["date_start"])
        starts = [timestamp(row.get("date")) for row in data.get("race_control", [])
                  if row.get("message", "").upper() in ("SESSION STARTED", "RACE STARTED")]
        valid_starts = [at for at in starts if at is not None and self.start - 120 <= at <= self.start + 1800]
        if valid_starts:
            self.start = min(valid_starts)

        self.drivers = {row["driver_number"]: row for row in data["drivers"]}
        self.grid = {row["driver_number"]: row["position"] for row in data.get("starting_grid", [])
                     if row.get("position", 0) > 0}
        self.laps = defaultdict(dict)
        grouped = defaultdict(list)
        for row in data["laps"]:
            grouped[row["driver_number"]].append(row)
        for driver, rows in grouped.items():
            cursor = self.start
            for row in sorted(rows, key=lambda r: r["lap_number"]):
                n = row["lap_number"]
                start = timestamp(row.get("date_start"))
                if start is None:
                    if not self.native:
                        start = cursor
                    elif n == 1:
                        start = self.start
                    else:
                        continue
                duration = numeric(row.get("lap_duration"))
                self.laps[driver][n] = Lap(driver, n, start, duration,
                                           bool(row.get("is_pit_out_lap")), row.get("position"))
                if duration:
                    cursor = start + duration
            for n, lap in self.laps[driver].items():
                next_lap = self.laps[driver].get(n + 1)
                if self.native and next_lap and next_lap.start > lap.start:
                    lap.crossing = next_lap.start

        self.pits = defaultdict(list)
        for row in data.get("pit", []):
            driver = row["driver_number"]
            n = row["lap_number"]
            lap = self.laps[driver].get(n)
            at = timestamp(row.get("date"))
            if at is None and lap and lap.duration:
                at = lap.end
            if at is not None:
                self.pits[driver].append((at, row))
        for stops in self.pits.values():
            stops.sort(key=lambda item: item[0])

        self.stints = defaultdict(dict)
        for row in sorted(data.get("stints", []), key=lambda r: (r["lap_start"], r.get("stint_number", 0))):
            driver = row["driver_number"]
            lap = self.laps[driver].get(row["lap_start"])
            if lap or row["lap_start"] == 1:
                self.stints[driver][row["lap_start"]] = row

        self.positions = self._driver_timelines(data.get("position", []))
        self.intervals = self._driver_timelines(data.get("intervals", []))
        control = self._dated(data.get("race_control", []))
        self.messages = Timeline(control)
        state = "green"
        states = [(self.start - 1, state)]
        for at, row in sorted(control, key=lambda item: item[0]):
            next_state = row.get("state") or control_state(row, state)
            if next_state != state:
                states.append((at, next_state))
            state = next_state
        self.control = Timeline(states)
        self.weather = Timeline(self._dated(data.get("weather", [])))
        self.finish = max((lap.end for laps in self.laps.values() for lap in laps.values()
                           if lap.duration and lap.number == data["actual_laps"]), default=self.start)

    @staticmethod
    def _dated(rows):
        return [(timestamp(row["date"]), row) for row in rows if row.get("date")]

    def _driver_timelines(self, rows):
        groups = defaultdict(list)
        for at, row in self._dated(rows):
            groups[row["driver_number"]].append((at, row))
        return {driver: Timeline(events) for driver, events in groups.items()}

    def track_at(self, at):
        weather = self.weather.latest(at, max_age=180)
        if weather is None or weather.get("rainfall") not in (0, 1):
            return self.data.get("weather_assumption", "unknown"), weather
        recent = self.weather.between(at - 240, at)
        if weather["rainfall"]:
            dry = [stamp for stamp, row in recent if row.get("rainfall") == 0]
            return ("damp" if dry and at - dry[-1] < 115 else "wet"), weather
        return ("damp" if any(row.get("rainfall") == 1 for _, row in recent) else "dry"), weather

    def tyre(self, driver, lap):
        starts = self.stints[driver]
        first = max((n for n in starts if n <= lap), default=None)
        if first is None:
            return None, None, None
        row = starts[first]
        initial = row.get("tyre_age_at_start")
        age = initial + lap - first if initial is not None else None
        compound = row.get("compound")
        return compound if compound in COMPOUNDS else None, age, first

    def past_stops(self, driver, at):
        return [(stamp, row) for stamp, row in self.pits[driver] if stamp <= at]

    def clean(self, lap, at, pit_laps):
        if (lap.number == 1 or lap.outlap or not lap.duration or lap.duration < 55
                or lap.duration > 150 or lap.end > at or lap.end <= lap.start):
            return False
        if lap.number in pit_laps or lap.number - 1 in pit_laps:
            return False
        if self.control.latest(lap.start) != "green" or self.control.between(lap.start, lap.end):
            return False
        previous = self.laps[lap.driver].get(lap.number - 1)
        return previous is None or not previous.duration or lap.start - previous.start <= 170

    def _board(self, at):
        entries = []
        for driver, laps in self.laps.items():
            completed = [lap for lap in laps.values() if lap.duration and lap.end <= at]
            latest = max(completed, key=lambda lap: lap.number, default=None)
            live = self.positions.get(driver)
            current = live.latest(at) if live else None
            position = current["position"] if current else (latest.position if latest else self.grid.get(driver))
            interval = self.intervals.get(driver)
            gap = interval.latest(at, max_age=15) if interval else None
            # After a driver stops updating, do not use stale gaps in projections.
            active = latest is None or at - latest.end < 180 or self.control.latest(at) == "red"
            if position is not None:
                entries.append(dict(driver=driver, position=position, completed=latest.number if latest else 0,
                                    gap=gap.get("gap_to_leader") if gap else None,
                                    interval=gap.get("interval") if gap else None,
                                    crossing=latest.end if latest else None, active=active))
        if self.native:
            entries.sort(key=lambda row: row["position"])
        else:
            entries.sort(key=lambda row: (-row["completed"], row["crossing"] or 0, row["position"]))
            for position, row in enumerate(entries, 1):
                row["position"] = position
                leader = entries[0]
                ahead = entries[position - 2] if position > 1 else None
                for label, rival in (("gap", leader), ("interval", ahead)):
                    if not rival or not row["crossing"] or not rival["crossing"]:
                        continue
                    common = min(row["completed"], rival["completed"])
                    own_lap = self.laps[row["driver"]].get(common)
                    other_lap = self.laps[rival["driver"]].get(common)
                    if row["completed"] + 1 < rival["completed"]:
                        continue
                    elif own_lap and other_lap and own_lap.duration and other_lap.duration:
                        delta = own_lap.end - other_lap.end
                        if 0 <= delta < 65 and at - other_lap.end < 150:
                            row[label] = round(delta, 3)
        if entries and entries[0]["position"] == 1:
            entries[0]["gap"] = 0.0
        return entries

    def snapshot(self, driver, number):
        lap = self.laps[driver].get(number)
        if lap is None:
            return None
        at = lap.start
        past = [lap for lap in self.laps[driver].values()
                if lap.number < number and lap.duration and lap.end <= at]
        best = min(past, key=lambda lap: lap.duration, default=None)
        stops = self.past_stops(driver, at)
        compound, age, stint = self.tyre(driver, number)
        track, weather = self.track_at(at)
        board = self._board(at)
        own = next((row for row in board if row["driver"] == driver), None)
        position = own["position"] if own else None
        front = next((row for row in board if position and row["position"] == position - 1), None)
        rear = next((row for row in board if position and row["position"] == position + 1), None)
        pit_laps = {row["lap_number"] for _, row in stops}
        return dict(lap=number, at=iso(at), elapsed=round(at - self.start), compound=compound,
                    age=age, stint_start=stint, last_pit=stops[-1][1] if stops else None,
                    track=track, weather=weather, assumed_track=weather is None and track != "unknown",
                    control=self.control.latest(at),
                    position=position, front=front["driver"] if front else None,
                    rear=rear["driver"] if rear else None, gap_front=own["interval"] if front else None,
                    gap_rear=rear["interval"] if rear else None, board=board,
                    event=self.messages.latest(at),
                    best={"lap": best.number, "duration": best.duration} if best else None,
                    last_lap={"lap": past[-1].number, "duration": past[-1].duration} if past else None,
                    history=[dict(lap=row.number, duration=row.duration, compound=self.tyre(driver, row.number)[0],
                                  clean=self.clean(row, at, pit_laps)) for row in past])

    def metadata(self):
        return dict(name=self.data["name"], event=self.data["event"], source=self.data["source"],
                    actual_laps=self.data["actual_laps"], imported_at=self.data["imported_at"],
                    timing="timestamps" if self.native else "lap_crossings",
                    capabilities=dict(tyres=bool(self.data.get("stints")),
                                      weather=bool(self.data.get("weather")),
                                      neutralizations=bool(self.data.get("race_control"))),
                    provenance=self.data.get("provenance", []),
                    drivers=[dict(number=number, name=row.get("full_name"),
                                  code=row.get("name_acronym") or str(number),
                                  team=row.get("team_name"), laps=sorted(self.laps[number]))
                             for number, row in sorted(self.drivers.items()) if self.laps[number]])
