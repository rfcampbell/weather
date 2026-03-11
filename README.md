# weather

Local weather dashboard powered by NOAA APIs. No API keys required. Configure your location in `config.json`.

## Data Sources

| Source | What |
|--------|------|
| NWS Points API | Current obs + hourly forecast (configured lat/lon) |
| NOAA Tides & Currents | Tide hi/lo predictions (configured station) |
| NWS Alerts | Marine alerts (configured zone) |

Responses cached in-memory for 15 minutes.

## Endpoints

- `GET /` — HTML weather dashboard
- `GET /api/weather` — JSON aggregated weather data

## Deploy

```bash
# Install
cd /opt/weather
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Systemd
sudo cp weather.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weather

# Nginx
sudo cp weather.nginx /etc/nginx/sites-available/weather
sudo ln -s /etc/nginx/sites-available/weather /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
# → http://localhost:5090
```
