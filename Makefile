# Eunomia gate entrypoints. Local == CI == Hermes.
#
# The five Python gates below are the VERBATIM Hermes commands in Hermes order.
# `make gates` runs every BLOCKING gate. Since Run F1 landed firmware/coordinator/core/, the esp32
# target build is now BLOCKING (OQ-13/F1-OQ-3: core/ is pure C++17 and must cross-compile for the
# ESP32 it will run on). Only clang-tidy stays non-blocking (flips on with transport/ui in F2) —
# wired in `gates-cpp-nonblocking` + CI (continue-on-error).

PIO ?= pio
# Hand-written firmware C++ only — prune .pio/ (downloaded libs) and contracts/_generated (codegen).
CPP_FILES := $(shell find firmware -path '*/.pio' -prune -o -path '*/vendor/*' -prune -o \( -name '*.cpp' -o -name '*.cc' -o -name '*.h' -o -name '*.hpp' \) -print 2>/dev/null)
# clang-tidy scope (OQ-11 / F3 FLAG-F): the framework-FREE hand-written logic where the two hard rules
# + the trigger core live — core/ + transport/proto/ (all clean under the enabled checks).
# transport/hw/ is Arduino-framework-coupled ("framework noise"), ui/ is framework-coupled too
# (TFT_eSPI), and transport/vendor/ is reference; all three are out of scope. core/ was DEFERRED in F2
# (its pre-existing performance-enum-size findings would have edited core/, out of F2's transport-only
# boundary); F3 cleared the 5 enums (explicit underlying type) and extends the blocking scope to core/
# here — the .cpp set below AND the .clang-tidy HeaderFilterRegex (the enums live in HEADERS, so both
# halves are required to actually catch them).
TIDY_FILES := $(shell find firmware/coordinator/core firmware/coordinator/transport/proto -name '*.cpp' 2>/dev/null)

.PHONY: gates gates-python gates-cpp gates-cpp-tidy gates-db codegen drift camera-image-checksum help

help:
	@echo "make gates                 - all BLOCKING gates (python + cpp + drift); needs NO database"
	@echo "make gates-python          - the five Hermes python gates (verbatim, in order)"
	@echo "make gates-cpp             - clang-format + native test + esp32 & cyd builds + tidy + checksum (blocking)"
	@echo "make gates-cpp-tidy        - clang-tidy (BLOCKING, scoped to core/ + transport/proto/)"
	@echo "make gates-db              - DB-backed edge/store tests (throwaway docker Postgres; loud-skip if absent)"
	@echo "make codegen               - regenerate contracts/_generated from the neutral source"
	@echo "make drift                 - codegen + assert contracts/_generated is unchanged"

gates: gates-python gates-cpp drift

# ---- DB-backed edge/store tests (Run S1) ----
# The default `make gates` needs NO database (the `db`-marked tests skip without a DSN). This target
# runs them: it uses EUNOMIA_STORE_TEST_DSN if set, else spins a throwaway docker Postgres, applies
# the migration via the test harness, runs the `db` tests, and tears the container down. Guarded on
# docker so a machine without it gets a LOUD skip, not a spurious break (the clang-tidy pattern); CI
# runs the same tests against a postgres SERVICE container instead.
EUNOMIA_PG_IMAGE ?= postgres:16
EUNOMIA_PG_CONTAINER ?= eunomia-store-test-pg
EUNOMIA_PG_PORT ?= 55432
gates-db:
	@if [ -n "$$EUNOMIA_STORE_TEST_DSN" ]; then \
	  echo "gates-db: using EUNOMIA_STORE_TEST_DSN from the environment"; \
	  uv run pytest edge/store -m db; \
	elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then \
	  echo "gates-db: starting throwaway Postgres ($(EUNOMIA_PG_IMAGE))"; \
	  docker rm -f $(EUNOMIA_PG_CONTAINER) >/dev/null 2>&1 || true; \
	  docker run -d --name $(EUNOMIA_PG_CONTAINER) -e POSTGRES_PASSWORD=eunomia \
	    -e POSTGRES_DB=eunomia_test -p $(EUNOMIA_PG_PORT):5432 $(EUNOMIA_PG_IMAGE) >/dev/null; \
	  trap 'docker rm -f $(EUNOMIA_PG_CONTAINER) >/dev/null 2>&1 || true' EXIT; \
	  echo "gates-db: waiting for Postgres"; \
	  for _ in $$(seq 1 30); do \
	    docker exec $(EUNOMIA_PG_CONTAINER) pg_isready -U postgres >/dev/null 2>&1 && break; \
	    sleep 1; \
	  done; \
	  EUNOMIA_STORE_TEST_DSN=postgresql+psycopg://postgres:eunomia@127.0.0.1:$(EUNOMIA_PG_PORT)/eunomia_test \
	    uv run pytest edge/store -m db; \
	else \
	  echo "gates-db: docker not available — SKIPPED locally (CI runs these against a postgres service)."; \
	  echo "          Set EUNOMIA_STORE_TEST_DSN to run against your own Postgres."; \
	fi

