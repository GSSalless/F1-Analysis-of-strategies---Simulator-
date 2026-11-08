"""Verify real crossover evidence and automatic strategy analysis."""
from unittest import TestCase

from app import load
from review import RaceReview


class RaceReviewTests(TestCase):
    def setUp(self):
        self.race = load("interlagos")
        if self.race is None:
            self.skipTest("Cache de Interlagos indisponível.")

    def test_compounds_distinguish_moisture_from_the_rain_sensor(self):
        facts = self.race.facts
        first, dry, last = (facts.condition(facts.starts[n] + 25) for n in (1, 45, 67))
        self.assertEqual([c["track"] for c in (first, dry, last)], ["wet", "dry", "wet"])
        self.assertEqual(first["rain"], 0)
        self.assertGreater(first["wet_share"], .9)

    def test_verstappen_window_respects_real_stops_and_sample_limits(self):
        driver = 3
        review = RaceReview(self.race.facts)
        self.assertEqual(review.projected_position(driver, 0), 2)
        self.assertEqual(review.projected_position(driver, 15), 1)
        windows = review.report(driver)["windows"]
        self.assertEqual([window["lap"] for window in windows], [17, 45, 62])
        rows = []
        for window in windows:
            self.assertLessEqual(len(window["neighbors"]), 10)
            for option in window["alternatives"]:
                self.assertLessEqual(abs(option["lap"] - window["lap"]), 2)
                self.assertNotEqual((option["lap"], option["compound"]), (window["lap"], window["actual"]))
                rows.append(option)
        self.assertTrue(any(row["chance"] is None for row in rows))
        self.assertTrue(any(0 <= row["chance"] <= 100 for row in rows if row["chance"] is not None))
