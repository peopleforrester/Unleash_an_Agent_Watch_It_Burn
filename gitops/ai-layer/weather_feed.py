# ABOUTME: Current weather for a named city from Open-Meteo, served in-cluster to C7's get_weather (#642).
# ABOUTME: The one agent-namespace pod with internet egress, and all it can do is this lookup.
"""weather-feed: GET /current?city=<name> -> the current reading, as JSON.

The agent namespace is default-deny egress once the network layer is on, and Challenge 1 depends on that.
So the MCP server never calls the internet itself: it asks this service, which builds its own two Open-Meteo
URLs from a city name and returns four fields. A caller cannot point it anywhere else.

Open-Meteo needs no key. Measured 2026-10-28: the geocoding search returns name, admin1, country, latitude,
longitude; the forecast's `current` block returns temperature_2m (in the requested unit) and weather_code
(a WMO code), with an ISO observation time.

Errors are returned as errors: an unknown city is a 404, an upstream failure a 502. Nothing is invented.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 8

# WMO weather interpretation codes, as Open-Meteo documents them.
WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "light freezing drizzle",
    57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers", 85: "light snow showers",
    86: "snow showers", 95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with hail",
}

log = logging.getLogger("weather-feed")


class LookupError404(Exception):
    """The city name matched no place."""


def _get_json(url: str, params: dict) -> dict:
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=TIMEOUT) as r:
        return json.loads(r.read())


def current(city: str) -> dict:
    """Look up a city and return its current reading.

    Raises:
        LookupError404: no place matches the name.
        urllib.error.URLError, ValueError, KeyError: Open-Meteo failed or answered in an unexpected shape.
    """
    found = _get_json(GEOCODE, {"name": city, "count": 1, "language": "en", "format": "json"}).get("results")
    if not found:
        raise LookupError404(city)
    p = found[0]
    place = ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country")) if x)
    cur = _get_json(FORECAST, {"latitude": p["latitude"], "longitude": p["longitude"],
                               "current": "temperature_2m,weather_code", "temperature_unit": "fahrenheit"})["current"]
    temp_f = float(cur["temperature_2m"])
    code = int(cur["weather_code"])
    return {"place": place, "temp_f": round(temp_f, 1), "temp_c": round((temp_f - 32) * 5 / 9, 1),
            "conditions": WMO.get(code, f"WMO code {code}"), "observed": cur.get("time", "")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 (http.server's name)
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz":
            self._send(200, {"ok": True})
            return
        if url.path != "/current":
            self._send(404, {"error": "not found"})
            return
        city = (urllib.parse.parse_qs(url.query).get("city") or [""])[0].strip()[:100]
        if not city:
            self._send(400, {"error": "city is required"})
            return
        try:
            self._send(200, current(city))
        except LookupError404:
            self._send(404, {"error": f"no place matches {city!r}"})
        except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
            log.warning("upstream lookup for %r failed: %s", city, e)
            self._send(502, {"error": f"weather service unavailable: {e}"})

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s %s", self.address_string(), fmt % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    host = os.environ.get("WEATHER_FEED_HOST", "0.0.0.0")
    port = int(os.environ.get("WEATHER_FEED_PORT", "8080"))
    log.info("listening on %s:%d", host, port)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
