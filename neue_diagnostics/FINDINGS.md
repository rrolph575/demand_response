# Findings — stages 00/01/04a

Generated 2026-07-22 from `dr_sweep_results` as of 2026-07-14. All numbers below
are reproducible with `scripts/00_build_registry.py`, `01_extract_eue.py`,
`04_saturation.py`. No `.pras` reads, no allocation used.

---

## 1. ERCOT has zero EUE in every case — there is nothing to explain there

**All 24 ERCOT cases report exactly 0.0 MWh EUE and 0.0 ppm NEUE**, including
both baselines. The DR sweep for ERCOT therefore contains no signal: there is no
reliability event for DR to mitigate, at any fraction, in either datacenter-load
scenario.

This is physical, not a broken run:

| system | peak load (MW) | available cap @ peak (MW) | reserve margin | mean unit FOR |
|---|---:|---:|---:|---:|
| ERCOT base | 108 081 | 165 196 | **52.8 %** | 0.0028 |
| ERCOT high | 116 960 | 165 196 | **41.2 %** | 0.0028 |
| PJM base | 162 403 | 217 889 | 34.2 % | 0.0079 |
| PJM high | 170 178 | 217 889 | **28.0 %** | 0.0079 |

The added datacenter load *did* land in ERCOT (+8 879 MW at the peak hour,
consistent with `load_add_summary.md`), but ERCOT enters 2032 with ~40 % reserve
margin at peak and a forced-outage rate roughly a third of PJM's. It never runs
short.

**Consequence:** every downstream question — when does high NEUE happen, which
region, which weather year, does DR help — is a **PJM-only** question with these
inputs. Worth deciding whether that is an interesting result in itself (ERCOT's
2032 buildout absorbs central-case datacenter growth without reliability cost)
or a reason to re-run ERCOT with a tighter system.

---

## 2. The EUE data is tiny and extremely concentrated

| | PJM |
|---|---|
| `/eue` nonzero cells | **0.066 %** of 131 400 × 19 |
| hours with any EUE (no-DR, high DC) | 1 659 of 131 400 (**1.26 %**) |
| nonzero cells in those hours | 1 660 |

Nonzero cells ≈ nonzero hours (1 660 vs 1 659), meaning **EUE almost never hits
two regions in the same hour**. Events are overwhelmingly single-region. That is
a strong hint that these are local/deliverability-constrained events rather than
system-wide capacity shortfalls — worth confirming against transmission limits in
stage 02, because it changes the story from "PJM is short of capacity" to "one
region is short and can't import".

Practical consequence: the whole sweep stores as ~139 000 nonzero rows (a 6 MB
CSV). The earlier "170 million rows" concern was an artifact of a dense
long-format design, now dropped.

---

## 3. DR saturation — the diminishing-returns question

### Curves flatten gradually; there is no sharp knee at any fraction

| family | mode | NEUE floor (f=1) | % of DC penalty recovered | kneedle knee | f for 80 % of achievable |
|---|---|---:|---:|---:|---:|
| `shift_16h_all` | shift | **0.0932** | **50.5 %** | 0.5 | 0.8 |
| `shed_16h_all` | shed | 0.1102 | 40.6 % | 0.5 | 0.8 |
| `shift_8h_all` | shift | 0.1293 | 29.4 % | 0.5 | 0.8 |
| `shed_8h_all` | shed | 0.1377 | 24.5 % | 0.6 | 0.8 |
| `shed_4h_all` | shed | 0.1525 | 15.8 % | 0.6 | 0.8 |
| `shift_4h_all` | shift | 0.1536 | 15.2 % | 0.5 | 0.7 |

Reference points: no DR at high DC load = **0.1796 ppm**; base DC load =
**0.00856 ppm**. The "DC penalty" is the 0.171 ppm gap between them.

**The hypothesis that gains stop around 50 % is not supported.** Marginal return
declines smoothly and monotonically; the geometric knee lands at 0.5–0.6 but the
curve is still delivering meaningful reduction past it — 80 % of everything
achievable needs f ≈ 0.7–0.8. There is no fraction beyond which added DR stops
helping; it just helps progressively less.

**Duration matters far more than fraction.** Going 4h → 16h roughly triples the
benefit (15 % → 50 % of the penalty recovered), while going f=0.5 → f=1.0 within
a family adds much less. If there is a lever here, it is device duration, not
deployment share.

**Even the best case recovers only half the penalty.** `shift_16h_all` at f=1.0
lands at 0.0932 ppm against a 0.00856 ppm base-load target — still ~11× the
base-case NEUE. DR meaningfully mitigates but does not neutralize the added
datacenter load in this buildout.

### Why the curves flatten — and it differs by mode

| family | verdict | EUE inside DR window | dispatch per borrow-MW | DR shortfall |
|---|---|---:|---:|---:|
| `shed_4h_all` | **dispatch-limited** | **0.08** | 0.040 | 0 |
| `shed_8h_all` | **window-limited** | 0.16 | 0.061 | 0 |
| `shed_16h_all` | **window-limited** | 0.26 | 0.100 | 0 |
| `shift_4h_all` | magnitude-limited | 1.00 | 0.400 | 1 369 MWh |
| `shift_8h_all` | magnitude-limited | 1.00 | 0.784 | 1 119 MWh |
| `shift_16h_all` | magnitude-limited | 1.00 | 1.356 | 627 MWh |

