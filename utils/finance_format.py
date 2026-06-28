from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import os
import re
import unicodedata

import config


logger = logging.getLogger(__name__)


def normalize_text(text):
    if not text:
        return ""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    return text.encode("ascii", "ignore").decode("utf-8")


def parse_number(value):
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value or "").strip().replace(" ", "")
    if not text:
        return 0.0

    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in ["-", ".", ","]:
        return 0.0

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif "." in text:
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
            text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        logger.warning("Could not parse number '%s'. Falling back to 0.0", value)
        return 0.0


def timezone_name():
    try:
        return getattr(config, "TIMEZONE", os.getenv("TIMEZONE", "America/Lima"))
    except Exception:
        return os.getenv("TIMEZONE", "America/Lima")


def get_now(tz_name=None):
    name = tz_name or timezone_name() or "America/Lima"
    try:
        timezone = ZoneInfo(name)
    except Exception:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone)


def now_str(fmt="%Y-%m-%d %H:%M:%S", tz_name=None):
    return get_now(tz_name).strftime(fmt)


def parse_date(value):
    if isinstance(value, datetime):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        pass

    formats = [
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_field(record, *keys, default=""):
    for key in keys:
        if key in record:
            return record.get(key)
    return default
