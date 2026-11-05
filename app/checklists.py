"""Checklist templates keyed on service_type. A job gets a copy at booking time."""

# (label, required)
CHECKLIST_TEMPLATES: dict[str, list[tuple[str, bool]]] = {
    "standard_clean": [
        ("Kitchen", True),
        ("Bathroom", True),
        ("Floors", True),
        ("Surfaces", True),
        ("Oven", False),
    ],
}
