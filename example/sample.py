"""A small order-pricing module used to demonstrate junk round-trips."""

TAX_RATE = 0.08


def subtotal(items):
    """Return the sum of price * quantity across all line items."""
    total = 0.0
    for item in items:
        total += item["price"] * item["quantity"]
    return total


def apply_discount(amount, pct):
    """Apply a percentage discount; pct must be in [0, 100]."""
    if pct < 0 or pct > 100:
        raise ValueError("pct must be between 0 and 100")
    return amount * (1 - pct / 100.0)


def with_tax(amount):
    """Add sales tax to an amount."""
    return amount * (1 + TAX_RATE)


class Cart:
    """A tiny shopping cart."""

    def __init__(self):
        self.items = []

    def add(self, name, price, quantity=1):
        self.items.append({"name": name, "price": price, "quantity": quantity})
        return self

    def total(self, discount_pct=0):
        running = subtotal(self.items)
        running = apply_discount(running, discount_pct)
        return round(with_tax(running), 2)
