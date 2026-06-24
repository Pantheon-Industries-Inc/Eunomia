"""eunomia_bench_harness — the engineering bench harness (Run 0a shell).

Two layers (built in a later run): a thin real serial/telnet IO shell, and a
hardware-free core that replays recorded logs so the gates are CI-able with no rig.
Depends only on ``eunomia_contracts`` (the dependency law).
"""

__version__ = "0.0.0"
