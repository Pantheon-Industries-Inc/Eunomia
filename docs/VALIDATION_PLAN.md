# Eunomia — Capture Validation Plan

**What changed (read first).** This was originally a "prove the gates on a bench before the fleet
buy" plan. Two things have overtaken that framing:

1. **The working rig IS the bench.** Victor's latest firmware ran **over an hour continuously with no
   battery or thermal issue**. That is direct evidence for the gate that actually mattered for the
   hardware decision — whether the ESP32 SoftAP + cameras survive sustained load. So the expensive,
   uncertain, fleet-buy-blocking part is essentially answered; it does not need a separate lab campaign.
2. **We build, deploy, and validate during the first real captures — and fix if it fails.** This is
   safe *here specifically* because the design degrades **visibly and non-destructively**: every
   remaining failure mode surfaces as a flag (`recording_suspect`, `needs_review`) or a count
   mismatch, never as silently-wrong data. A problem in the field is caught and quarantined, not
   baked into the training set. So "ship it and watch" costs a re-fix, never lost or corrupted data.

So this is no longer a gate-before-buy checklist. It is: **what Victor's run already settles**, **what
the design handles by construction (validated on the first real captures, not a lab test)**, and **the
short induced-failure checks worth doing deliberately because a quiet run can't exercise them.**

