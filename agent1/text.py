from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into", "is", "it", "its",
    "of", "on", "or", "that", "the", "their", "this", "to", "was", "were", "will", "with", "after", "before", "over",
    "der", "die", "das", "und", "in", "im", "mit", "auf", "für", "von", "zu", "zum", "zur", "ist", "sich", "nicht",
    "een", "de", "het", "een", "van", "met", "op", "voor", "door", "bij", "zijn", "wordt", "niet", "dat", "die",
}

COUNTRY_PATTERNS = {
    "United States": r"\b(?:united states|u\.s\.|u\. s\.|\bus\b|american)\b",
    "China": r"\b(?:china|chinese)\b",
    "Germany": r"\b(?:germany|german|deutschland)\b",
    "Netherlands": r"\b(?:netherlands|dutch|nederland)\b",
    "United Kingdom": r"\b(?:united kingdom|u\.k\.|\buk\b|britain|british)\b",
    "Russia": r"\b(?:russia|russian)\b",
    "India": r"\bindia\b",
    "Japan": r"\bjapan\b",
    "Canada": r"\bcanada\b",
    "France": r"\bfrance\b",
    "Italy": r"\bitaly\b",
    "Spain": r"\bspain\b",
    "Australia": r"\baustralia\b",
    "Brazil": r"\bbrazil\b",
    "Mexico": r"\bmexico\b",
    "South Korea": r"\b(?:south korea|korean)\b",
    "Taiwan": r"\btaiwan\b",
}

GENERIC_ENTITIES = {
    "the", "this", "that", "after", "before", "us", "u.s.", "u.s", "wall street", "dow", "nasdaq",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "reuters", "cnbc", "afp", "bloomberg",
}
GENERIC_ENTITY_WORDS = GENERIC_ENTITIES | {
    "hit", "with", "after", "as", "at", "by", "for", "from", "into", "over", "amid", "about",
    "investors", "investor", "allege", "alleged", "alleges", "company", "companies", "hid", "stock",
    "stocks", "share", "shares", "plunge", "falls", "fall", "fell", "rises", "rose", "why", "what",
    "open", "higher", "lower", "trading", "premarket", "report", "reports", "update", "digest",
    "says", "said", "files", "filed", "faces", "faced", "after", "before", "near", "hits", "hit",
}
ENTITY_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Za-z0-9&.\-']+(?:\s+[A-Z][A-Za-z0-9&.\-']+){0,3})")
NUMBER_RE = re.compile(r"(?<![\w])(\d+(?:[.,]\d+)*(?:\s?(?:%|billion|million|trillion|bn|mn|tn|bps|points?))?)", re.I)
SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|\Z)")


def normalize_ws(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", " ", text).strip()


def parse_timestamp(value: object) -> datetime:
    if value is None or value == "":
        raise ValueError("missing timestamp")
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = normalize_ws(str(value)).replace("Z", "+00:00")
    text = re.sub(r"(\.\d{7,})(\+|-)", lambda m: m.group(1)[:7] + m.group(2), text)
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch))


