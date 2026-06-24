# Rule: firmware/

- **`firmware/coordinator/core/` stays pure, hardware-free, and off-target testable.** No hardware
  calls in `core/`; it implements `CoordinatorPort` and is tested with `pio test -e native` (the
  one-machine rule — never assume real hardware in a test).
- **`transport/` and `ui/` are the swappable layers.** Board/radio changes live in `transport/`;
  display changes in `ui/`. Neither change touches `core/` or the contracts (adapt-not-rebuild).
- firmware depends only on `contracts/`, via the generated header `contracts/_generated/cpp/`. It is
  outside the Python import-linter; its boundary is the include structure + the conformance gate.
- Hand-written C++ is `clang-format`-clean (`clang-format -i`); generated headers are exempt from the
  format gate but must compile in the `native` test.