> **Why there is no pre-build rig test.** Eunomia's coordinator firmware is a clean rewrite with more
> involved behavior than Victor's binary (the dedicated-core network task, the two-write sidecar, the
> instant-ack UI state machine, our own OSC serialization). Testing Victor's rig now would validate
> *Victor's* firmware — it would not transfer, because the failure modes that matter (does *our*
> serialization hold the single-OSC rule under *our* load; does *our* radio task starve anything) live
> in code that does not exist yet. The only thing a pre-build rig test could have de-risked is whether
> the **hardware** is physically capable — and Victor's hour-plus run already answered that. So every
> remaining question is about *our* firmware, which can only be tested once built. We test on our own
> firmware, after building it. (The lone hardware-usage-independent exception is the one-file-vs-split
> question in section A/B — that is a property of the *camera* firmware + the locked capture mode,
> which is identical on Victor's rig and ours, so a long recording on either answers it.)

The measurement discipline is unchanged and still governs everything: **the camera clock and file
timestamps are never a measurement** — truth is the fob serial log (timing) + telnet clip-count/
file-growth (did-it-record). Same rule the architecture runs on.

---

## A. Settled by Victor's run (no separate test needed)

These were the gates that could have changed the **hardware**; the hour-plus continuous run answers them.

- **Sustained load / SoftAP hold.** The ESP32 hosted the AP + cameras + recording for over an hour
  with no drops Victor flagged. The "can the board even do this" question is answered for session-
  length operation. *Residual:* confirm parity (clips-landed = takes-fired on both cameras) over a
  full ~2 hr block during the first real session — but as an observation, not a blocking lab test.
- **Thermal.** Over an hour at the locked 3K/100 with no thermal shutdown. The `overheat` stop-reason
  risk is largely retired. *Residual, free:* the first real ~2 hr block confirms the block length
  (the camera auto-stops at its thermal limit and stamps `stop_reason`, so if it ever happens it is
  recorded, not silent).
- **Battery.** No battery issue over the run → power draw is sustainable for a session. The
  start-on-full-batteries operational rule still stands (low battery was historically a drop cause).

**One thing to confirm with Victor when he's back (not blocking):** was the hour-long recording **one
continuous file, or did it split into several?** This is the cheapest possible answer to the
file-splitting question in section B. If it was one file, that gate is also settled for free.

---

## B. Handled by construction — validated on the first real captures (not a lab test)

These are **correctness** behaviors (not hardware-survival). The build must handle each; a clean run
can't prove them because nothing went wrong — so we validate them as the **first real capture session
exercises them naturally**, and rely on the safe-degradation property to make a miss visible, not
corrupting. For each: what the build must do, and what to watch for on day one.

- **File-splitting of a long take.** *Risk:* firmware auto-segments a ~2 hr recording into multiple
  files → the camera episode count inflates vs. fob starts → naive count-reconcile mislabels.
  *Build handles it:* the join keys on the camera's swap-proof ordinal + a clip-count fallback and
  flags a `needs_review` mismatch rather than positionally shifting labels. *Day-one check:* after the
  first long block, confirm clips-per-fob-start (1, or N if it split) and that the join didn't silently
  shift. *If it splits unexpectedly:* teach the count-reconcile the split rule — the data is flagged,
  not lost. (Confirming with Victor per section A may pre-answer this.)
- **NAND episode-sequence monotonic across SD / battery swaps.** *Risk:* the ordering spine resets on
  a swap → ordering desync. *Build handles it:* the join uses the NAND global sequence as the spine and
  detects gaps; a fob swap is disambiguated by the per-boot session id. *Day-one check:* the first
  session *will* include card and battery swaps (a card fills in ~2 hr) — confirm the sequence stays
  continuous across them and pairing holds. This is the real test and it happens for free on day one.
- **Stop-tightness.** *Risk:* the two arms stop seconds apart → beyond audio-sync tolerance.
  *Build handles it:* fire both `stopCapture`s first, then finalize per camera. *Day-one check:* on the
  first back-to-back takes, the fob serial shows both stops issued within a tight window (target
  < ~300 ms) and the end-offset is comfortably under the audio-sync tolerance (the rig has absorbed
  ~1.4 s; anything well under ~1 s is fine). *If still staggered:* the stop loop is still serializing
  finalize-before-next-stop — pure firmware fix.
- **Telemetry never bleeds into a take.** *Risk:* a telemetry WiFi hop fires mid-take and delays a
  STOP. *Build handles it:* the network worker is on a dedicated core and flushes strictly in the
  post-STOP idle gap; START is never blocked. *Day-one check:* on the first back-to-back burst, confirm
  from the serial log that no WiFi hop happens between a START and its STOP. *If it does:* defer the
  flush to the idle gap, or (fallback) flush only at sign-out.
- **Serial reliably present in every clip.** *Build handles it:* the crosswalk uses the always-present
  embedded serial; an un-resolvable card is parked whole in quarantine and rescued by teaching the
  registry the serial. *Day-one check:* no cards land in quarantine unexpectedly; if one does, the
  rescue path recovers it (footage intact). Never guess left/right.

---

## C. Short induced-failure checks (worth doing deliberately, minutes not days)

Two failure modes are *data-integrity* checks that a normal session won't reliably trigger on its own,
so it's worth **inducing** them once — either in a few spare minutes with the prototype, or as a
deliberate moment during the first session. Both are quick.

- **Silent-stop → `recording_suspect`.** The one unfixable-on-camera edge: a camera that **stops
  recording but stays associated** is invisible at the network layer and must not be OSC-polled. The
  STOP-time clip-grew check is what catches it.
  *Induce:* start a take on both cameras; pull or fill one camera's SD mid-take (recording stops, WiFi
  stays up — confirm the fob serial still shows that camera associated); press STOP.
  *Pass:* the camera stayed associated, yet the fob flagged `recording_suspect` from the clip-grew
  check. *Fail:* the fob reported the take clean → tune the grow/minimum-size threshold (firmware fix).
- **No-SD start.** *Induce:* start a take on a camera with no card / a full card.
  *Pass:* the fob's start-confirm doesn't see the clip grow and flags `recording_suspect` (it does not
  optimistically count the take). *Fail:* the take is counted clean → same threshold fix.

(These two share one mechanism — the "did the clip actually grow" confirmation — so passing one
largely covers the other. Downstream QC + pairing is still a second backstop, but the point is to
catch it live.)