def tokenize(text: str, remove_stopwords: bool = True) -> list[str]:
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9][a-zA-ZÀ-ÿ0-9\-']+", fold(text))
    if remove_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
    return tokens


def build_gazetteer(texts: Iterable[str]) -> set[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        for match in ENTITY_RE.finditer(text):
            parts = normalize_ws(match.group(1)).split()
            trimmed: list[str] = []
            for part in parts:
                if fold(part) in GENERIC_ENTITY_WORDS:
                    break
                trimmed.append(part)
            for size in (1, 2, 3):
                if len(trimmed) >= size:
                    phrase = fold(" ".join(trimmed[:size]))
                    if len(phrase) > 2:
                        counts[phrase] += 1
    return {phrase for phrase, count in counts.items() if count >= 3}


def extract_entities(text: str, gazetteer: set[str] | None = None) -> list[str]:
    if gazetteer is not None:
        folded = fold(text)
        found = []
        for phrase in sorted(gazetteer, key=len, reverse=True):
            if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", folded) and phrase not in found:
                found.append(phrase)
        return found
    found: list[str] = []
    for match in ENTITY_RE.finditer(text):
        value = normalize_ws(match.group(1))
        parts = value.split()
        if any(fold(part) in GENERIC_ENTITY_WORDS for part in parts):
            continue
        value = re.sub(r"\s+(?:says|said|reports|reported|files|filed)$", "", value, flags=re.I)
        value = re.sub(r"'s$", "", value, flags=re.I)
        if len(value) < 3:
            continue
        if value not in found:
            found.append(value)
    return found


def numeric_signature(text: str) -> list[str]:
    values = []
    for match in NUMBER_RE.finditer(text):
        value = normalize_ws(match.group(1)).replace(",", ".")
        value = re.sub(r"\s+", "", value)
        if value not in values:
            values.append(value)
    return sorted(values)


def country_mentions(text: str) -> list[str]:
    lowered = fold(text)
    found = []
    for country, pattern in COUNTRY_PATTERNS.items():
        if re.search(pattern, lowered):
            found.append(country)
    return found


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    result = []
    for match in SENTENCE_RE.finditer(text or ""):
        span = normalize_ws(match.group(0))
        if len(span) < 30:
            continue
        start = text.find(span, match.start())
        if start < 0:
            continue
        end = start + len(span)
        result.append((span, start, end))
    return result


def slugify(text: str, limit: int = 6) -> str:
    tokens = tokenize(text)
    tokens = [t for t in tokens if not t.isdigit()][:limit]
    return "-".join(tokens) if tokens else "event"


def local_embedding(text: str) -> dict[str, float]:
    features: dict[str, float] = {}
    words = tokenize(text)
    for token in words:
        features[f"w:{token}"] = features.get(f"w:{token}", 0.0) + 1.0
        padded = f"^{token}$"
        for i in range(len(padded) - 2):
            gram = padded[i : i + 3]
            features[f"g:{gram}"] = features.get(f"g:{gram}", 0.0) + 0.35
    for entity in extract_entities(text):
        key = f"e:{fold(entity)}"
        features[key] = features.get(key, 0.0) + 2.0
    for number in numeric_signature(text):
        key = f"n:{number}"
        features[key] = features.get(key, 0.0) + 2.0
    norm = math.sqrt(sum(v * v for v in features.values()))
    if norm:
        features = {k: v / norm for k, v in features.items()}
    return features


def cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def overlap_count(left: Iterable[str], right: Iterable[str]) -> int:
    return len(set(left) & set(right))


def extract_figures(text: str) -> list[dict[str, object]]:
    figures: list[dict[str, object]] = []
    pattern = re.compile(
        r"(?P<currency>[$€£])\s?(?P<amount>\d+(?:[.,]\d+)*)\s*(?P<scale>billion|million|trillion|bn|mn|tn)?"
        r"|(?P<percent>\d+(?:[.,]\d+)?\s?%)"
        r"|(?P<plain>\d+(?:[.,]\d+)?)\s*(?P<unit>bps|basis points|points|jobs|people|votes?|years?|days?)",
        re.I,
    )
    for match in pattern.finditer(text):
        raw = normalize_ws(match.group(0))
        currency = match.group("currency")
        amount = match.group("amount") or match.group("percent") or match.group("plain")
        numeric = None
        if amount:
            cleaned = amount.replace(",", "").rstrip("%").strip()
            try:
                numeric = float(cleaned)
            except ValueError:
                numeric = None
            if currency == "$":
                numeric = numeric / 1000 if numeric and match.group("scale") in {"billion", "bn"} else numeric
        unit = match.group("scale") or match.group("percent") or match.group("unit")
        figures.append(
            {
                "raw": raw,
                "value": numeric,
                "unit": normalize_ws(unit) if unit else None,
                "currency": currency,
                "context": normalize_ws(text[max(0, match.start() - 45) : match.end() + 45]),
            }
        )
    return figures
