"""junk — a reversible legacy-mess obfuscator.

Inflate clean Python source into a deliberate maintenance nightmare to raise the
cost of casual reading and automated deconstruction, while keeping a byte-exact
snapshot in a local ``.junkmap/`` store so a single ``junk restore`` reconstructs
the original source verbatim.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
