"""
Gowripatnam Village Weather Alerts
----------------------------------
Forecast source: Open-Meteo
Notifications: Telegram Bot API
Timezone: Asia/Kolkata

IMPORTANT:
This script calculates experimental forecast risk.
It does not issue or replace official IMD/APSDMA warnings.
"""

import argparse
import csv
import json
import logging
import os
import sys

from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


# =========================================================
# 1. CONFIGURATION
# =========================================================

LOCATION = "Gowripatnam, Anakapalli, Andhra Pradesh"
LATITUDE = 17.8489
LONGITUDE = 82.92275
TIMEZONE = ZoneInfo("Asia/Kolkata")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

STATE_FILE = Path("state.json")
HISTORY_FILE = Path("history.csv")

RISK_ORDER = {
    "SAFE": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
}

RISK_LABELS_EN = {
    "SAFE": "LOW FORECAST RISK",
    "LOW": "CAUTION",
    "MEDIUM": "ELEVATED FORECAST RISK",
    "HIGH": "HIGH FORECAST RISK",
}

RISK_LABELS_TE = {
    "SAFE": "తక్కువ వర్ష సూచన",
    "LOW": "జాగ్రత్త",
    "MEDIUM": "అధిక జాగ్రత్త",
    "HIGH": "అధిక అంచనా ప్రమాద స్థాయి",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)


# =========================================================
# 2. DOWNLOAD FORECAST
# =========================================================

def get_forecast():
    """Download hourly forecast data from Open-Meteo."""

    parameters = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": (
            "precipitation,"
            "wind_speed_10m,"
            "wind_gusts_10m"
        ),
        "wind_speed_unit": "kmh",
        "timezone": "Asia/Kolkata",
        "forecast_days": 7,
    }

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urlencode(parameters)
    )

    request = Request(
        url,
        headers={
            "User-Agent": "GowripatnamWeatherAlerts/1.0"
        },
    )

    with urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    if "hourly" not in data:
        raise ValueError("Forecast response has no hourly data.")

    hourly = data["hourly"]

    required = [
        "time",
        "precipitation",
        "wind_speed_10m",
        "wind_gusts_10m",
    ]

    for field in required:
        if field not in hourly:
            raise ValueError(f"Missing forecast field: {field}")

    length = len(hourly["time"])

    if length == 0:
        raise ValueError("Forecast contains no hourly records.")

    for field in required[1:]:
        if len(hourly[field]) != length:
            raise ValueError(f"Forecast arrays differ in length: {field}")

    return hourly


# =========================================================
# 3. CALCULATE NEXT-24-HOUR FORECAST RISK
# =========================================================

def calculate_weather(hourly):
    """Calculate experimental risk from the next 24 forecast hours."""

    now = datetime.now(TIMEZONE).replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    end = now + timedelta(hours=24)

    # Open-Meteo returns local timestamps without UTC offsets.
    start_local = now.replace(tzinfo=None)
    end_local = end.replace(tzinfo=None)

    selected = []

    for index, value in enumerate(hourly["time"]):
        timestamp = datetime.fromisoformat(value)

        if start_local <= timestamp < end_local:
            selected.append(index)

    if len(selected) < 20:
        raise ValueError(
            "Not enough forecast hours available for a 24-hour check."
        )

    def valid_number(value, field):
        if value is None:
            raise ValueError(
                f"Missing forecast value in {field}; "
                "cannot calculate risk reliably."
            )

        number = float(value)

        if number < 0:
            raise ValueError(f"Invalid negative value in {field}.")

        return number

    rainfall = sum(
        valid_number(hourly["precipitation"][i], "precipitation")
        for i in selected
    )

    max_gust = max(
        valid_number(hourly["wind_gusts_10m"][i], "wind_gusts_10m")
        for i in selected
    )

    max_wind = max(
        valid_number(hourly["wind_speed_10m"][i], "wind_speed_10m")
        for i in selected
    )

    # Experimental thresholds used by this project.
    # These are NOT official government warning categories.
    if rainfall >= 115.6 or max_gust >= 62:
        risk = "HIGH"
    elif rainfall >= 64.5 or max_gust >= 40:
        risk = "MEDIUM"
    elif rainfall >= 15:
        risk = "LOW"
    else:
        risk = "SAFE"

    return {
        "risk": risk,
        "rain_mm": round(rainfall, 1),
        "max_gust_kmh": round(max_gust, 1),
        "max_wind_kmh": round(max_wind, 1),
        "forecast_hours_checked": len(selected),
        "updated_ist": datetime.now(TIMEZONE).isoformat(
            timespec="seconds"
        ),
    }


# =========================================================
# 4. BUILD BILINGUAL MESSAGE
# =========================================================

