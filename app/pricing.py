"""Server-side price list. The browser sends an amount, but the API only accepts the tier's price."""
from decimal import Decimal

TIER_PRICES: dict[str, Decimal] = {
    "basic": Decimal("10.00"),
    "deep": Decimal("20.00"),
    "deluxe": Decimal("30.00"),
}
