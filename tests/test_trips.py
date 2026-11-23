"""
Trip & itinerary tests: create / edit / delete trips, add / move / edit /
remove places, validation, and OWNERSHIP (another user's trip -> 403).

Real app + in-memory database + fake API answers. Run:  python3 -m unittest -v
"""
import logging
import os
import re
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["OPENTRIPMAP_API_KEY"] = "test-key"

import api_client                                   # noqa: E402
from app import app                                 # noqa: E402
from models import db, Trip, TripItem               # noqa: E402
from tests.test_routes import fake_api              # noqa: E402

logging.disable(logging.CRITICAL)

START = date.today() + timedelta(days=10)
END = START + timedelta(days=3)                      # a 4-day trip


class Browser:
    """A logged-in test user (its own cookies = its own session)."""

    def __init__(self):
        self.client = app.test_client()
        self.email = f"{uuid.uuid4().hex[:8]}@test.com"   # unique user per test
        self.post("/signup", {"email": self.email, "password": "abc12345",
                              "confirm": "abc12345"}, page="/signup")

    def token(self, page="/"):
        html = self.client.get(page).get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, url, data, page="/"):
        data = dict(data, csrf_token=self.token(page))
        return self.client.post(url, data=data)

    def get(self, url):
        return self.client.get(url)

    def new_trip(self, **changes):
        data = {"title": "Beirut weekend", "destination": "Beirut",
                "start_date": START.isoformat(), "end_date": END.isoformat()}
        data.update(changes)
        return self.post("/trips/new", data)

    def last_trip(self):
        with app.app_context():
            return Trip.query.order_by(Trip.id.desc()).first().id

    def add_place(self, trip_id, xid="W2", name="National Museum", **extra):
        data = {"trip_id": str(trip_id), "place_xid": xid, "place_name": name,
                "place_lat": "33.87", "place_lon": "35.51", "next": f"/place/{xid}"}
        data.update(extra)
        return self.post("/trips/items/add", data)


def items_of(trip_id):
    with app.app_context():
        return [(i.place_name, i.visit_date, i.sort_order, i.notes)
                for i in db.session.get(Trip, trip_id).items]


