"""Regression checks for the chronology and strategy comparisons."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main
import json

from app import analyze
from race import Race, iso, timestamp


def sample_race():
    base = timestamp("2026-11-08T17:00:00+00:00")
    rows = []
    for n in range(1, 22):
        for driver in (1, 2):
            at = base + 85 * (n - 1) + driver * 2
            rows.append(dict(driver_number=driver, lap_number=n, date_start=iso(at),
                             lap_duration=85 + driver * .2 + n * .02))
    weather = [dict(date=iso(base + offset), rainfall=int(offset < 425 or offset >= 1275))
               for offset in range(0, 1800, 40)]
    return dict(name="Teste", event="interlagos", source="OpenF1", actual_laps=21, scheduled_laps=21,
                session={"date_start": iso(base)}, drivers=[{"driver_number": n} for n in (1, 2)],
                laps=rows, weather=weather, stints=[
                    dict(driver_number=1, lap_start=1, lap_end=7, tyre_age_at_start=0, compound="INTERMEDIATE"),
                    dict(driver_number=1, lap_start=8, lap_end=15, tyre_age_at_start=0, compound="SOFT"),
                    dict(driver_number=1, lap_start=16, lap_end=21, tyre_age_at_start=0, compound="INTERMEDIATE"),
                    dict(driver_number=2, lap_start=1, lap_end=21, tyre_age_at_start=0, compound="INTERMEDIATE"),
                ])


class ReplayTests(TestCase):
    def test_future_does_not_change_current_replay(self):
        data = sample_race()
        race = Race(data)
        before = analyze(race, 1, 12, "hold", 8, None)
        altered = deepcopy(data)
        cutoff = race.laps[1][12].start
        for row in altered["laps"]:
            if timestamp(row["date_start"]) >= cutoff:
                row["lap_duration"] += 20
        for row in altered["weather"]:
            if timestamp(row["date"]) > cutoff:
                row["rainfall"] = 0
        altered["stints"][2]["compound"] = "WET"
        altered["pit"] = [{"date": iso(cutoff + 60), "driver_number": 1,
                           "lap_number": 12, "lane_duration": 27}]
        altered["race_control"] = [{"date": iso(cutoff + 5), "state": "red"}]
        self.assertEqual(before, analyze(Race(altered), 1, 12, "hold", 8, None))

    def test_wet_to_dry_to_wet_and_user_scenario(self):
        race = Race(sample_race())
        first = analyze(race, 1, 4, "hold", 8, None)
        middle = analyze(race, 1, 12, "rain", 8, None)
        last = analyze(race, 1, 19, "hold", 8, None)
        self.assertEqual([view["snapshot"]["track"] for view in (first, middle, last)],
                         ["wet", "dry", "wet"])
        self.assertEqual(middle["strategy"]["track_path"][:5], ["dry", "dry", "damp", "damp", "wet"])
        self.assertTrue(all(row["compound"] in ("INTERMEDIATE", "WET")
                            for row in last["strategy"]["options"] if row["stop"] is not None))

    def test_mexico_actual_stop_and_suspension(self):
        cache = Path(__file__).resolve().parent / "data" / "mexico.json"
        if not cache.exists():
            self.skipTest("Cache do México indisponível.")
        data = json.loads(cache.read_text(encoding="utf-8"))
        race = Race(data)
        driver = next(n for n, entry in race.drivers.items() if entry.get("name_acronym") == "VER")
        s = analyze(race, driver, 27, "hold", 12, None)["snapshot"]
        self.assertEqual((s["compound"], s["age"]), ("MEDIUM", 26))
        self.assertIsNotNone(s["gap_front"])
        self.assertIsNotNone(s["gap_rear"])
        review = analyze(race, driver, 27, "hold", 12, 27)["strategy"]
        soft = [r for r in review["options"] if r["compound"] == "SOFT"]
        self.assertEqual({r["stop"] for r in soft}, {26, 27, 28})
        self.assertEqual([r["stop"] for r in soft if r["actual"]], [27])
        if data["source"] == "Jolpica F1":
            suspension = analyze(race, driver, 45, "hold", 12, 45)["strategy"]
            self.assertFalse(suspension["options"])
            self.assertTrue(suspension["actual_stop"]["suspension"])


if __name__ == "__main__":
    main()
