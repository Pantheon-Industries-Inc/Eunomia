# Eunomia gate entrypoints. Local == CI == Hermes.
#
# The five Python gates below are the VERBATIM Hermes commands in Hermes order.
# `make gates` runs every BLOCKING gate. Non-blocking in Run 0a (OQ-13): the esp32
# target build and clang-tidy — wired in `gates-cpp-nonblocking` + CI (continue-on-error).

PIO ?= pio
# Hand-written firmware C++ only — prune .pio/ (downloaded libs) and contracts/_generated (codegen).
CPP_FILES := $(shell find firmware -path '*/.pio' -prune -o \( -name '*.cpp' -o -name '*.cc' -o -name '*.h' -o -name '*.hpp' \) -print 2>/dev/null)

.PHONY: gates gates-python gates-cpp gates-cpp-nonblocking codegen drift camera-image-checksum help

help:
	@echo "make gates                 - all BLOCKING gates (python + cpp + drift)"
	@echo "make gates-python          - the five Hermes python gates (verbatim, in order)"
	@echo "make gates-cpp             - clang-format + native build/test + checksum stub (blocking)"
	@echo "make gates-cpp-nonblocking - esp32 target build + clang-tidy (NON-blocking in 0a)"
	@echo "make codegen               - regenerate contracts/_generated from the neutral source"
	@echo "make drift                 - codegen + assert contracts/_generated is unchanged"

gates: gates-python gates-cpp drift

# ---- Python: verbatim Hermes commands, Hermes order (pytest -> ruff -> mypy -> imports) ----
gates-python:
	uv run pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run lint-imports

# ---- C++: blocking gates ----
gates-cpp:
	clang-format --dry-run -Werror $(CPP_FILES)
	$(PIO) test -e native -d firmware/coordinator
	$(MAKE) camera-image-checksum

# ---- C++: non-blocking in 0a (present, but does not gate); CI runs with continue-on-error ----
gates-cpp-nonblocking:
	-$(PIO) run -e esp32 -d firmware/coordinator
	@echo "clang-tidy: configured in .clang-tidy, non-blocking in 0a (flips on when coordinator/core/ lands)"

# ---- codegen + drift ----
codegen:
	uv run --no-project --with pyyaml python contracts/codegen/generate.py

drift: codegen
	git diff --exit-code contracts/_generated

# ---- camera-image checksum gate (no-op stub in 0a) ----
camera-image-checksum:
	python3 firmware/camera-image/checksum_gate.py
