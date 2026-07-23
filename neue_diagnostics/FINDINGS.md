# Findings — `neue1` input set

Generated 2026-07-23 from the `neue1` PRAS runs
(`dr_sweep_results/{pjm,ercot}_neue1/results/`, `*_neue1*.pras`). Reproducible with
`sbatch slurm/run_all.sh`. The headline narrative is in
[brief_results_summary.md](brief_results_summary.md); this file keeps the detail and
the data-quality record.

> **Supersedes the first-round findings.** An earlier version of this file described
> the original PRAS systems, in which ERCOT had zero EUE and PJM's unserved energy
> was a single-region offshore-wind artifact (p124). The `neue1` systems are far
> more capacity-constrained and that story does **not** carry over. The old p124
> diagnosis is preserved in git history (commit before 2026-07-23) if needed.

---

## 1. Both systems are now heavily stressed; ERCOT is the worse of the two

| | base (no DC), NEUE | +DC, no DR, NEUE | +DC EUE (MWh) | growth |
|---|---:|---:|---:|---:|
| PJM | 1.05 ppm | **59.83 ppm** | 1,003,700 | 61× |
| ERCOT | 1.00 ppm | **72.12 ppm** | 804,376 | 79× |

Both baselines sit near 1 ppm; adding datacenter load raises NEUE 60–80×. Unlike
the first-round runs (PJM ≈ 0.18 ppm, ERCOT = 0), these are large, absolute
shortfalls. Reconciliation against `cases.csv` matches for all but 3 PJM cases,
which are simply absent from ssundar's `cases.csv` (value `nan`) — the `.h5` files
read fine and are authoritative.

---

## 2. WHERE — EUE tracks the added datacenter load (reversal of the old result)

**PJM** (`outputs/tables/pjm_where.csv`): 93 % of EUE is in **p99**, which also
takes **47 % of the added load** — the most of any region. p99 runs a negative
mean margin (−7,798 MW). The datacenter load lands on the most capacity-short
region.

**ERCOT** (`outputs/tables/ercot_where.csv`): 98 % of EUE is in **p63 / p65 / p64**
(52 / 25 / 21 %), which take **71 % of the added load**. Counter-example: **p67
gets the most added load (24 %) but only 1.4 % of the EUE** — it has enough margin
(min −1,374 MW) to absorb it, while the failing regions run −5 to −15 GW.

So datacenter DR is **well-targeted by construction** here: sized to the load, and
the load is where the risk is. This is the opposite of the first-round PJM run,
where EUE was concentrated in a region with almost no datacenter load. It does not
mean DR is *sufficient* (see §6).

---

## 3. WHY — system-wide capacity shortfalls at extreme net load, after sunset

EUE-weighted conditions during failure hours (`outputs/tables/{pjm,ercot}_why.csv`):

| feature | PJM all-hrs | PJM EUE-wtd | ERCOT all-hrs | ERCOT EUE-wtd |
|---|---:|---:|---:|---:|
| net-load percentile | 0.50 | **0.995** | 0.50 | **0.994** |
| margin percentile | 0.50 | **0.005** | 0.50 | **0.006** |
| margin (MW) | +4,061 | **−17,464** | +6,327 | **−6,553** |
| solar CF | 0.227 | 0.035 | 0.299 | 0.020 |
| wind CF | 0.425 | 0.331 | 0.422 | 0.193 |
| added load (MW) | 444 | **3,743** | 1,130 | **2,076** |

Failures occur at the extreme top of net load and bottom of margin, with **near-zero
solar** (evening/overnight) and **elevated datacenter load**. Average margin during
EUE is deeply negative — the system is short by many GW. **Wind is not the trigger**
this time (CF only moderately below normal); the driver is total load vs total
capacity with solar absent after sunset. Contrast the first-round p124 story, which
was specifically a wind drought.

---

## 4. Chronic, not a few extreme hours; ~half the EUE is in new failure hours

**Concentration** (`outputs/tables/{pjm,ercot}_concentration.csv`, system scope):

| case | top-10 h | top-100 h | hours to 90 % | nonzero hours |
|---|---:|---:|---:|---:|
| PJM base | 56 % | 86 % | 195 | 1,884 |
| PJM +DC, no DR | 10 % | 44 % | **627** | 7,855 |
| ERCOT base | 86 % | 100 % | 14 | 86 |
| ERCOT +DC, no DR | 12 % | 66 % | **211** | 1,023 |

Base failures are a few extreme hours; adding datacenter load spreads the deficit
across hundreds-to-thousands of hours — a sustained seasonal shortfall.

**Delta decomposition** (`outputs/tables/{pjm,ercot}_delta.csv`): **52 % (PJM) /
54 % (ERCOT) of the high-case EUE is in hours that had none in the base case.** The
added load creates new scarcity as much as it deepens existing scarcity. The *shape*
of when EUE occurs shifts substantially (total-variation distance base→high:
PJM month 0.33 / hour 0.46 / weather-year 0.44; ERCOT 0.43 / 0.62 / 0.72).

