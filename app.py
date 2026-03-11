import json
import os
import re
import time
import requests
from datetime import datetime, date
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CACHE = {}
CACHE_TTL = 900  # 15 minutes

# Load location-specific config
_config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(_config_path) as _f:
    CONFIG = json.load(_f)

LOCATION_NAME     = CONFIG["location_name"]
NWS_POINTS_URL    = f"https://api.weather.gov/points/{CONFIG['nws_lat']},{CONFIG['nws_lon']}"
MARINE_ALERTS_URL = f"https://api.weather.gov/alerts/active?zone={CONFIG['marine_zone']}"
TIDES_URL = (
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    f"?station={CONFIG['tides_station_id']}&product=predictions&datum=MLLW"
    "&time_zone=lst_ldt&interval=hilo&units=english"
    "&application=weather&format=json"
    "&range=24&begin_date={today}"
)

WU_STATION      = CONFIG["wu_station_id"]
WU_DASH_URL     = f"https://www.wunderground.com/dashboard/pws/{WU_STATION}"
WU_OBS_BASE_URL = "https://api.weather.com/v2/pws/observations/current?format=json&units=e&numericPrecision=decimal"
WU_KEY_TTL      = 21600  # re-scrape API key every 6 hours

WU_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

HEADERS = {"User-Agent": "weather-dashboard"}


def cached_get(url):
    now = time.time()
    if url in CACHE:
        data, ts = CACHE[url]
        if now - ts < CACHE_TTL:
            return data
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    CACHE[url] = (data, now)
    return data


def get_nws_urls():
    points = cached_get(NWS_POINTS_URL)
    props = points["properties"]
    return props["forecastHourly"], props["observationStations"]


def feels_like(temp_f, wind_mph, humidity_pct):
    """Return wind chill or heat index, whichever applies, else None."""
    if temp_f is None:
        return None
    if temp_f <= 50 and wind_mph is not None and wind_mph >= 3:
        wc = (35.74 + 0.6215*temp_f - 35.75*(wind_mph**0.16)
              + 0.4275*temp_f*(wind_mph**0.16))
        return round(wc, 1)
    if temp_f >= 80 and humidity_pct is not None:
        h = humidity_pct
        hi = (-42.379 + 2.04901523*temp_f + 10.14333127*h
              - 0.22475541*temp_f*h - 0.00683783*temp_f**2
              - 0.05481717*h**2 + 0.00122874*temp_f**2*h
              + 0.00085282*temp_f*h**2 - 0.00000199*temp_f**2*h**2)
        return round(hi, 1)
    return None


def deg_to_cardinal(deg):
    if deg is None:
        return None
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[round(deg / 22.5) % 16]


def get_noaa_conditions(stations_url):
    stations = cached_get(stations_url)
    station_id = stations["features"][0]["properties"]["stationIdentifier"]
    obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
    obs = cached_get(obs_url)
    p = obs["properties"]

    def val(field):
        v = p.get(field, {})
        return v.get("value") if isinstance(v, dict) else v

    temp_c   = val("temperature")
    wind_ms  = val("windSpeed")
    gusts_ms = val("windGust")
    wind_deg = val("windDirection")

    return {
        "source":                 "noaa",
        "station":                station_id,
        "timestamp":              p.get("timestamp"),
        "temperature_f":          round(temp_c * 9/5 + 32, 1) if temp_c is not None else None,
        "humidity_pct":           val("relativeHumidity"),
        "wind_speed_mph":         round(wind_ms  * 2.23694, 1) if wind_ms  is not None else None,
        "wind_gust_mph":          round(gusts_ms * 2.23694, 1) if gusts_ms is not None else None,
        "wind_direction_deg":     wind_deg,
        "wind_direction_cardinal": deg_to_cardinal(wind_deg),
        "barometric_pressure_mb": round(val("barometricPressure") / 100, 1)
                                  if val("barometricPressure") else None,
        "visibility_miles":       round(val("visibility") * 0.000621371, 1)
                                  if val("visibility") else None,
        "description":            p.get("textDescription"),
        "dewpoint_f":             round(val("dewpoint") * 9/5 + 32, 1)
                                  if val("dewpoint") is not None else None,
        "feels_like_f":           feels_like(
                                      round(temp_c * 9/5 + 32, 1) if temp_c is not None else None,
                                      round(wind_ms * 2.23694, 1) if wind_ms is not None else None,
                                      val("relativeHumidity"),
                                  ),
    }


