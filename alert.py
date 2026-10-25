import csv
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# --------------------------------------------------
# 1. Village settings
# --------------------------------------------------

VILLAGE = "Gowripatnam"
MANDAL = "Chodavaram"
DISTRICT = "Anakapalli"
STATE = "Andhra Pradesh"

LATITUDE = 17.8489
LONGITUDE = 82.92275

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime.now(IST)

STATE_FILE = Path("state.json")
HISTORY_FILE = Path("history.csv")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)


# --------------------------------------------------
# 2. Download the weather forecast
# --------------------------------------------------

def get_forecast():
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
        + urllib.parse.urlencode(parameters)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GowripatnamWeatherAlerts/1.0"},
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    hourly = data["hourly"]

    if not hourly.get("time"):
        raise ValueError("The weather API returned no hourly forecast.")

    return hourly


# --------------------------------------------------
# 3. Calculate risk from the next 24 forecast hours
# --------------------------------------------------

def calculate_risk(hourly):
    times = hourly["time"]
    rain = hourly["precipitation"]
    gusts = hourly["wind_gusts_10m"]

    current_hour = NOW.strftime("%Y-%m-%dT%H:00")

    # Find the first forecast hour at or after the current hour.
    start = next(
        (i for i, t in enumerate(times) if t >= current_hour),
        None,
    )

    if start is None:
        raise ValueError("Could not find the current forecast hour.")

    end = min(start + 24, len(times))

    if end - start < 12:
        raise ValueError("Not enough forecast hours were returned.")

    rain_total = sum(
        float(value or 0)
        for value in rain[start:end]
    )

    max_gust = max(
        float(value or 0)
        for value in gusts[start:end]
    )

    # Experimental thresholds, not official warnings.
    if rain_total >= 115.6 or max_gust >= 62:
        risk = "HIGH"
    elif rain_total >= 64.5 or max_gust >= 40:
        risk = "MEDIUM"
    elif rain_total >= 15:
        risk = "LOW"
    else:
        risk = "SAFE"

    return {
        "risk": risk,
        "rain_mm": round(rain_total, 1),
        "max_gust_kmh": round(max_gust, 1),
        "updated_ist": NOW.strftime("%d-%b-%Y %I:%M %p IST"),
    }


# --------------------------------------------------
# 4. Create a bilingual Telegram message
# --------------------------------------------------

def make_message(result, title="🌦️ WEATHER UPDATE"):
    risk = result["risk"]
    rain = result["rain_mm"]
    gust = result["max_gust_kmh"]
    updated = result["updated_ist"]

    if risk == "HIGH":
        english_status = "HIGH FORECAST RISK — Prepare and follow official instructions."
        telugu_status = "అధిక వాతావరణ ప్రమాద సూచన — సిద్ధంగా ఉండండి; అధికారిక సూచనలు పాటించండి."
    elif risk == "MEDIUM":
        english_status = "MEDIUM FORECAST RISK — Stay alert and prepare."
        telugu_status = "మధ్యస్థ వాతావరణ ప్రమాద సూచన — అప్రమత్తంగా ఉండి సిద్ధంగా ఉండండి."
    elif risk == "LOW":
        english_status = "LOW FORECAST RISK — Keep monitoring official updates."
        telugu_status = "తక్కువ వాతావరణ ప్రమాద సూచన — అధికారిక సమాచారాన్ని గమనించండి."
    else:
        english_status = "No threshold triggered by this experimental forecast."
        telugu_status = "ఈ ప్రయోగాత్మక అంచనాలో ప్రమాద పరిమితి దాటలేదు."

    return (
        f"📍 {VILLAGE}, {MANDAL}, {DISTRICT}\n"
        f"🌧️ {title}\n\n"
        f"🇮🇳 తెలుగు\n"
        f"{telugu_status}\n"
        f"వచ్చే 24 గంటల అంచనా వర్షపాతం: {rain} mm\n"
        f"గరిష్ఠ గాలి వేగపు ఉధృతి: {gust} km/h\n\n"
        f"🇬🇧 ENGLISH\n"
        f"{english_status}\n"
        f"Forecast rain next 24 hours: {rain} mm\n"
        f"Maximum forecast wind gust: {gust} km/h\n\n"
        f"🕒 Updated: {updated}\n\n"
        "⚠️ This is an experimental forecast, not an official warning.\n"
        "IMD / APSDMA instructions always take priority.\n"
        "Emergency assistance in India: 112."
    )


# --------------------------------------------------
# 5. Send a message to the Telegram channel
# --------------------------------------------------

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret."
        )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram rejected the message. Check the bot and channel settings."
        )

    logging.info("Telegram message sent successfully.")


# --------------------------------------------------
# 6. Read and save the previous forecast state
# --------------------------------------------------

def read_previous_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.warning("Previous state could not be read; starting fresh.")
        return {}


def save_state(result):
    state = {
        **result,
        "checked_at": NOW.isoformat(),
    }

    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_history(result):
    file_exists = HISTORY_FILE.exists()

    with HISTORY_FILE.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow([
                "updated_ist",
                "village",
                "risk",
                "rain_mm_next_24h",
                "max_gust_kmh",
            ])

        writer.writerow([
            result["updated_ist"],
            VILLAGE,
            result["risk"],
            result["rain_mm"],
            result["max_gust_kmh"],
        ])


# --------------------------------------------------
# 7. Run the alert system
# --------------------------------------------------

def main():
    logging.info(
        "Starting forecast check for %s, %s, %s.",
        VILLAGE,
        DISTRICT,
        STATE,
    )

    hourly = get_forecast()
    result = calculate_risk(hourly)

    logging.info(
        "Risk=%s, rain=%.1f mm, max gust=%.1f km/h.",
        result["risk"],
        result["rain_mm"],
        result["max_gust_kmh"],
    )

    previous = read_previous_state()
    previous_risk = previous.get("risk")

    # Manual workflow runs send a test message.
    # Scheduled runs do not send test messages.
    event_name = os.getenv("GITHUB_EVENT_NAME", "")

    if event_name == "workflow_dispatch":
        send_telegram(
            make_message(result, title="🧪 TELEGRAM DELIVERY TEST")
        )

    # Alert only when risk rises to a higher level.
    risk_order = {
        "SAFE": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
    }

    if (
        previous_risk in risk_order
        and risk_order[result["risk"]] > risk_order[previous_risk]
    ):
        send_telegram(
            make_message(result, title="🚨 WEATHER RISK INCREASE")
        )
    elif previous_risk is None:
        logging.info("No previous risk state exists; no escalation alert.")

    save_state(result)
    save_history(result)

    logging.info("Forecast check completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Weather alert run failed.")
        raise