---

## 5. DR — effective in PJM, weak in ERCOT, magnitude-limited everywhere

Saturation (`outputs/tables/dr_saturation_summary.csv`), % of DC penalty recovered
at fraction 1.0:

| family | system | NEUE floor | recovered | kneedle | 80 %-achieved f |
|---|---|---:|---:|---:|---:|
| shed_16h | PJM | 20.64 | **67 %** | 0.3 | 0.4 |
| shed_8h | PJM | 24.37 | 60 % | 0.3 | 0.4 |
| shift_16h | PJM | 26.58 | 57 % | 0.3 | 0.4 |
| shift_8h | PJM | 29.09 | 52 % | 0.3 | 0.4 |
| shift_4h | PJM | 39.62 | 34 % | 0.3 | 0.3 |
| shed_4h | PJM | 53.61 | 11 % | 0.5 | 0.6 |
| shift_8h | ERCOT | 56.23 | **22 %** | 0.4 | 0.7 |
| shift_4h | ERCOT | 61.40 | 15 % | 0.4 | 0.7 |

- **No knee past which DR is wasted** — returns decline smoothly; 80 % of the
  achievable reduction needs f ≈ 0.4 (PJM) to 0.7 (ERCOT).
- **Duration beats deployment share** — PJM `shed_4h` recovers 11 %, `shed_16h`
  recovers 67 %.
- **Best cases are statistically distinguishable** from their runners-up
  (`best_distinguishable_indep = True` for PJM `shed_16h` and ERCOT `shift_8h`) —
  with EUE this large, the increments now clear Monte-Carlo noise.

**Every family is magnitude-limited** (`outputs/tables/dr_limit_diagnosis.csv`):
the always-on shift devices reach `eue_in_window_frac = 1.0` and dispatch enormous
energy (PJM `shift_16h`: 5.86 M MWh) yet still leave large shortfalls (383,000 MWh).
DR is used to the hilt; the system is short by more than the datacenter load can
flex away. This is a genuine magnitude limit, unlike the first-round run where the
shed families were *window*-limited by a tiny availability overlap.

**ERCOT's weaker result is partly an experiment artifact** — its sweep has shift
only, 4 h and 8 h, no shed and no 16 h. It is under-equipped, so its 22 % is not a
fair floor on what DR could do there.

**shed-vs-shift is still confounded** (PJM): shed forgives payback but is
window-restricted. `shed_4h` (4–8 PM ET) sees only 0.4 % of its remaining EUE in
its window, which is why it is the weakest family despite shed's mechanistic
advantage. An **always-on shed run** (drop `available_hours_et`) is still needed for
a clean mechanism comparison.

---

## 6. Data issues found and handled (unchanged — file-format facts)

| Issue | Where | Handling |
|---|---|---|
| `/eue` is `(N, R)` in h5py, not `(R, N)` as `usage.md` says (Julia column-major) | all files | asserted in `io_results.read_arrays`; confirmed against the [PRAS HDF5 spec](https://natlabrockies.github.io/PRAS/stable/SystemModel_HDF5_spec/) |
| `dr_energy`/`dr_shortfall` are **zero-width** `(N, 0)` for baselines, not "zeros" | baseline files | materialized as zeros, flagged via `_synthesized` |
| `usage.md` availability table wrong for `shed_16h` (says 12–8 PM; file says 6 AM–9 PM) | `dr_sweep/usage.md` | read from `/dr_config`, never the doc |
| `case_id` unique only *within* a system (each has `baseline`) | cross-system joins | all lookups scoped by system |
| Weather-year blocks drift ~1 day/leap-year (Feb 29 present, blocks forced to 8760 h) | all files | benign; 672 h, all in December. Use `weather_year` for ReEDS alignment, `calendar_year`/`month` for meteorology |
| Cross-check tolerance was absolute (1 MWh), false-alarmed on the larger `neue1` EUE | `01_extract_eue.py` | changed to relative (1e-3 of largest case); 1.07 MWh diff on 1 M MWh = 0.0001 %, benign |
| 3 PJM cases (`shift_4h_all_0.80/0.90/1.00`) absent from `cases.csv` | ssundar's merge | `.h5` files authoritative; pipeline reads them fine |

---

## 7. Open items

- **ERCOT shed / 16 h run.** ERCOT's 22 % recovery is capped by an incomplete DR
  toolkit, not necessarily by the system. Needed before concluding ERCOT is harder
  to help than PJM.
- **Always-on shed run** to disentangle the shed-vs-shift confound (PJM).
- **What changed between the first-round and `neue1` systems?** NEUE jumped ~330×
  (PJM) and 0→72 ppm (ERCOT). Worth confirming the intended capacity-mix difference
  (e.g. retirements, lower reserve margin) rather than an input error, since it
  drives every result here. `scripts/90_verify_pras_delta.py` can diff old vs new
  `.pras` if that comparison is wanted.
