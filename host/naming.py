"""Reconhecimento do link e nome do arquivo.

As regras são as mesmas de extension/detect.js. tests/cases.json cobre os dois.
"""

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "extension" / "networks.json"
MEDIA_EXTENSION = re.compile(r"\.(mp4|mp3|zip|webm|mkv|m4a)$", re.IGNORECASE)
FORBIDDEN = re.compile(r"[\x00-\x1f:*?\"<>|]+")
MAX_SECONDS = 48 * 60 * 60
TIME_INVALID = "Tempo inválido. Use 1:30 ou 90,5."
TIME_NEGATIVE = "O tempo não pode ser negativo."
TIME_TOO_LONG = "O tempo fica acima de 48 horas."
TIME_ORDER = "O fim precisa ser depois do início."


class UserError(Exception):
    """Pedido que a pessoa pode corrigir."""


@dataclass(frozen=True)
class DownloadRequest:
    url: str
    quality: str
    filename: str
    compress: bool
    network_id: str
    start_time: float | None = None
    end_time: float | None = None


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))


def host_matches(hostname: str, pattern: str) -> bool:
    host = hostname.lower().removeprefix("www.")
    expected = pattern.lower().removeprefix("www.")
    return host == expected or host.endswith(f".{expected}")


def detect_network(url: str, catalog: dict) -> dict | None:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower().removeprefix("www.")
    for network in catalog["networks"]:
        if any(host_matches(hostname, pattern) for pattern in network["hosts"]):
            return {"id": network["id"], "label": network["label"]}
    return {"id": "outra", "label": "Outra rede"}


def auto_filename(network_id: str | None, moment: datetime) -> str:
    slug = network_id or "midia"
    return f"{slug}_{moment.strftime('%Y-%m-%d_%H-%M-%S')}"


def sanitize_filename(name: str) -> str:
    cleaned = str(name or "").strip()
    cleaned = cleaned.replace("\\", " ").replace("/", " ")
    cleaned = FORBIDDEN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    for _ in range(3):
        next_name = MEDIA_EXTENSION.sub("", cleaned)
        if next_name == cleaned:
            break
        cleaned = next_name.rstrip(" .")
    return cleaned[:80].rstrip(" .") or "midia"


def output_extension(quality: str, compress: bool) -> str:
    if compress:
        return ".zip"
    return ".mp3" if quality == "audio" else ".mp4"


def _as_seconds(value: Decimal) -> float:
    quantized = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if quantized < 0:
        raise UserError(TIME_NEGATIVE)
    if quantized > MAX_SECONDS:
        raise UserError(TIME_TOO_LONG)
    return float(quantized)


def parse_time(value: object) -> float | None:
    """Segundos. Aceita 90, 90,5, 1:30 e 1:02:03.5. Vazio significa o vídeo todo."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise UserError(TIME_INVALID)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise UserError(TIME_INVALID)
        return _as_seconds(Decimal(str(value)))
    text = value.strip().replace(",", ".")
    if not text:
        return None
    if text.startswith("-"):
        raise UserError(TIME_NEGATIVE)
    clock = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", text)
    if clock:
        hours = int(clock.group(1) or 0)
        minutes = int(clock.group(2))
        seconds = Decimal(clock.group(3))
        if clock.group(1) is not None and minutes >= 60:
            raise UserError(TIME_INVALID)
        if seconds >= 60:
            raise UserError(TIME_INVALID)
        return _as_seconds(Decimal(hours * 3600 + minutes * 60) + seconds)
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _as_seconds(Decimal(text))
    raise UserError(TIME_INVALID)


def format_time(seconds: float) -> str:
    """m:ss.ss, com o milésimo quando ele não é zero. A partir de 1 h, h:mm:ss.ss."""
    millis = int((Decimal(str(seconds)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if millis < 0:
        millis = 0
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, fraction = divmod(remainder, 1000)
    if fraction % 10:
        frac = f"{fraction:03d}"
    else:
        frac = f"{fraction // 10:02d}"
    body = f"{secs:02d}.{frac}"
    if hours:
        return f"{hours}:{minutes:02d}:{body}"
    return f"{minutes}:{body}"


def _youtube_host(hostname: str) -> bool:
    host = hostname.lower().removeprefix("www.")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com") or (
        host == "youtube-nocookie.com" or host.endswith(".youtube-nocookie.com")
    )


def _youtube_clock(text: str) -> float | None:
    cleaned = text.strip().replace(",", ".")
    if re.fullmatch(r"\d+(?:\.\d+)?s?", cleaned):
        return parse_time(cleaned[:-1] if cleaned.endswith("s") else cleaned)
    clock = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", cleaned)
    if clock is None or not any(clock.groups()):
        return None
    hours = int(clock.group(1) or 0)
    minutes = int(clock.group(2) or 0)
    seconds = Decimal(clock.group(3) or "0")
    return _as_seconds(Decimal(hours * 3600 + minutes * 60) + seconds)


def youtube_start(url: str) -> float | None:
    """Tempo do parâmetro t= ou start= de um link do YouTube. Fora isso, None."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if not _youtube_host(parsed.hostname):
        return None
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    raw = (query.get("t") or query.get("start") or fragment.get("t") or [None])[0]
    if not raw:
        return None
    try:
        return _youtube_clock(raw)
    except (UserError, ArithmeticError):
        return None


def parse_request(payload: object, catalog: dict, moment: datetime | None = None) -> DownloadRequest:
    if not isinstance(payload, dict):
        raise UserError("Pedido inválido.")
    url = payload.get("url")
    if not isinstance(url, str):
        raise UserError("Informe o link.")
    url = url.strip()
    if len(url) > 2000:
        raise UserError("O link é longo demais.")
    network = detect_network(url, catalog)
    if network is None:
        raise UserError("Use um link http ou https.")
    quality = payload.get("quality", "best")
    known = {item["id"] for item in catalog["qualities"]}
    if not isinstance(quality, str) or quality not in known:
        raise UserError("Qualidade desconhecida.")
    raw_name = payload.get("filename", "")
    if not isinstance(raw_name, str):
        raise UserError("O nome do arquivo é inválido.")
    filename = sanitize_filename(raw_name) if raw_name.strip() else auto_filename(
        network["id"], moment or datetime.now())
    compress = payload.get("compress", False)
    if not isinstance(compress, bool):
        raise UserError("O formato compactado precisa ser sim ou não.")
    start_time = parse_time(payload["start_time"]) if "start_time" in payload else None
    end_time = parse_time(payload["end_time"]) if "end_time" in payload else None
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise UserError(TIME_ORDER)
    return DownloadRequest(url, quality, filename, compress, network["id"], start_time, end_time)
