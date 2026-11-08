"""Deterministic language understanding for phone orders.

This is the last-resort brain: it works with no LLM at all, and it double-checks
what the LLM proposes. Prices never come from here or from the LLM, only from the menu.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

NUMBERS = {
    "a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "couple": 2, "pair": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12,
}
YES = re.compile(r"\b(yes|yeah|yep|yup|sure|correct|right|confirm|sounds good|that'?s it|that is it|that'?s all|perfect|ok(ay)?|go ahead|done)\b", re.I)
NO = re.compile(r"\b(no|nope|not yet|wait|actually|change)\b", re.I)
REMOVE = re.compile(r"\b(remove|cancel|drop|take off|delete|without|no more)\b", re.I)
PAID = re.compile(r"\b(paid|i paid|done paying|payment (is )?(done|sent|complete)|finished paying|sent (it|the money))\b", re.I)
MENU_Q = re.compile(r"\b(menu|what do you (have|sell|got)|options|what('?s| is) good|recommend)\b", re.I)
SUPPORT = re.compile(r"\b(refund|wrong order|complain|complaint|problem|cold|missing|charged twice|dispute|manager)\b", re.I)
GOODBYE = re.compile(r"\b(bye|goodbye|that'?s all|hang up|thanks,? bye)\b", re.I)
TOTAL_Q = re.compile(r"\b(total|how much|price|cost)\b", re.I)
STOP = {"the", "a", "an", "and", "of", "please", "with", "some", "i", "want", "would", "like", "can", "get", "me", "order", "add", "also", "plus", "to", "id", "i'd"}


@dataclass
class Intent:
    kind: str  # order|remove|confirm|deny|paid|menu|support|goodbye|total|clarify|chat
    items: list[tuple[str, int]] = field(default_factory=list)  # (menu_item_id, qty)
    options: list[str] = field(default_factory=list)  # menu item ids when the caller was ambiguous


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _singular(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and w[:-2].endswith(("ch", "sh", "x", "s")):
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us")) and w not in ("plus", "this", "is", "yes", "was", "has", "its"):
        return w[:-1]
    return w


def _tokens(s: str) -> list[str]:
    return [_singular(w) for w in _norm(s).split()]


def _score(phrase: list[str], item: list[str]) -> float:
    """How well a chunk of caller words matches a menu item name (0..1)."""
    if not phrase:
        return 0.0
    words = [w for w in phrase if w not in STOP]
    if not words:
        return 0.0
    hits = 0.0
    for w in words:
        best = max((SequenceMatcher(None, w, iw).ratio() for iw in item), default=0)
        hits += best if best >= 0.8 else 0
    coverage = hits / len(item)  # how much of the item name was said
    precision = hits / len(words)
    return 0.65 * coverage + 0.35 * precision


def _names_any(words: list[str], names: dict) -> bool:
    """True if any word already looks like part of a menu item name."""
    return any(SequenceMatcher(None, w, iw).ratio() >= 0.8 for w in words for n in names.values() for iw in n)


def extract_items(text: str, menu: list[dict], ambiguous: list | None = None) -> list[tuple[str, int]]:
    """Find "2 carne asada tacos and a horchata" -> [(id, 2), (id, 1)].
    Chunks that match several items equally well ("2 tacos") are reported in `ambiguous` instead."""
    toks = _tokens(text)
    names = {m["id"]: _tokens(m["name"]) for m in menu}
    found: dict[str, int] = {}
    # split on conjunctions/commas into chunks; each chunk is "<qty> <item words>"
    chunks, cur = [], []
    for t in toks:
        if t in ("and", "plus", "also", "with") and cur:
            chunks.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        chunks.append(cur)
    for chunk in chunks:
        qty, words = 1, []
        for t in chunk:
            m = re.fullmatch(r"x?(\d+)x?", t)
            if m and 0 < int(m.group(1)) <= 50:
                qty = int(m.group(1))
                if not _names_any(words, names):
                    words = []  # "hi can I get 2 ..." -> filler before the number is dropped
            elif t in NUMBERS and not _names_any(words, names):
                qty, words = NUMBERS[t], []
            else:
                words.append(t)
        scored = sorted(((_score(words, name), mid) for mid, name in names.items()), reverse=True)
        if not scored or scored[0][0] < 0.45:
            continue
        top = [mid for sc, mid in scored if sc >= 0.45 and scored[0][0] - sc < 0.05]
        if len(top) > 1:
            if ambiguous is not None:
                ambiguous.append((top, qty))
            continue
        found[top[0]] = found.get(top[0], 0) + qty
    return list(found.items())


def understand(text: str, menu: list[dict], stage: str) -> Intent:
    amb: list = []
    items = extract_items(text, menu, amb)
    if amb and not items and not REMOVE.search(text):
        return Intent("clarify", [], amb[0][0])
    if SUPPORT.search(text):
        return Intent("support")
    if items and REMOVE.search(text):
        return Intent("remove", items)
    if items:
        return Intent("order", items)
    if stage == "awaiting_payment" and PAID.search(text):
        return Intent("paid")
    if MENU_Q.search(text):
        return Intent("menu")
    if stage == "confirming" and YES.search(text):
        return Intent("confirm")
    if stage == "confirming" and NO.search(text):
        return Intent("deny")
    if TOTAL_Q.search(text):
        return Intent("total")
    if GOODBYE.search(text):
        return Intent("goodbye")
    if stage == "ordering" and YES.search(text):
        return Intent("confirm")  # "that's it" while ordering
    return Intent("chat")
