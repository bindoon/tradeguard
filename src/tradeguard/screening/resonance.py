"""Independent resonance votes for related screening strategies.

``box_breakout`` draws its box from closes. ``box_high_breakout`` draws the
same kind of box from highs and lows and then confirms with the close. They
often fire together, and the high-based rule is the stricter breakout test, so
they are one family: a stock that hits both still has one box vote.

``RULE_VERSION`` is part of the signal-portfolio plugin version. Increment it
when this vote or tie-break changes.
"""

from collections.abc import Iterable, Sequence

RULE_VERSION = "1"

BOX_FAMILY = "box_breakout"
STRATEGY_FAMILIES = {
    "box_breakout": BOX_FAMILY,
    "box_high_breakout": BOX_FAMILY,
}
PREFERRED_HIT = "box_high_breakout"


def family_of(name: str) -> str:
    return STRATEGY_FAMILIES.get(name, name)


def independent_votes(names: Iterable[str]) -> int:
    return len({family_of(name) for name in names})


def prefers_box_high(names: Iterable[str]) -> int:
    """Sort key fragment: 0 comes before 1 when the close-confirmed high breakout is present."""
    return 0 if PREFERRED_HIT in set(names) else 1


def rank_key(resonance: int, hits: Sequence[str], symbol: str) -> tuple[int, int, str]:
    return (-int(resonance), prefers_box_high(hits), symbol)


def ordered_hits(names: Sequence[str]) -> list[str]:
    """Keep scan order, but list the stricter box strategy ahead of its close-based sibling."""
    if PREFERRED_HIT not in names or "box_breakout" not in names:
        return list(names)
    ordered: list[str] = []
    placed = False
    for name in names:
        if name == PREFERRED_HIT:
            continue
        if name == "box_breakout" and not placed:
            ordered.append(PREFERRED_HIT)
            placed = True
        ordered.append(name)
    return ordered


def order_hit_details(details: Sequence[dict]) -> tuple[list[str], list[dict], int]:
    original = [str(item["strategy"]) for item in details]
    names = ordered_hits(original)
    by_name = {str(item["strategy"]): item for item in details}
    ordered = [by_name[name] for name in names]
    return names, ordered, independent_votes(names)


def shown_resonance(stored: int | None, hits: Sequence[str] | None) -> int:
    """Prefer the stored family count. Older rows left the column at 0 and still use their hits."""
    if stored:
        return int(stored)
    return independent_votes(list(hits or []))


def family_evidence(items: Sequence[tuple[str, bool | None]]) -> list[bool | None]:
    """Collapse one combination into family votes.

    A family is true when any member is true, unknown when none is true but one
    is unknown, and false only when every member is a known miss. ``all`` and
    ``at_least`` then count families, so the two box strategies are one vote.
    """
    grouped: dict[str, list[bool | None]] = {}
    order: list[str] = []
    for name, value in items:
        family = family_of(name)
        if family not in grouped:
            order.append(family)
            grouped[family] = []
        grouped[family].append(value)
    votes: list[bool | None] = []
    for family in order:
        values = grouped[family]
        if any(value is True for value in values):
            votes.append(True)
        elif any(value is None for value in values):
            votes.append(None)
        else:
            votes.append(False)
    return votes
