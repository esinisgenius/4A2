import unittest

from src.prepare_chargers import normalise_connectors
from src.prepare_generator_input import EXPECTED_COLUMNS, URBAN_SA4_CODES


class PrepareChargersTests(unittest.TestCase):
    def test_connector_aliases_are_canonical(self):
        self.assertEqual(normalise_connectors("CCS (Type 2); CHAdeMO"), ["CCS2", "CHAdeMO"])
        self.assertEqual(normalise_connectors("ccs2; chademo"), ["CCS2", "CHAdeMO"])

    def test_connector_values_are_deduplicated(self):
        self.assertEqual(normalise_connectors("ccs2; CCS (Type 2)"), ["CCS2"])

    def test_generator_schema_matches_teacher_demo(self):
        self.assertEqual(EXPECTED_COLUMNS,
                         ["station_id", "name", "lat", "lon", "site_type", "connectors", "max_kw"])

    def test_generator_urban_codes_cover_demo_metros(self):
        self.assertTrue({"102", "107", "111", "117"}.issubset(URBAN_SA4_CODES))


if __name__ == "__main__":
    unittest.main()