def build_message(weather, reason):
    """Create a Telugu-first, English-second Telegram message."""

    risk = weather["risk"]
    rainfall = weather["rain_mm"]
    gust = weather["max_gust_kmh"]
    updated = weather["updated_ist"]

    return (
        "🌦️ గ్రామ వాతావరణ సమాచారం\n"
        "GOWRIPATNAM WEATHER UPDATE\n\n"

        f"📍 {LOCATION}\n"
        f"⚠️ స్థాయి: {RISK_LABELS_TE[risk]}\n"
        f"🌧️ తదుపరి 24 గంటల అంచనా వర్షం: {rainfall} mm\n"
        f"💨 గరిష్ఠ గాలి ఉధృతి అంచనా: {gust} km/h\n\n"

        "ఇది వాతావరణ మోడల్ ఆధారిత అంచనా మాత్రమే; "
        "అధికారిక హెచ్చరిక కాదు.\n"
        "తాజా IMD/APSDMA హెచ్చరికలు, స్థానిక అధికారుల "
        "సూచనలు తప్పనిసరిగా పాటించండి.\n"
        "🚨 అత్యవసర సహాయం: 112\n\n"

        "━━━━━━━━━━━━━━━━\n\n"

        "🌦️ ENGLISH WEATHER UPDATE\n"
        f"📍 {LOCATION}\n"
        f"⚠️ Forecast level: {RISK_LABELS_EN[risk]}\n"
        f"🌧️ Forecast rainfall next 24 hours: {rainfall} mm\n"
        f"💨 Maximum forecast wind gust: {gust} km/h\n\n"

        "This is an experimental model forecast, not an official warning.\n"
        "Follow the latest IMD/APSDMA warnings and local authorities.\n"
        "🚨 Emergency: 112\n\n"

        f"🕒 Updated: {updated}\n"
        f"ℹ️ Reason: {reason}"
    )


# =========================================================
# 5. READ AND SAVE STATE
# =========================================================

def read_state():
    """Read the previous successful run's state."""

    if not STATE_FILE.exists():
        return {}

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        if not isinstance(state, dict):
            raise ValueError("State file must contain a JSON object.")

        return state

    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise RuntimeError(
            f"Cannot read {STATE_FILE}: {error}"
        ) from error


def save_state(weather):
    """Save the latest processed forecast."""

    STATE_FILE.write_text(
        json.dumps(weather, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# =========================================================
# 6. SEND TELEGRAM MESSAGE
# =========================================================

def send_telegram(message):
    """Send a message and verify Telegram accepted it."""

    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN secret.")

    if not CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_CHAT_ID secret.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = urlencode({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        # Do not log the request URL: it contains the secret token.
        raise RuntimeError(
            "Telegram API rejected the message. "
            "Check the bot token, channel username and bot permissions."
        )

    logging.info("Telegram accepted the message.")


# =========================================================
# 7. RECORD FORECAST HISTORY
# =========================================================

def save_history(weather, reason):
    """Append a row to the forecast history CSV."""

    columns = [
        "updated_ist",
        "location",
        "risk",
        "rain_mm_next_24h",
        "max_gust_kmh",
        "max_wind_kmh",
        "reason",
    ]

    file_exists = HISTORY_FILE.exists()

    with HISTORY_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(file, fieldnames=columns)

        if not file_exists or HISTORY_FILE.stat().st_size == 0:
            writer.writeheader()

        writer.writerow({
            "updated_ist": weather["updated_ist"],
            "location": LOCATION,
            "risk": weather["risk"],
            "rain_mm_next_24h": weather["rain_mm"],
            "max_gust_kmh": weather["max_gust_kmh"],
            "max_wind_kmh": weather["max_wind_kmh"],
            "reason": reason,
        })


# =========================================================
# 8. MAIN WORKFLOW
# =========================================================

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--daily-summary",
        action="store_true",
        help="Send a daily forecast summary even if risk is unchanged.",
    )

    args = parser.parse_args()

    logging.info("Starting forecast check for %s.", LOCATION)

    # Validate credentials before doing any work.
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "in GitHub Actions Secrets."
        )

    # Fetch and validate the forecast.
    hourly = get_forecast()
    weather = calculate_weather(hourly)

    # Read state only after the forecast is valid.
    previous = read_state()
    previous_risk = previous.get("risk")

    current_risk = weather["risk"]

    logging.info(
        "Risk=%s, rain=%s mm, max gust=%s km/h.",
        current_risk,
        weather["rain_mm"],
        weather["max_gust_kmh"],
    )

    # First run: notify only if the calculated risk is elevated.
    if previous_risk is None:
        should_alert = current_risk in ("MEDIUM", "HIGH")
        reason = "Initial elevated forecast"

    else:
        if previous_risk not in RISK_ORDER:
            raise RuntimeError(
                "Unknown risk in saved state; inspect state.json."
            )

        should_alert = (
            RISK_ORDER[current_risk] > RISK_ORDER[previous_risk]
        )

        reason = (
            f"Forecast risk increased: "
            f"{previous_risk} → {current_risk}"
        )

    # A scheduled daily summary can be sent even if risk is unchanged.
    if args.daily_summary:
        should_alert = True
        reason = "Scheduled daily forecast summary"

    # Send first. If sending fails, state is not advanced,
    # allowing the next scheduled run to retry the alert.
    if should_alert:
        message = build_message(weather, reason)
        send_telegram(message)
        logging.info("Alert sent.")
    else:
        logging.info("No new alert required.")

    # Record history and save state after successful processing.
    save_history(weather, reason)
    save_state(weather)

    logging.info("Forecast check completed successfully.")


# =========================================================
# 9. ENTRY POINT AND ERROR HANDLING
# =========================================================

if __name__ == "__main__":
    try:
        main()

    except (HTTPError, URLError, TimeoutError) as error:
        logging.error(
            "Network/API request failed: %s",
            type(error).__name__,
        )
        sys.exit(1)

    except (ValueError, KeyError, RuntimeError, OSError) as error:
        logging.error("%s", error)
        sys.exit(1)

    except Exception:
        # Avoid printing request details or credentials in logs.
        logging.exception("Unexpected failure.")
        sys.exit(1)