This resolves the shed/shift confound flagged in the plan, and the answer is
decisive: **the shed cases are crippled by their availability windows, not by
their payback rule.** At f=1.0, only **8 %** of `shed_4h`'s remaining EUE occurs
during the hours it is allowed to run (16–19 ET). The other 92 % happens when
its borrow capacity is pinned at zero.

Note the overlap *falls* as fraction rises (see
`outputs/figures/pjm_availability_overlap.png`): DR removes the EUE it can
reach, so what survives is increasingly outside the window. That is the
signature of window-limiting.

**Therefore the apparent "shed vs shift" comparison in this sweep is not a
comparison of shed vs shift.** Shed is handicapped by a restriction shift does
not have. Shed should out-perform shift per MW on physics (forgiven energy
strictly beats rescheduled energy), and instead it under-performs at every
duration — entirely explained by the window. **To compare the mechanisms, an
always-on shed run is needed.** That is a config change
(drop `available_hours_et`), not a code change.

### A caveat on the marginal-return curve

The sweep's fraction grid is uneven — 0.05 steps up to 0.10, then 0.10 steps.
The first two marginal-return points divide a small ΔNEUE by a small Δf and are
visibly noisier than the rest (see the non-monotonic left edge of the right-hand
panel in `pjm_saturation.png`). Knee estimates in f < 0.2 should not be trusted;
the 0.5–0.6 knees sit in the smooth region and are stable.

More generally: case-level MC stderr is ~1 % of EUE, so NEUE stderr ≈ ±0.0018 —
**larger than most step-to-step differences**. The curves are nonetheless cleanly
monotone because all cases share `seed = 14` (common random numbers), which makes
paired differences far more reliable than independent stderrs imply. The `.h5`
files do not retain per-sample draws, so this cannot be quantified from the
outputs alone. If a defensible confidence interval on the increments is needed,
the sweep would have to be re-run with per-sample output retained.

---

## 4. Data issues found and handled

| Issue | Where | Handling |
|---|---|---|
| `/eue` is `(N, R)` in h5py, not `(R, N)` as `usage.md` says | Julia column-major | asserted in `io_results.read_arrays` |
| `dr_energy`/`dr_shortfall` are **zero-width** `(N, 0)` for baselines, not "zeros" as `usage.md` says | all baseline files | materialized as zeros, flagged via `_synthesized` |
| `usage.md` availability table wrong for `shed_16h` (says 12–8 PM; file says 6 AM–9 PM) | `dr_sweep/usage.md` | read from `/dr_config`, never the doc |
| Archived `experiment_setup.md` peak-added values are ~2.4× the current ones | `archive_eer_central_csv/` | **resolved**: current runs match `load_add_summary.md` (implied 10 162 MW vs 10 167 stated). The archive is a stale vintage. |
| `case_id` is unique only *within* a system (both have `baseline`) | cross-system joins | all lookups scoped by system; this bug was caught and fixed in stage 01 |
| Weather-year blocks drift ~1 day earlier per leap year (timestamps contain Feb 29 but blocks are forced to 8760 h) | all files | benign; 672 h affected, all in late December. Use `weather_year` for ReEDS alignment, `calendar_year`/`month` for meteorology. Detected and explained automatically. |

---

## 5. Attribution — ANSWERED (stages 02 + 03, 2026-07-22)

Stage 02 (`.pras` features) ran in 24 s for PJM / 10 s for ERCOT; stage 03
(attribution) in seconds. Results are summarized in
[brief_results_summary.md](brief_results_summary.md); the short version:

- **Where:** 99.0 % of PJM EUE is in **p124**, which receives 0.3 % of the added
  datacenter load. p99 takes 47 % of the added load and produces 0.9 % of EUE.
  p124 has a 220 MW peak, **60 MW of firm capacity**, up to 2 611 MW of wind, and
  only **80 MW of import capability** — the lowest import-to-peak ratio in PJM.
  The §2 single-region hypothesis is confirmed: this is local deliverability,
  not system-wide scarcity.
- **When:** evening/overnight (8 pm–1 am local), winter and summer, nearly
  nothing in spring.
- **Why:** EUE-weighted wind CF is **0.005** against an all-hours mean of 0.425;
  net-load percentile 0.986, margin percentile 0.014. Wind drought in a
  wind-dependent pocket.
- **Delta:** **41 % of high-case EUE is in hours that had none in the base case** —
  new failure modes, not just amplification. Shape shifts substantially by
  weather year (TVD 0.45) and month (0.43), much less by hour of day (0.22).