def get_wu_api_key():
    """Scrape WU's embedded API key from their dashboard page. Cached 6 hrs."""
    cache_key = "_wu_api_key"
    now = time.time()
    if cache_key in CACHE:
        key, ts = CACHE[cache_key]
        if now - ts < WU_KEY_TTL:
            return key
    resp = requests.get(WU_DASH_URL, headers=WU_SCRAPE_HEADERS, timeout=20)
    resp.raise_for_status()
    m = re.search(r'apiKey["\s:=]+([a-f0-9]{32})', resp.text)
    if not m:
        raise ValueError("Could not scrape WU API key from dashboard page")
    key = m.group(1)
    CACHE[cache_key] = (key, now)
    return key


def get_wunderground_conditions():
    api_key = get_wu_api_key()
    url = f"{WU_OBS_BASE_URL}&stationId={WU_STATION}&apiKey={api_key}"
    data = cached_get(url)
    obs  = data["observations"][0]
    imp  = obs["imperial"]
    deg  = obs.get("winddir")
    pressure_mb = round(imp["pressure"] * 33.8639, 1) if imp.get("pressure") else None
    return {
        "source":                  "wunderground",
        "station":                 obs.get("stationID", WU_STATION),
        "neighborhood":            obs.get("neighborhood"),
        "timestamp":               obs.get("obsTimeLocal"),
        "temperature_f":           imp.get("temp"),
        "humidity_pct":            obs.get("humidity"),
        "wind_speed_mph":          imp.get("windSpeed"),
        "wind_gust_mph":           imp.get("windGust"),
        "wind_direction_deg":      deg,
        "wind_direction_cardinal": deg_to_cardinal(deg),
        "barometric_pressure_mb":  pressure_mb,
        "visibility_miles":        None,
        "description":             None,
        "dewpoint_f":              imp.get("dewpt"),
        "feels_like_f":            feels_like(
                                       imp.get("temp"),
                                       imp.get("windSpeed"),
                                       obs.get("humidity"),
                                   ),
    }


def get_hourly_forecast(hourly_url):
    data = cached_get(hourly_url)
    result = []
    for p in data["properties"]["periods"][:12]:
        result.append({
            "start_time":                 p["startTime"],
            "temperature_f":              p["temperature"],
            "wind_speed":                 p["windSpeed"],
            "wind_direction":             p["windDirection"],
            "short_forecast":             p["shortForecast"],
            "probability_of_precipitation": p.get("probabilityOfPrecipitation", {}).get("value"),
        })
    return result


def get_tides():
    today = date.today().strftime("%Y%m%d")
    data  = cached_get(TIDES_URL.format(today=today))
    return [
        {"time": p["t"], "height_ft": float(p["v"]), "type": "High" if p["type"] == "H" else "Low"}
        for p in data.get("predictions", [])
    ]


def get_marine_alerts():
    data = cached_get(MARINE_ALERTS_URL)
    return [
        {
            "event":       f["properties"].get("event"),
            "headline":    f["properties"].get("headline"),
            "severity":    f["properties"].get("severity"),
            "expires":     f["properties"].get("expires"),
        }
        for f in data.get("features", [])
    ]


@app.route("/api/weather")
def weather():
    source = request.args.get("source", "noaa")
    try:
        hourly_url, stations_url = get_nws_urls()

        if source == "wu":
            current = get_wunderground_conditions()
        else:
            current = get_noaa_conditions(stations_url)

        return jsonify({
            "location":             LOCATION_NAME,
            "generated_at":         datetime.utcnow().isoformat() + "Z",
            "source":               source,
            "current_conditions":   current,
            "hourly_forecast":      get_hourly_forecast(hourly_url),
            "tide_predictions_24hr": get_tides(),
            "marine_alerts":        get_marine_alerts(),
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5090, debug=False)
