"""
ElevenLabs -> Telegram webhook relay.

Receives ElevenLabs post-call webhooks, checks whether the call's
data-collection field "whatsapp_requested" is true, and if so,
sends a formatted summary message to a Telegram group.

Calls where whatsapp_requested is not true are acknowledged (200 OK)
but no Telegram message is sent.
"""

import os
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---- Configuration (set these as environment variables on Render) ----
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")  # optional, for HMAC verification later
ISTANBUL_OFFSET_HOURS = int(os.environ.get("ISTANBUL_OFFSET_HOURS", "3"))  # Europe/Istanbul is UTC+3 (no DST since 2016)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def format_istanbul_time(unix_secs):
    """Convert a unix timestamp (seconds) to a readable Europe/Istanbul time string."""
    if not unix_secs:
        return "N/A"
    try:
        dt_utc = datetime.fromtimestamp(unix_secs, tz=timezone.utc)
        dt_istanbul = dt_utc + timedelta(hours=ISTANBUL_OFFSET_HOURS)
        return dt_istanbul.strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return "N/A"


def extract_call_record(payload):
    """
    ElevenLabs sometimes sends a single object, sometimes a list containing
    one object. Normalize to a single "data" dict, or None if not found.
    """
    if isinstance(payload, list):
        if not payload:
            return None
        payload = payload[0]

    if not isinstance(payload, dict):
        return None

    return payload.get("data")


def get_data_collection_value(data, field_name):
    """Safely pull a data_collection_results[field_name].value out of the call data."""
    try:
        results = data.get("analysis", {}).get("data_collection_results", {})
        field = results.get(field_name, {})
        return field.get("value")
    except AttributeError:
        return None


def build_telegram_message(data, whatsapp_requested, human_followup_needed):
    agent_name = data.get("agent_name", "Unknown agent")
    phone = (
        data.get("metadata", {})
        .get("phone_call", {})
        .get("external_number")
        or data.get("user_id")
        or "Unknown"
    )
    start_time_secs = data.get("metadata", {}).get("start_time_unix_secs")
    call_time = format_istanbul_time(start_time_secs)
    duration = data.get("metadata", {}).get("call_duration_secs", "N/A")
    reason = get_data_collection_value(data, "whatsapp_request_reason") or "N/A"
    summary = data.get("analysis", {}).get("transcript_summary", "N/A")
    conversation_id = data.get("conversation_id", "N/A")

    triggers = []
    if whatsapp_requested:
        triggers.append("WhatsApp Requested")
    if human_followup_needed:
        triggers.append("Human Follow-up Needed")
    trigger_label = " + ".join(triggers) if triggers else "Alert"

    message = (
        f"📞 *{trigger_label} — New Call*\n\n"
        f"🤖 Agent: {agent_name}\n"
        f"📱 Phone: {phone}\n"
        f"🕐 Time: {call_time} (Istanbul)\n"
        f"⏱ Duration: {duration}s\n\n"
        f"📲 WhatsApp requested: {'Yes' if whatsapp_requested else 'No'}\n"
        f"🙋 Human follow-up needed: {'Yes' if human_followup_needed else 'No'}\n\n"
        f"💬 WhatsApp reason: {reason}\n"
        f"📝 Summary: {summary}\n\n"
        f"🆔 {conversation_id}"
    )
    return message


def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID not configured.")
        return False

    try:
        response = requests.post(
            TELEGRAM_API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        if response.status_code != 200:
            logger.error("Telegram API error %s: %s", response.status_code, response.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.error("Failed to reach Telegram API: %s", exc)
        return False


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "service": "elevenlabs-telegram-webhook"})


@app.route("/webhook/elevenlabs", methods=["POST"])
def elevenlabs_webhook():
    payload = request.get_json(silent=True)

    if payload is None:
        logger.warning("Received non-JSON or empty payload.")
        # Still return 200 so ElevenLabs doesn't treat this as a failed delivery
        # for things like audio-only webhooks we don't care about.
        return jsonify({"status": "ignored", "reason": "no JSON payload"}), 200

    event_type = payload[0].get("type") if isinstance(payload, list) and payload else payload.get("type") if isinstance(payload, dict) else None

    if event_type and event_type != "post_call_transcription":
        logger.info("Ignoring webhook of type: %s", event_type)
        return jsonify({"status": "ignored", "reason": f"event type {event_type}"}), 200

    data = extract_call_record(payload)
    if data is None:
        logger.warning("Could not find call data in payload.")
        return jsonify({"status": "ignored", "reason": "no data field found"}), 200

    whatsapp_requested = get_data_collection_value(data, "whatsapp_requested")
    human_followup_needed = get_data_collection_value(data, "human_followup_needed")

    conversation_id = data.get("conversation_id", "unknown")
    logger.info(
        "Processed call %s — whatsapp_requested=%s, human_followup_needed=%s",
        conversation_id, whatsapp_requested, human_followup_needed,
    )

    if whatsapp_requested is True or human_followup_needed is True:
        message = build_telegram_message(data, whatsapp_requested, human_followup_needed)
        sent = send_telegram_message(message)
        if not sent:
            # Still return 200 to ElevenLabs — we don't want it to retry/disable
            # the webhook just because our Telegram delivery hiccuped.
            return jsonify({"status": "error", "reason": "telegram send failed"}), 200
        return jsonify({"status": "sent", "conversation_id": conversation_id}), 200

    return jsonify({"status": "filtered_out", "conversation_id": conversation_id}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
