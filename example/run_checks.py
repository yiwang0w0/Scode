"""Behavioural checks for example/sample.py.

Used as the ``--tests`` gate when demonstrating junk:

    junk obfuscate example/sample.py --aggressive --tests "python example/run_checks.py"

Loads sample.py fresh from disk (so it picks up the obfuscated version) and
asserts the public behaviour is unchanged. Exits non-zero on any failure.
"""

import importlib.util
import math
import pathlib
import sys


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    sample = _load("sample_under_test", here / "sample.py")

    assert sample.TAX_RATE == 0.08

    items = [{"price": 2.0, "quantity": 3}, {"price": 1.5, "quantity": 2}]
    assert sample.subtotal(items) == 9.0

    assert sample.apply_discount(100, 10) == 90.0
    try:
        sample.apply_discount(100, 150)
    except ValueError:
        pass
    else:
        raise AssertionError("apply_discount should reject pct > 100")

    assert math.isclose(sample.with_tax(100), 108.0)

    cart = sample.Cart().add("widget", 10.0, 2).add("gadget", 5.0)
    # subtotal = 25, no discount, +8% tax => 27.0
    assert cart.total() == 27.0
    assert cart.total(discount_pct=20) == round(25 * 0.8 * 1.08, 2)

    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
