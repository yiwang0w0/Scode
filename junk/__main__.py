"""Allow ``python -m junk`` to behave like the ``junk`` console script."""

import sys

from junk.cli import main

if __name__ == "__main__":
    sys.exit(main())
