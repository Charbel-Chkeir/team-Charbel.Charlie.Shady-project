"""
Tests for validators.py (server-side validation). No API, no database.

Run from the project root:   python3 -m unittest -v
"""
import unittest

import validators as v

CATEGORIES = {"all": None, "historic": None}


class SearchValidationTests(unittest.TestCase):

    def check(self, args):
        return v.validate_search(args, CATEGORIES)

    def test_valid_searches(self):
        for city in ["Rome", "Rio de Janeiro", "Saint-Malo", "St. John's", "بيروت", "Zürich"]:
            errors, form = self.check({"city": city})
            self.assertEqual(errors, {}, city)
        errors, form = self.check({"city": "  Rio   de  Janeiro ", "kind": "historic", "page": "3"})
        self.assertEqual(form, {"city": "Rio de Janeiro", "kind": "historic", "page": 3})

    def test_defaults(self):
        errors, form = self.check({"city": "Rome"})
        self.assertEqual((form["kind"], form["page"]), ("all", 1))

    def test_bad_city(self):
        for city, words in [("", "enter"), ("   ", "enter"), ("R", "2 to 80"),
                            ("x" * 81, "2 to 80"), ("<script>", "only contain"),
                            ("Rome1", "only contain"), ("Rome; DROP TABLE", "only contain")]:
            errors, _ = self.check({"city": city})
            self.assertIn(words, errors.get("city", ""), repr(city))

    def test_bad_kind(self):
        errors, _ = self.check({"city": "Rome", "kind": "weapons"})
        self.assertIn("kind", errors)

    def test_bad_page(self):
        for page in ["0", "-1", "101", "abc", "1.5", "²"]:
            errors, form = self.check({"city": "Rome", "page": page})
            self.assertIn("page", errors, page)
            self.assertEqual(form["page"], 1)


class CoordsValidationTests(unittest.TestCase):

    def test_valid(self):
        errors, form = v.validate_coords({"lat": "33.89", "lon": "-35.5", "name": " Beirut "})
        self.assertEqual(errors, {})
        self.assertEqual(form, {"lat": 33.89, "lon": -35.5, "name": "Beirut"})

    def test_invalid(self):
        for args in [{}, {"lat": "91", "lon": "0"}, {"lat": "0", "lon": "181"},
                     {"lat": "abc", "lon": "0"}, {"lat": "nan", "lon": "0"},
                     {"lat": "inf", "lon": "0"}]:
            errors, _ = v.validate_coords(args)
            self.assertTrue(errors, args)

    def test_name_is_shortened(self):
        _, form = v.validate_coords({"lat": "1", "lon": "1", "name": "a" * 200})
        self.assertEqual(len(form["name"]), 80)


class PlaceValidationTests(unittest.TestCase):

    def test_xid(self):
        self.assertTrue(v.is_valid_xid("W479475562"))
        for bad in ["", None, "../geoname", "N1?apikey=x", "a" * 51]:
            self.assertFalse(v.is_valid_xid(bad), bad)

    def test_validate_place(self):
        errors, place = v.validate_place({"place_xid": "N1", "place_name": " Museum ",
                                          "place_image": "javascript:alert(1)"})
        self.assertEqual(errors, {})
        self.assertEqual(place, {"place_xid": "N1", "place_name": "Museum", "place_image": ""})
        errors, _ = v.validate_place({"place_xid": "N 1", "place_name": ""})
        self.assertEqual(set(errors), {"place_xid", "place_name"})


class SignupValidationTests(unittest.TestCase):

    def test_signup(self):
        ok = {"email": "A@B.com ", "password": "abc12345", "confirm": "abc12345"}
        errors, email = v.validate_signup(ok)
        self.assertEqual((errors, email), ({}, "a@b.com"))
        for change, field in [({"email": "bad"}, "email"), ({"password": "short1"}, "password"),
                              ({"password": "onlyletters"}, "password"),
                              ({"confirm": "different1"}, "confirm")]:
            errors, _ = v.validate_signup({**ok, **change})
            self.assertIn(field, errors, change)


if __name__ == "__main__":
    unittest.main()
