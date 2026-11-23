/*
  map.js -- draws every <div class="map" data-map='{...}'> with Leaflet.

  The data comes from Flask (Python builds it, Jinja's |tojson writes it into
  the data-map attribute safely):
    {
      "markers": [{"lat": 33.9, "lon": 35.5, "label": "1",
                   "title": "National Museum", "url": "/place/W123"}, ...],
      "line": true,          // optional: connect the markers in order (trip route)
      "zoom": 15             // optional: zoom used when there is one marker
    }
  Loaded only on pages that have a map, after leaflet.js (both with "defer").
*/

var TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
var TILE_CREDIT = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

// A numbered pin made with HTML/CSS (no image files needed):
// <span> is the rotated teardrop shape, <b> holds the number (rotated back).
function pinIcon(label) {
  var pin = document.createElement("span");
  var text = document.createElement("b");
  text.textContent = label || "";       // textContent: never interpreted as HTML
  pin.appendChild(text);
  return L.divIcon({
    className: "map-pin",
    html: pin.outerHTML,
    iconSize: [30, 30],
    iconAnchor: [15, 30],      // the bottom tip of the pin is on the place
    popupAnchor: [0, -28]
  });
}

// Popup content built with DOM methods, so a place name coming from the API
// can never inject HTML or scripts (XSS) into the page.
function popupContent(marker) {
  if (!marker.url) {
    var strong = document.createElement("strong");
    strong.textContent = marker.title;
    return strong;
  }
  var link = document.createElement("a");
  link.href = marker.url;
  link.textContent = marker.title;
  return link;
}

document.querySelectorAll(".map[data-map]").forEach(function (box) {
  var data = JSON.parse(box.dataset.map);
  var map = L.map(box, { scrollWheelZoom: false });   // page scroll stays normal

  L.tileLayer(TILE_URL, { maxZoom: 19, attribution: TILE_CREDIT }).addTo(map);

  var points = [];
  data.markers.forEach(function (m) {
    L.marker([m.lat, m.lon], { icon: pinIcon(m.label), title: m.title, alt: m.title })
      .bindPopup(popupContent(m))
      .addTo(map);
    points.push([m.lat, m.lon]);
  });

  if (data.line && points.length > 1) {
    L.polyline(points, { color: "#2e74b5", weight: 3, dashArray: "6 6" }).addTo(map);
  }

  if (points.length === 1) {
    map.setView(points[0], data.zoom || 15);
  } else if (points.length > 1) {
    map.fitBounds(points, { padding: [30, 30], maxZoom: 16 });
  }
});