class TripTests(unittest.TestCase):

    def setUp(self):
        api_client.clear_cache()
        patcher = mock.patch("api_client.requests.get", side_effect=fake_api)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.alice = Browser()

    # ---------- login required ----------
    def test_trips_need_login(self):
        anonymous = app.test_client()
        for url in ["/trips", "/trips/new", "/trips/1"]:
            r = anonymous.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.location)

    # ---------- create / list / view ----------
    def test_create_trip(self):
        r = self.alice.new_trip()
        self.assertEqual(r.status_code, 302)
        trip_id = self.alice.last_trip()
        self.assertTrue(r.location.endswith(f"/trips/{trip_id}"))
        with app.app_context():
            trip = db.session.get(Trip, trip_id)
            self.assertEqual((trip.dest_lat, trip.dest_lon), (33.89, 35.50))   # geocoded
            self.assertEqual(trip.days, 4)
        html = self.alice.get("/trips").get_data(as_text=True)
        self.assertIn("Beirut weekend", html)
        html = self.alice.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("No places planned yet", html)

    def test_create_trip_validation(self):
        cases = [({"title": ""}, "Give your trip a title"),
                 ({"destination": "R0me"}, "can only contain letters"),
                 ({"end_date": (START - timedelta(days=1)).isoformat()}, "cannot be before"),
                 ({"end_date": (START + timedelta(days=90)).isoformat()}, "at most 60 days"),
                 ({"start_date": "2027-02-30"}, "valid start date"),
                 ({"destination": "Atlantisxyz"}, "could not find a city")]
        for change, message in cases:
            r = self.alice.new_trip(**change)
            self.assertEqual(r.status_code, 400, change)
            self.assertIn(message, r.get_data(as_text=True), change)

    def test_api_down_still_creates_trip(self):
        import requests
        with mock.patch("api_client.requests.get", side_effect=requests.Timeout):
            r = self.alice.new_trip()
        self.assertEqual(r.status_code, 302)
        with app.app_context():
            trip = db.session.get(Trip, self.alice.last_trip())
            self.assertIsNone(trip.dest_lat)          # saved, just without weather

    # ---------- ownership (IDOR) ----------
    def test_other_users_cannot_touch_my_trip(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        self.alice.add_place(trip_id)
        with app.app_context():
            item_id = db.session.get(Trip, trip_id).items[0].id

        bob = Browser()
        self.assertEqual(bob.get(f"/trips/{trip_id}").status_code, 403)
        self.assertEqual(bob.get(f"/trips/{trip_id}/edit").status_code, 403)
        attacks = [
            (f"/trips/{trip_id}/edit", {"title": "hacked", "destination": "Beirut",
                                        "start_date": START.isoformat(), "end_date": END.isoformat()}),
            (f"/trips/{trip_id}/delete", {}),
            (f"/trips/{trip_id}/items/{item_id}/update", {"notes": "hacked"}),
            (f"/trips/{trip_id}/items/{item_id}/move", {"direction": "up"}),
            (f"/trips/{trip_id}/items/{item_id}/delete", {}),
            ("/trips/items/add", {"trip_id": str(trip_id), "place_xid": "N9", "place_name": "Spam"}),
        ]
        for url, data in attacks:
            self.assertEqual(bob.post(url, data).status_code, 403, url)
        # nothing changed
        with app.app_context():
            trip = db.session.get(Trip, trip_id)
            self.assertEqual(trip.title, "Beirut weekend")
            self.assertEqual([i.place_name for i in trip.items], ["National Museum"])
        self.assertNotIn("Beirut weekend", bob.get("/trips").get_data(as_text=True))

    def test_item_must_belong_to_the_trip(self):
        """Using MY trip id with an item id from someone else's trip -> 404."""
        bob = Browser()
        bob.new_trip(title="Bob trip")
        bob_trip = bob.last_trip()
        bob.add_place(bob_trip)
        with app.app_context():
            bob_item = db.session.get(Trip, bob_trip).items[0].id
        self.alice.new_trip()
        alice_trip = self.alice.last_trip()
        r = self.alice.post(f"/trips/{alice_trip}/items/{bob_item}/delete", {})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(items_of(bob_trip)), 1)

    def test_unknown_trip_is_404(self):
        self.assertEqual(self.alice.get("/trips/99999").status_code, 404)

    # ---------- itinerary items ----------
    def test_add_items(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        day2 = (START + timedelta(days=1)).isoformat()
        r = self.alice.add_place(trip_id, visit_date=day2, notes="  Go early  ")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.location.endswith("/place/W2"))        # back to the place page
        self.alice.add_place(trip_id, xid="N5", name="Pigeon Rocks")
        self.assertEqual(items_of(trip_id), [
            ("National Museum", START + timedelta(days=1), 0, "Go early"),
            ("Pigeon Rocks", None, 1, None)])
        html = self.alice.get(f"/trips/{trip_id}").get_data(as_text=True)
        self.assertIn("Day 2", html)
        self.assertIn("Not scheduled yet", html)

    def test_add_item_errors(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        outside = (END + timedelta(days=1)).isoformat()
        for extra in [{"visit_date": outside}, {"notes": "x" * 501}, {"place_xid": "../x"}]:
            self.alice.add_place(trip_id, **extra)
        self.assertEqual(items_of(trip_id), [])                   # nothing saved
        self.alice.add_place(trip_id)
        r = self.alice.add_place(trip_id)                         # same place twice
        self.assertEqual(len(items_of(trip_id)), 1)
        html = self.alice.client.get(r.location).get_data(as_text=True)
        self.assertIn("already in", html)

    def test_move_update_delete_item(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        for xid, name in [("N1", "First"), ("N2", "Second"), ("N3", "Third")]:
            self.alice.add_place(trip_id, xid=xid, name=name)
        with app.app_context():
            ids = {i.place_name: i.id for i in db.session.get(Trip, trip_id).items}

        self.alice.post(f"/trips/{trip_id}/items/{ids['Third']}/move", {"direction": "up"})
        self.assertEqual([i[0] for i in items_of(trip_id)], ["First", "Third", "Second"])
        self.alice.post(f"/trips/{trip_id}/items/{ids['First']}/move", {"direction": "up"})  # already first
        self.assertEqual([i[0] for i in items_of(trip_id)], ["First", "Third", "Second"])
        r = self.alice.post(f"/trips/{trip_id}/items/{ids['First']}/move", {"direction": "sideways"})
        self.assertEqual(r.status_code, 400)

        self.alice.post(f"/trips/{trip_id}/items/{ids['Second']}/update",
                        {"visit_date": START.isoformat(), "notes": "Lunch nearby"})
        self.assertIn(("Second", START, 2, "Lunch nearby"), items_of(trip_id))

        self.alice.post(f"/trips/{trip_id}/items/{ids['First']}/delete", {})
        self.assertEqual(sorted(i[0] for i in items_of(trip_id)), ["Second", "Third"])

    # ---------- edit / delete trip ----------
    def test_edit_trip_moves_out_of_range_items(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        self.alice.add_place(trip_id, visit_date=END.isoformat())          # last day
        r = self.alice.post(f"/trips/{trip_id}/edit", {
            "title": "Shorter", "destination": "Beirut",
            "start_date": START.isoformat(), "end_date": START.isoformat()})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(items_of(trip_id)[0][1], None)                   # now unscheduled
        with app.app_context():
            self.assertEqual(db.session.get(Trip, trip_id).title, "Shorter")

    def test_delete_trip_deletes_items(self):
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        self.alice.add_place(trip_id)
        r = self.alice.post(f"/trips/{trip_id}/delete", {})
        self.assertEqual(r.status_code, 302)
        with app.app_context():
            self.assertIsNone(db.session.get(Trip, trip_id))
            self.assertEqual(TripItem.query.filter_by(trip_id=trip_id).count(), 0)

    def test_get_cannot_delete(self):
        """Changing data needs POST (+ CSRF token): a link or GET cannot delete."""
        self.alice.new_trip()
        trip_id = self.alice.last_trip()
        self.assertEqual(self.alice.get(f"/trips/{trip_id}/delete").status_code, 405)
        r = self.alice.client.post(f"/trips/{trip_id}/delete")           # no CSRF token
        self.assertEqual(r.status_code, 302)                             # rejected, redirected
        with app.app_context():
            self.assertIsNotNone(db.session.get(Trip, trip_id))

    # ---------- place page ----------
    def test_place_page_shows_my_trips(self):
        self.alice.new_trip(title="Upcoming one")
        html = self.alice.get("/place/W2").get_data(as_text=True)
        self.assertIn("Add to a trip", html)
        self.assertIn("Upcoming one", html)
        other = Browser()
        html = other.get("/place/W2").get_data(as_text=True)
        self.assertNotIn("Upcoming one", html)                           # not my trip
        self.assertIn("Create a trip", html)


if __name__ == "__main__":
    unittest.main()