- **Rapid re-START sidecar race (the GATE_SAVING question, F6).** The fob never confirms that
  discardd materialized the PRIOR take's on-card `.pantheon.json` before the next take begins. The
  ui DelayedButton lockout covers only the in-flight finalize window (the STOP/sidecar-push action),
  NOT discardd's *asynchronous* stamp a moment later — so a fast re-START could leave the prior clip
  unlabeled. (We deliberately did NOT speculatively port Victor's `priorSidecarsReady` poll.)
  *Induce:* STOP a take, then START the next as fast as the UI allows (back-to-back), repeatedly.
  *Pass:* each prior clip's `.pantheon.json` is present on every card before the next take's clip is
  created — no unlabeled/mislabeled prior clip. *Fail:* a prior clip lands unlabeled → THEN implement
  a persistent GATE_SAVING (a `sidecars_pending` flag + a press-time telnet `test -f .pantheon.json`
  poll, mirroring Victor). The implementation is conditional on THIS result — not done speculatively.

---

## D. Provisioning + ship gate (the real pre-deploy gate)

The thing that genuinely should block a kit from going out is **not** a soak test — it's that the kit
is correctly provisioned and isolated. This is enforced at provisioning (in the provisioning console),
per kit:

- **Per-camera:** correct identity burned to NAND (kit + side, generated from the registry, never
  hand-typed); the on-camera agent running (holds capture mode + writes the sidecar); capture profile
  set (locked 3K/100, FlowState off, audio on, both lenses kept); auto-power-off never; orientation
  ground-truthed (left camera = left view).
- **Per-fob:** isolated to its two cameras (the camera allowlist locked; a fob that would trigger any
  camera in the room must not ship); kit/operator bound; WiFi + upload config set; NTP-synced on boot.
- **The ship gate:** a single per-kit check that refuses unless the allowlist is locked + identity is
  set + firmware matches the deployment version + the fob has synced time. This is the one hard gate;
  it blocks an un-isolated or mis-provisioned kit, which is the actual fleet risk — not thermal.

---

## E. What to watch during the first real session (the validation that replaces the soak)

The first real ~2 hr collection block, run normally, exercises almost everything in section B for free.
Watch (or check after) these, all of which are visible because the design surfaces them:

- Clip parity: clips-landed (each camera) = fob starts, across the whole block including card/battery
  swaps. A mismatch → inspect the join's `needs_review` / gap output (not silent).
- The sequence stayed continuous across each card and battery swap; pairing held.
- No unexpected quarantined cards; any that appear recover via the rescue path.
- The first back-to-back takes: stops tight, no telemetry hop inside a take window.
- The block ran its full length without a thermal stop (and if one ever happens, it's stamped
  `stop_reason=overheat`, not silent).

If all of that holds on the first real session, the system is validated in the environment that
matters, and the only thing that was ever a true pre-deploy gate (provisioning + isolation, section D)
is already enforced per kit.

---

## Results / observations log

| Item | When | Result | What was observed | Follow-up if it failed |
|---|---|---|---|---|
| Sustained load / thermal / battery | Victor's run | ✅ settled | >1 hr continuous, no battery/thermal issue | — |
| One-file-or-split (ask Victor) | when back | ☐ confirmed | one file? / split? | if splits: teach count-reconcile |
| File-splitting on first long block | first session | ☐ ok ☐ flagged | clips per start | flagged = fix reconcile, data safe |
| Sequence continuity across swaps | first session | ☐ ok ☐ issue | continuous? pairing held? | fix join, data flagged not lost |
| Stop-tightness | first back-to-back | ☐ ok ☐ staggered | stop-to-stop ms, end-offset | firmware: stops-before-finalize |
| Telemetry not in take | first back-to-back | ☐ ok ☐ bled | hop inside a take window? | defer flush to idle gap |
| Silent-stop → recording_suspect | induced | ☐ caught ☐ missed | stayed associated? flagged? | tune grow/size threshold |
| No-SD start | induced | ☐ caught ☐ missed | flagged? | same threshold fix |
| Rapid re-START sidecar race (GATE_SAVING, F6) | induced | ☐ ok ☐ raced | prior `.pantheon.json` on-card before next clip? | raced = add persistent GATE_SAVING (press-time `test -f` poll) |
| Per-kit ship gate | each kit | ☐ pass ☐ block | allowlist + identity + fw + time | block until provisioned right |

**Decision rule (revised).** There is no separate soak gating the fleet buy — Victor's run + the
first real session cover load/thermal, and the design makes every remaining failure visible and
non-corrupting, so we build, deploy, and fix-if-it-fails. The one hard pre-deploy gate is the
**per-kit ship gate** (section D): a kit ships only when it is correctly provisioned and isolated.
