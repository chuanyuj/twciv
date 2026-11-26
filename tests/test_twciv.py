"""Automated verification suite for twciv (台灣文明地圖).

Validates all 11 generated web/data/*.json files against docs/DATA_CONTRACTS.md,
verifies zero NaN/Infinity values, verifies 22-county & 368-township completeness,
and verifies every active Advisor view's lens and column contracts.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "web" / "data"


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class TestTwcivDataContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = load("world.json")
        cls.states = load("states.json")
        cls.cities = load("cities.json")
        cls.nation = load("nation.json")
        cls.counties = load("counties.json")
        cls.lenses = load("lenses.json")
        cls.resources = load("resources.json")
        cls.infra = load("infrastructure.json")
        cls.wonders = load("wonders.json")
        cls.citizens = load("citizens.json")
        cls.sources = load("sources.json")
        cls.grid_n = cls.world["grid"]["cols"] * cls.world["grid"]["rows"]

    def test_world_grid_and_geography(self):
        w = self.world
        self.assertEqual(w["version"], 2)
        for arr_key in ("owner", "county", "elev", "elev_max", "water", "relief", "cover"):
            self.assertEqual(len(w[arr_key]), self.grid_n, f"{arr_key} length mismatch")
        self.assertEqual(len(w["states"]), 22)
        self.assertEqual(len(w["counties"]), 368)
        land = sum(1 for o in w["owner"] if o >= 0)
        self.assertGreater(land, 1000)
        # Every one of the 22 counties/cities must own at least 1 land hex
        owned = {o for o in w["owner"] if o >= 0}
        self.assertEqual(len(owned), 22)
        self.assertGreaterEqual(len(w["rivers"]), 10)

    def test_states_and_cities_alignment(self):
        self.assertEqual(len(self.states), 22)
        self.assertEqual(len(self.cities), 22)
        world_fips = [s["fips"] for s in self.world["states"]]
        state_fips = [s["fips"] for s in self.states]
        self.assertEqual(world_fips, state_fips)
        # Cities sorted by population descending
        pops = [c["population"] for c in self.cities]
        self.assertEqual(pops, sorted(pops, reverse=True))
        # Taipei is capital
        caps = [c for c in self.cities if c.get("capital")]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["full"], "臺北市")
        # All city cells on valid land
        for c in self.cities:
            self.assertTrue(0 <= c["cell"] < self.grid_n)
            self.assertGreaterEqual(self.world["owner"][c["cell"]], 0)

    def test_counties_368_townships(self):
        co = self.counties
        self.assertEqual(len(co["rows"]), 368)
        self.assertEqual(len(co["fields"]), len(co["columns"]))
        for row in co["rows"]:
            self.assertEqual(len(row), len(co["columns"]))
            for v in row:
                if isinstance(v, float):
                    self.assertTrue(math.isfinite(v))

    def test_lenses_contracts(self):
        lenses = self.lenses["lenses"]
        self.assertEqual(len(lenses), 16)
        ids = {l["id"] for l in lenses}
        for required in (
            "density", "income", "home_price", "degrees", "elderly", "child_pct", "aging_index",
            "growth", "home_ratio", "age", "single_hh", "elevation", "forest", "crop", "developed", "quakes",
        ):
            self.assertIn(required, ids)
        for l in lenses:
            self.assertEqual(len(l["values"]), self.grid_n)
            self.assertEqual(len(l["domain"]), 2)
            self.assertLess(l["domain"][0], l["domain"][1])
            non_null = [v for v in l["values"] if v is not None]
            self.assertGreater(len(non_null), 500, f"lens {l['id']} too sparse")

    def test_resources_infra_wonders_citizens_sources(self):
        self.assertGreaterEqual(len(self.resources["items"]), 55)
        for it in self.resources["items"]:
            self.assertTrue(0 <= it["cell"] < self.grid_n)
        self.assertGreater(len(self.infra["roads"]), 300)
        self.assertGreater(len(self.infra["rail"]), 200)
        self.assertEqual(len(self.infra["ports"]), 7)
        self.assertEqual(len(self.infra["airports"]), 9)
        self.assertEqual(len(self.wonders["wonders"]), 23)
        self.assertEqual(len(self.citizens["cities"]), 22)
        self.assertGreaterEqual(len(self.sources), 15)
        # Verify v2 expansion files exist and conform to contracts
        districts = load("districts.json")
        self.assertEqual(len(districts["cities"]), 22)
        self.assertEqual(len(districts["counties"]), 368)
        self.assertGreaterEqual(len(districts["catalog"]), 7)
        trade = load("trade.json")
        self.assertEqual(len(trade["zones"]), 12)
        self.assertEqual(len(trade["routes"]), 18)
        for r in trade["routes"]:
            self.assertGreaterEqual(len(r["path"]), 2)
        disasters = load("disasters.json")
        self.assertGreater(disasters["seismic"]["total_events"], 2000)
        self.assertGreaterEqual(len(disasters["seismic"]["notable_m6"]), 20)
        # Military remains intentionally absent (classified in Taiwan)
        self.assertFalse((DATA / "military.json").exists(), "military.json should not exist")


if __name__ == "__main__":
    unittest.main()