- **DR targeting:** in the best case, p124's **30 MW** device delivers 1 210 of
  the 1 234 MWh total reduction (98 %); the other ~10 100 MW deployed elsewhere do
  almost nothing. But p124 is **maxed out and still short** — flexing 100 % of its
  datacenter load leaves 1 332 MWh EUE and 627 MWh DR-shortfall. Because DR here IS
  datacenter flexibility, the risk region can only flex the 30 MW of datacenter
  load it has, and the idle DR elsewhere cannot be reallocated: it is that region's
  own load, and p124's 80 MW tie caps external help regardless. **Datacenter DR
  structurally cannot close p124's gap.** (An earlier framing — "DR sized to
  adequacy need would do more per MW" — was withdrawn as unsupported: you cannot
  manufacture datacenter-DR where there is little datacenter load.)

### p124 — structural diagnosis

| | |
|---|---|
| transmission | **one radial tie** to p123: 80 MW in / 336 MW out |
| offshore wind | **2 536 MW** vs a 220 MW peak load (11.5×) |
| firm generation | 60 MW across 22 o-g-s units; 12 are 0 MW, most others 1–2 MW |
| battery | 426 MWh / 148 MW = 2.9 h |
| **VRE stranded** | **116 TWh = 69.6 %** of everything it generates |
| hours generating more than it can use or export | 66 % |
| hours short after imports | 2 603 (2.0 %), max residual only **55 MW** |
| residual-deficit episodes | 853; **386 exceed the battery's 2.9 h** |

Mechanism: a wind drought longer than ~3 h in a zone with 60 MW of real
generation behind an 80 MW tie. The deficits are shallow (≤55 MW) and long, which
is exactly why a 30 MW DR device covers most of them.

**Confirmed: EUE lives entirely in the low tail of p124's wind output.**

- **100 % of p124 EUE hours have wind ≤ 77 MW** (capacity 2 611 MW, all-hours
  median 1 009 MW). Median wind during EUE hours: **4 MW**.
- Only 14 % of EUE hours have wind at exactly 0; 97 % are ≤ 50 MW and carry
  99.8 % of the energy. So: drought, not literal zero.
- firm (60) + import (80) = **140 MW servable without wind** against a median
  EUE-hour load of 150 MW and a max of 207 MW. p124 needs ~70 MW of wind — 2.7 %
  of installed — to close the gap. That threshold is exactly why no EUE hour
  exceeds 77 MW of wind.
- Given wind == 0 (790 h over 15 wy), 29.5 % of those hours produce EUE.

**The stranded-wind observation is therefore a red herring for adequacy** — only
the bottom ~3 % of the wind distribution matters.

Two failure modes, and the split is worth keeping straight:

| mode | hours | share of EUE | mean EUE/h |
|---|---:|---:|---:|
| capacity-short (load > firm+import+VRE) | 628 (38 %) | **72 %** | 2.90 MWh |
| outage-driven (nameplate adequate) | 1 013 (62 %) | 28 % | 0.71 MWh |

Since `/eue` is a mean over 1000 samples, an hour can carry small positive EUE
even when nameplate capacity covers load, because a minority of draws lose part
of the 60 MW firm fleet or the tie. Most EUE *hours* are of this type; most EUE
*energy* is not. Figure: `outputs/figures/pjm_critical_region.png`.

**Not a translation artifact.** Two hypotheses were tested and both failed:

1. *Missing interconnection to the offshore wind.* Wrong — the plant is inside
   p124, so none is needed, and 336 MW of export capacity exists. Direction
   convention confirmed against the
   [PRAS HDF5 spec](https://natlabrockies.github.io/PRAS/stable/SystemModel_HDF5_spec/):
   `forwardcapacity` runs `region_from`→`region_to`.
2. *The 80/336 asymmetry is anomalous.* Wrong — **all 41 PJM lines are
   asymmetric, zero symmetric**; p124's 4.2× ratio is mild against p110|p118's
   13.2×. Directional ratings are just how ReEDS transmission translates.

The spec also confirms rows = timesteps, columns = entities, i.e. `(N, R)` in
h5py — so `usage.md`'s `(R, N)` is the Julia column-major view, as asserted in §4.

**Most likely explanation: policy-forced capacity.** The ReEDS scenario is
`high_currentpolicy_central`; current policy includes state offshore-wind
mandates. ReEDS must build the 2 536 MW regardless of deliverability, and absent
a co-optimized tie the outcome is exactly what is observed — mandated offshore
wind, ~70 % curtailed, in a BA with 60 MW of firm capacity. Expected model
behavior under a binding constraint, not a defect.

**Interpretation:** the p124 result is real *within the model* but narrow. It
says a small coastal BA meeting an OSW mandate is thin on firm capacity behind a
small tie, and ~30 MW of datacenter load tips it. It does **not** support a claim
that PJM broadly has a datacenter-driven adequacy problem.

### Open items

- **Confirm the ReEDS run shows comparable p124 curtailment.** If it does, this
  is settled as expected behavior. Every aggregate PJM number in this study is
  effectively a statement about this one zone, so the framing matters.
- **Always-on shed run** to make the shed-vs-shift mechanism comparison valid.
- **ERCOT re-run** against a tighter system, or accept the null result.
