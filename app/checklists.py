"""Checklist templates keyed on service_type (the three site tiers). A job gets a copy at booking time."""

# (label, required)
_BASIC = [
    ("Kitchen", True),
    ("Bathroom", True),
    ("Floors", True),
    ("Surfaces", True),
]
_DEEP = _BASIC + [
    ("Oven", False),
    ("Baseboards", False),
    ("Inside cabinets", False),
]
_DELUXE = _DEEP + [
    ("Inside refrigerator", False),
    ("Windows", False),
    ("Laundry folded", False),
]

CHECKLIST_TEMPLATES: dict[str, list[tuple[str, bool]]] = {
    "basic": _BASIC,
    "deep": _DEEP,
    "deluxe": _DELUXE,
}
