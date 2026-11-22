"""Database models -- the ONLY data WanderWise stores.

Places, descriptions and weather come from the APIs and are NOT copied here.
We store accounts and what each user creates: favorites, trips, itinerary items.

    User 1 --- * Favorite          (a user saves many places)
    User 1 --- * Trip              (a user plans many trips)
    Trip 1 --- * TripItem          (a trip contains many places to visit)

A place is identified by OpenTripMap's id, the "xid" (e.g. "N1234567").
We also keep its name/image/coordinates so lists and maps can be drawn
without calling the API again for every row.

After changing this file:  python reset_db.py   (local, wipes local data).
"""
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Deleting a user deletes their favorites and trips (and, through Trip,
    # the trip items) -> no orphan rows left in the database.
    favorites = db.relationship("Favorite", backref="user",
                                cascade="all, delete-orphan")
    trips = db.relationship("Trip", backref="user",
                            cascade="all, delete-orphan")


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    place_xid = db.Column(db.String(50), nullable=False)      # OpenTripMap id
    place_name = db.Column(db.String(255), nullable=False)
    place_image = db.Column(db.String(500))                   # optional URL
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow,
                           nullable=False)

    # The same user cannot save the same place twice.
    __table_args__ = (db.UniqueConstraint("user_id", "place_xid",
                                          name="uniq_user_place"),)


class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    destination = db.Column(db.String(120), nullable=False)   # e.g. "Rome"
    # Destination centre, kept so the trip page can show weather and a map
    # without searching the city again. Optional.
    dest_lat = db.Column(db.Float)
    dest_lon = db.Column(db.Float)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow,
                           nullable=False)

    # Items come back already sorted: by day, then by the order chosen.
    items = db.relationship("TripItem", backref="trip",
                            cascade="all, delete-orphan",
                            order_by="(TripItem.visit_date, TripItem.sort_order)")

    # Backstop in the database itself; validators.py checks this first and
    # shows a friendly message.
    __table_args__ = (db.CheckConstraint("end_date >= start_date",
                                         name="trip_dates_order"),)


class TripItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    place_xid = db.Column(db.String(50), nullable=False)
    place_name = db.Column(db.String(255), nullable=False)
    place_lat = db.Column(db.Float)                           # for the trip map
    place_lon = db.Column(db.Float)
    visit_date = db.Column(db.Date)                           # optional
    notes = db.Column(db.String(500))                         # optional
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    # A place appears at most once in the same trip.
    __table_args__ = (db.UniqueConstraint("trip_id", "place_xid",
                                          name="uniq_trip_place"),)
