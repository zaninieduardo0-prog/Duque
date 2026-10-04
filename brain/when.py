"""Entende datas e horas faladas em português: "amanhã às 9h", "sexta às
18:30", "dia 5 ao meio-dia", "hoje à noite às 8", "05/10 às 14h".

Devolve o momento e o texto que sobra (o assunto do lembrete).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

WEEKDAYS = {
    "segunda": 0, "segunda-feira": 0, "terca": 1, "terca-feira": 1, "quarta": 2, "quarta-feira": 2,
    "quinta": 3, "quinta-feira": 3, "sexta": 4, "sexta-feira": 4, "sabado": 5, "domingo": 6,
}
MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
    "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
DEFAULT_HOUR = 9


@dataclass(slots=True, frozen=True)
class When:
    moment: datetime
    rest: str


def _fold(text: str) -> str:
    """Minúsculas sem acentos, preservando o comprimento (para recortar o original)."""
    out = []
    for char in text.casefold():
        base = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode() or char
        out.append(base[0])
    return "".join(out)


_TIME_PATTERNS = (
    re.compile(r"\b(?:as|a|ao|pras|para as|pelas)?\s*meio[- ]dia(?:\s+e\s+meia)?\b"),
    re.compile(r"\b(?:a|à)?\s*meia[- ]noite\b"),
    re.compile(r"\b(?:as|a|pras|para as|pelas|por volta das)\s+(\d{1,2})(?:[:h](\d{2}))?\s*(?:h(?:oras?)?|hrs?)?(?:\s+e\s+(meia|\d{1,2}))?\b"),
    re.compile(r"\b(\d{1,2})[:h](\d{2})\b"),
    re.compile(r"\b(\d{1,2})\s*(?:h|hrs?|horas)\b"),
)
_PERIOD = re.compile(r"\b(?:da|de|pela|a|à)\s+(manha|tarde|noite|madrugada)\b|\b(hoje a noite|hoje a tarde|hoje de manha|amanha cedo)\b")
_DAY_PATTERNS = (
    re.compile(r"\bdepois de amanha\b"),
    re.compile(r"\bamanha\b"),
    re.compile(r"\bhoje\b"),
    re.compile(r"\b(?:na|no|nesta|neste|proxima|proximo)?\s*(segunda|terca|quarta|quinta|sexta)(?:-feira)?\b|\b(?:no|neste|proximo)?\s*(sabado|domingo)\b"),
    re.compile(r"\b(?:dia\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"),
    re.compile(r"\bdia\s+(\d{1,2})(?:\s+de\s+(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro))?\b"),
)


_RELATIVE = re.compile(
    r"\b(?:daqui a|daqui|em|dentro de)\s+(\d+(?:[.,]\d+)?|uma?|meia)\s*(minutos?|mins?|horas?|hrs?|h)\b"
    r"(?:\s+e\s+(\d+)\s*(?:minutos?|mins?))?"
)


def _relative(folded: str, text: str, now: datetime) -> When | None:
    """ "daqui a 2 horas", "em 30 minutos": antes virava 02:00 / ignorado."""
    match = _RELATIVE.search(folded)
    if not match:
        return None
    amount_text, unit = match.group(1), match.group(2)
    amount = {"um": 1.0, "uma": 1.0, "meia": 0.5}.get(amount_text)
    if amount is None:
        amount = float(amount_text.replace(",", "."))
    minutes = amount * (60 if unit.startswith("h") else 1)
    if match.group(3):
        minutes += int(match.group(3))
    if minutes <= 0:
        return None
    start, end = match.span()
    rest = re.sub(r"\s+", " ", text[:start] + " " + text[end:]).strip(" ,.!?")
    return When(now + timedelta(minutes=minutes), rest)


def parse_when(text: str, now: datetime | None = None) -> When | None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    folded = _fold(text)
    relative = _relative(folded, text, now)
    if relative is not None:
        return relative
    spans: list[tuple[int, int]] = []

    # horário ---------------------------------------------------------------
    hour: int | None = None
    minute = 0
    for index, pattern in enumerate(_TIME_PATTERNS):
        match = pattern.search(folded)
        if not match:
            continue
        spans.append(match.span())
        if index == 0:
            hour, minute = 12, 30 if "meia" in match.group(0).split("dia")[-1] else 0
        elif index == 1:
            hour, minute = 0, 0
        else:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.lastindex and match.lastindex >= 2 and match.group(2) else 0
            if index == 2 and match.group(3):
                minute = 30 if match.group(3) == "meia" else int(match.group(3))
        break

    period = _PERIOD.search(folded)
    if period:
        spans.append(period.span())
        name = period.group(1) or period.group(2)
        if hour is not None and hour < 12 and any(word in name for word in ("tarde", "noite")):
            hour += 12
        if hour is None:
            hour = {"manha": 9, "tarde": 15, "noite": 20, "madrugada": 3, "cedo": 7}.get(name.split()[-1], DEFAULT_HOUR)

    if hour is not None and not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    # dia -------------------------------------------------------------------
    day: datetime | None = None
    for index, pattern in enumerate(_DAY_PATTERNS):
        match = pattern.search(folded)
        if not match:
            continue
        spans.append(match.span())
        today = now.replace(hour=0, minute=0)
        if index == 0:
            day = today + timedelta(days=2)
        elif index == 1:
            day = today + timedelta(days=1)
        elif index == 2:
            day = today
        elif index == 3:
            target = WEEKDAYS[match.group(1) or match.group(2)]
            ahead = (target - now.weekday()) % 7
            day = today + timedelta(days=ahead)
            effective = (hour, minute) if hour is not None else (DEFAULT_HOUR, 0)
            if ahead == 0 and effective <= (now.hour, now.minute):
                day += timedelta(days=7)  # "sexta" dita numa sexta à tarde é a próxima sexta
        elif index == 4:
            day_number, month = int(match.group(1)), int(match.group(2))
            year = int(match.group(3)) if match.group(3) else now.year
            year += 2000 if year < 100 else 0
            try:
                day = datetime(year, month, day_number)
            except ValueError:
                return None
            if day.date() < now.date() and not match.group(3):
                day = day.replace(year=year + 1)
        else:
            day_number = int(match.group(1))
            month = MONTHS[match.group(2)] if match.group(2) else now.month
            try:
                day = datetime(now.year, month, day_number)
            except ValueError:
                return None
            if day.date() < now.date():
                if match.group(2):
                    day = day.replace(year=now.year + 1)
                else:
                    next_month = now.month % 12 + 1
                    try:
                        day = datetime(now.year + (now.month == 12), next_month, day_number)
                    except ValueError:
                        return None
        break

    if day is None and hour is None:
        return None
    if day is None:
        moment = now.replace(hour=hour or 0, minute=minute)
        if moment <= now:
            moment += timedelta(days=1)
    else:
        moment = day.replace(hour=DEFAULT_HOUR if hour is None else hour, minute=minute)

    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    rest = text
    for start, end in reversed(merged):
        rest = rest[:start] + " " + rest[end:]
    rest = re.sub(r"\s+", " ", rest).strip(" ,.!?")
    return When(moment, rest)


def describe_moment(moment: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    days = (moment.date() - now.date()).days
    time_text = "meio-dia" if (moment.hour, moment.minute) == (12, 0) else f"{moment:%H:%M}"
    if days == 0:
        label = "hoje"
    elif days == 1:
        label = "amanhã"
    elif days == 2:
        label = "depois de amanhã"
    elif 0 < days < 7:
        label = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][moment.weekday()]
    else:
        label = f"dia {moment.day:02d}/{moment.month:02d}"
    return f"{label} às {time_text}" if time_text != "meio-dia" else f"{label} ao meio-dia"