# ---- Python: verbatim Hermes commands, Hermes order (pytest -> ruff -> mypy -> imports) ----
gates-python:
	uv run pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run lint-imports

# ---- C++: blocking gates ----
# --style=file is explicit (it IS the default — read .clang-format). PER-FILE via xargs -n1: a
# clang-format 22 multi-file --dry-run quirk prints every filename + exits 1 even when all files are
# clean (single-file invocations are correct); xargs -n1 sidesteps it and stays blocking on a real
# violation (xargs exits non-zero if any file fails). Equivalent on every clang-format version.
# Since Run F2 landed transport/, BOTH on-target envs are built: esp32 (headless) AND cyd (the
# deployment board). transport/vendor/ never compiles (excluded from every build_src_filter) and is
# pruned from CPP_FILES. clang-tidy is now BLOCKING (OQ-11), run via gates-cpp-tidy.
gates-cpp:
	printf '%s\n' $(CPP_FILES) | xargs -P4 -n1 clang-format --dry-run -Werror --style=file
	$(PIO) test -e native -d firmware/coordinator
	$(PIO) run -e esp32 -d firmware/coordinator
	$(PIO) run -e cyd -d firmware/coordinator
	$(MAKE) gates-cpp-tidy
	$(MAKE) camera-image-checksum

# clang-tidy — BLOCKING since transport/ landed (Run F2, OQ-11), SCOPED to the hand-written,
# framework-free logic (TIDY_FILES = core/ + transport/proto/, where the two hard rules live).
# transport/hw/ (Arduino-coupled = "framework noise") and transport/vendor/ (reference) are excluded.
# Guarded on the binary so a machine without clang-tidy gets a loud skip, not a spurious break; CI
# images carry clang-tidy and enforce it.
gates-cpp-tidy:
	@if command -v clang-tidy >/dev/null 2>&1; then \
	  echo "clang-tidy (blocking, scoped: core/ + transport/proto/)"; \
	  EXTRA=""; [ "$$(uname)" = "Darwin" ] && EXTRA="-isysroot $$(xcrun --show-sdk-path)"; \
	  AJSON="firmware/coordinator/.pio/libdeps/native/ArduinoJson/src"; \
	  clang-tidy $(TIDY_FILES) -- -std=c++17 -Ifirmware/coordinator/core \
	    -Ifirmware/coordinator/transport/proto -Icontracts/_generated/cpp \
	    $$([ -d "$$AJSON" ] && echo "-I$$AJSON") $$EXTRA; \
	elif [ -n "$$CI" ]; then \
	  echo "ERROR: clang-tidy is REQUIRED in CI but was not found (a blocking gate must not silently skip)"; \
	  exit 1; \
	else \
	  echo "clang-tidy NOT installed — BLOCKING in CI (hard-fails there); skipped on this non-CI host"; \
	fi

# ---- codegen + drift ----
# Hermetic: generate under the pinned codegen deps (--no-project, so it runs before uv could build
# the eunomia-contracts package it produces), then canonicalize the generated Python with the
# project's pinned ruff (the generator emits valid Python; ruff owns the exact format). Both steps
# are deterministic, so `make drift` is meaningful. (OQ-6 / BUILD_PLAN carry-forward #1.)
# generate_interfaces.py is a SIBLING command (Run 0c, OQ-8): the interface ports are operation
# SIGNATURES, not records, so they get their own mini-emitter — NOT imported by generate.py (an
# intra-codegen import breaks mypy-from-root). One source -> two targets; the drift gate below covers
# both since both write into contracts/_generated.
codegen:
	uv run --no-project --with-requirements contracts/codegen/requirements.txt python contracts/codegen/generate.py
	uv run --no-project --with-requirements contracts/codegen/requirements.txt python contracts/codegen/generate_interfaces.py
	uv run ruff format contracts/_generated/python

drift: codegen
	git diff --exit-code contracts/_generated

# ---- camera-image checksum gate (no-op stub in 0a) ----
camera-image-checksum:
	python3 firmware/camera-image/checksum_gate.py
