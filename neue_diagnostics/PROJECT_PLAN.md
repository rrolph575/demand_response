# NEUE Diagnostics Pipeline — Project Plan

**Goal.** Given a set of PRAS runs, explain *when* high NEUE happens and *why*: which
regions, which weather years, which hours, and what the co-occurring system conditions
were (load level, added datacenter load, VRE availability, storage state, DR headroom).
Then: **where do incremental DR gains stop being worth it?**

**Design constraint.** Input files get swapped. Nothing about a specific case name,
region set, or sweep design may be hardcoded in analysis code — all of it comes from a
config + an auto-built case registry.

**Environment.** `~/.conda-envs/reeds2` (py 3.11, h5py 3.9, numpy 1.26, pandas 2.0,
matplotlib 3.7, pyyaml). No installs needed. Caching uses `.npz` + CSV, deliberately
avoiding pyarrow/parquet since no available env has it.

---

## 1. What the data actually is (verified 2026-07-22)

### Result files — `<system>/results/*.h5`

One file per PRAS case. Verified layout:

| Path | Shape in h5py | Meaning |
|---|---|---|
| `/eue` | `(131400, Nreg)` f32 | **Primary dataset.** Per-region per-timestep EUE mean (MWh) over `samples` draws |
| `/dr_energy` | `(131400, Nreg)` f32 | DR energy stored |
| `/dr_shortfall` | `(131400, Nreg)` f32 | DR shortfall |
| `/regions` | `(Nreg,)` str | Region labels, **alphabetically sorted** (`p100, p109, …, p99, z122`) — not numeric order |
| `/timestamps` | `(131400,)` str | ISO8601 UTC, `2007-01-01T00` → `2021-12-27T23` |
| `/summary/{eue_mean_mwh, eue_stderr_mwh, neue_ppm, dr_eue_mean_mwh, dr_eue_stderr_mwh, dr_neue_ppm}` | scalar | Case-level rollups |
| `/dr_config/*` | `(Ndev,)` | DR fleet definition — see below. Empty for baselines |
| root attrs | `case_id, case_label, system, seed, samples, eer_scenario, pras_input, schema_version` | Self-describing provenance |

> **Transpose gotcha.** `usage.md` documents `/eue` as `(R, N)` — that's the Julia
> column-major view. h5py sees `(N, R)` = `(131400, Nreg)`. Verified by `h5dump`.
> Rows are timesteps in Python. Assert this on load rather than trusting either doc.

`131400 = 15 weather years × 8760 h` (2007–2021). PJM `Nreg=19`, ERCOT `Nreg=7`.

### `/dr_config` is the authoritative case description — do not parse filenames

Per device (one per region): `region, name, device_type, fraction,
borrow_capacity_mw, energy_capacity_mwh, payback_hours, avail_window_h, avail_hours_et`.

This matters because **the filename is misleading**. From `usage.md`:

- The `4h`/`8h`/`16h` in `shed_16h_all_0.50.h5` is **`energy_hours`**, i.e.
  `energy_capacity = energy_hours × borrow_capacity`. It is *not* a duration limit and
  *not* the availability window. My earlier `dr_duration_h` naming was wrong; the field
  is `energy_hours`.
- **Availability windows differ by mode.** Verified from `/dr_config` (2026-07-22):

  | case | device | `avail_window_h` | `avail_hours_et` |
  |---|---|---|---|
  | `shift_{4,8,16}h` | shift | 0 | `[]` — always on |
  | `shed_4h` | shed | 4 | `[16,17,18,19]` (4–8 PM) |
  | `shed_8h` | shed | 8 | `[12…19]` (12–8 PM) |
  | `shed_16h` | shed | 16 | `[6…21]` (**6 AM–9 PM**) |

  > **`usage.md` is stale here** — its config table claims `shed_16h` is 12–8 PM ET.
  > The file says 6 AM–9 PM. Trust `/dr_config`, not the docs.

  Outside the window `borrow_capacity = 0`. So a shed case differs from shift in **two**
  ways at once — forgiven payback **and** a time restriction — and these push in
  *opposite* directions (no-payback helps, narrow window hurts), so the bias can't even
  be signed. Not a clean A/B.
- **`Xh` also sets `payback_hours`.** Verified: `shift_16h` has
  `energy = 16 × borrow` and `payback_hours = 16`. So `shed_4h → shed_16h` varies
  energy capacity, payback window, *and* availability width simultaneously — not a clean
  energy-duration sensitivity either. Borrow capacity *is* matched across modes at equal
  fraction (checked: 80 / 90 MW for the first two devices in both `shed_4h_0.50` and
  `shift_4h_0.50`), so capacity is the one thing held constant.
- `avail_hours_et` uses a **fixed UTC−5 offset** (EST year-round, no DST), including for
  ERCOT. Any hour-of-day analysis must use that same convention or DR availability will
  appear misaligned by an hour for half the year.

All of the above is recorded in `/dr_config` per file, so Stage 0 reads it from the data
and treats the filename as advisory only. This is what makes the pipeline survive input
swaps and mixed `[[dr_device]]` configs.

### The `pras_input` attribute is the DC-load-scenario key

Do **not** parse scenario from the filename. Every result file records its input:

- `baseline.h5` → `../PJM_PRAS_2032i0.pras` ⇒ **base DC load**
- everything else → `../PJM_PRAS_2032i0_eer_central.pras` ⇒ **high DC load**

Rule: `dc_scenario = "high" if "eer_central" in pras_input else "base"`.

### Sweep design (current inputs)

`fractions = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]`,
`seed = 14`, `samples = 1000` throughout. **Asymmetric:** PJM has shed+shift ×
{4,8,16}h (68 files); ERCOT has shift only × {4,8}h (24 files). Never assume a complete
grid.

### Input `.pras` files (system state — needed for attribution)

`/kfs2/projects/reedsweto/ssundar/FY26_largeloads_DR/{PJM_PRAS_2032i0,ERCOT_PRAS_2032i1}[_eer_central].pras`

| Path | Shape | Use |
|---|---|---|
| `/regions/load` | `(131400, Nreg)` | Hourly load. **High − base = the added DC load timeseries.** |
| `/generators/_core` | `(Ngen,)` compound `(name, category, region)` | Tech type per unit — `gas-cc`, solar, wind, … |
| `/generators/capacity` | `(131400, Ngen)` | Hourly available capacity ⇒ per-region VRE output and firm capacity |
| `/storages/*`, `/generatorstorages/*` | | Storage energy/power by region |
| `/lines/*`, `/interfaces/*` | | Transfer limits for import-headroom features |

PJM: 2528 generators, 283 MB file. **`/generators/capacity` is ~1.3 GB decompressed** —
the only genuinely large read in the pipeline, and the reason Stage 2 gets a compute
node. Read it chunked along the generator axis and aggregate to per-region-per-category
on the fly; the aggregated result is ~10 MB per category.

### Existing summaries

- `dr_sweep_results/{pjm,ercot}/cases.csv` — case-level NEUE, produced by
  `merge_cases.jl`. Use as a **cross-check** on Stage 1, not as an input.
- `dr_sweep_results/load_add_summary.md` — peak/min added MW per region.
- `archive_eer_central_csv/.../experiment_setup.md` — **older vintage, conflicting
  numbers** (p99 peak added = 14,533 MW vs 4,696 MW in `load_add_summary.md`). Since
  `borrow_capacity = fraction × peak_added`, this discrepancy changes what a "50 % DR"
  case physically means. **Resolve by reading `/dr_config/borrow_capacity_mw` directly
  from each result file** — that's what was actually simulated. Flag the conflict in the
  report; do not silently pick one.

---

## 2. Pipeline architecture

Five stages, each a script writing a cached artifact. Every stage is re-runnable and
idempotent; swapping inputs means editing `config/paths.yaml` and re-running from
Stage 0.

```
config/paths.yaml ──┐
                    ▼
[0] build_registry    → cache/registry.csv                (one row per case)     [login OK]
                    ▼
[1] extract_eue       → cache/eue/<system>.npz            (arrays, case-stacked) [login OK]
                    ▼
[2] extract_features  → cache/features/<system>.npz       (hour × region)        [SBATCH]
                    ▼
[3] detect_events     → cache/events.csv                  (EUE episodes)         [login OK]
                    ▼
[4] attribute         → outputs/tables/*.csv, figures/*.png, report.md           [login OK]
```

Rationale for the split: Stage 2 is the only stage touching the big `.pras` files, and
its output is case-independent — shared by all 68 PJM cases. Adding a new DR sweep
re-runs Stage 1 only.

**Storage format.** Arrays stay arrays. One case's `/eue` is 131,400 × 19 f32 ≈ 10 MB;
all 92 files together are under 1 GB. Stage 1 stacks per system into a single `.npz`
with a shared `case_id` axis. Small tabular outputs (registry, events, rollups) are CSV.
No long-format explosion, no parquet, no pyarrow.

### Layout

```
neue_diagnostics/
├── config/
│   ├── paths.yaml              # roots, systems, pras map, conda env, slurm account/partition
│   └── analysis.yaml           # eps threshold, event gap, feature list, knee criteria
├── src/neue_diag/
│   ├── config.py               # load + validate yaml, resolve paths
│   ├── registry.py             # stage 0
│   ├── io_results.py           # h5 readers (+ transpose assertion)
│   ├── io_pras.py              # .pras readers, chunked generator aggregation
│   ├── features.py             # stage 2
│   ├── events.py               # stage 3
│   ├── attribute.py            # stage 4
│   ├── saturation.py           # DR knee-point analysis (§3, 4e)
│   └── plots.py
├── scripts/
│   ├── 00_build_registry.py    # all take --config, --system; write to cache/; exit
│   ├── 01_extract_eue.py
│   ├── 02_extract_features.py
│   ├── 03_detect_events.py
│   └── 04_attribute.py
├── slurm/
│   ├── stage02_features.sh     # the one that genuinely needs a node
│   ├── run_all.sh              # chained --dependency=afterok
│   └── README.md               # how to set account/partition
├── cache/                      # gitignored
├── outputs/
└── tests/
```

Scripts are plain CLIs — runnable interactively or under `sbatch`, identical either way.
Account and partition live in `config/paths.yaml`, never in the scripts.

---

## 3. Stage specifications

### Stage 0 — `00_build_registry.py`  *(login node)*

Walk `<root>/<system>/results/*.h5`. Read root attrs + `/summary` + `/dr_config` (all
cheap — no bulk dataset reads). One row per case:

```
case_id, system, path, case_label, dc_scenario, pras_input, samples, seed,
dr_mode, dr_energy_hours, dr_fraction, dr_payback_h, dr_avail_window_h,
dr_avail_hours_et, dr_borrow_capacity_total_mw, n_devices,
n_regions, n_timesteps, eue_mean_mwh, eue_stderr_mwh, neue_ppm,
dr_eue_mean_mwh, dr_neue_ppm, mtime
```

- `dc_scenario` from `pras_input`, **not** filename.
- `dr_mode`, `dr_energy_hours`, `dr_fraction` from `/dr_config` where present, falling
  back to a filename regex only when `dr_config` is empty. Unparseable → warn, keep row,
  set `None`.
- `dr_avail_hours_et` carried through verbatim so shed/shift availability asymmetry is
  visible in every downstream table.
- Validate: identical `/regions` and `/timestamps` across all cases in a system. A
  swapped-in file that disagrees must **fail loudly** — silent misalignment is the main
  way this analysis goes wrong.
- Reconcile `neue_ppm` against `cases.csv`; report mismatches.

Reference cases defined here: `ref_high_nodr = (dc_scenario='high', dr_mode=None)` =
`baseline_with_load_added`; `ref_base = (dc_scenario='base')` = `baseline`.

### Stage 1 — `01_extract_eue.py`  *(login node; ~1 GB, few minutes)*

Per system, read `/eue`, `/dr_energy`, `/dr_shortfall` from every registry case. Write
`cache/eue/<system>.npz`:

- `eue` — `(Ncase, 131400, Nreg)` f32
- `dr_energy`, `dr_shortfall` — same shape
- `case_ids`, `regions`, `hour_idx` — axis labels

PJM: 68 × 131400 × 19 × 4 B ≈ 680 MB per array. Store f32, and if memory pressure
appears, write one `.npz` per case and lazily stack — but a single file is simpler and
should fit.

Also emit `cache/rollups/<system>_annual.csv` (small, always useful):
`case_id, region, weather_year, eue_mwh, load_mwh, neue_ppm, n_event_hours`.

### Stage 2 — `02_extract_features.py`  *(SBATCH — the expensive one)*

Per system, read both `.pras` files, build an hour × region feature array set keyed on
`hour_idx`.

**Time features:** `timestamp_utc, weather_year, month, day_of_year, hour_utc,
hour_et_fixed (UTC−5, matching DR convention), hour_local, is_weekend, season`.

**Load:** `load_base_mw`, `load_high_mw`, `load_added_mw = high − base`,
`load_added_frac`. Also per-region added-load **load factor** (mean/peak) — quantifies
how flat the DC adder actually is instead of assuming.

**Supply** (from `/generators/capacity` grouped by `_core.category`, chunked):
`cap_solar_mw`, `cap_wind_mw`, `cap_firm_mw`, `cf_solar`, `cf_wind`,
`storage_energy_mwh`, `storage_power_mw`, `import_cap_mw`.

**Derived margins** — what attribution actually leans on:
`net_load_mw = load − solar − wind`; `margin_mw = cap_total − load`;
`margin_with_imports_mw`; plus percentile ranks of load / net load / margin within
region and within weather year.

**System aggregates** on `hour_idx`: `sys_load`, `sys_net_load`, `sys_margin`, and each
region's share.

Write `cache/features/<system>.npz` + a manifest recording source `.pras` mtimes so
later stages detect staleness.

### Stage 3 — `03_detect_events.py`  *(login node)*

An event = maximal run of consecutive hours with `eue > eps` in a region for a case,
bridging gaps ≤ `gap_h` (default 1). Per event:

```
case_id, system, region, event_id, start_hour_idx, end_hour_idx, duration_h,
weather_year, month, start_hour_et, total_eue_mwh, peak_eue_mwh,
concurrent_regions, is_systemwide
```

`eps` matters: `/eue` is a mean over 1000 samples, so one failed sample yields a tiny
nonzero. Default `eps = 0.1 MWh`, exposed in `analysis.yaml`, with a reported
sensitivity sweep — event counts move a lot with this knob.

Also **concentration metrics** per case-region: share of annual EUE in top 1/10/100
hours; hours needed to reach 50 %/90 % of total EUE. Cleanest answer to "is high NEUE a
few extreme hours or a chronic condition," and it likely differs between base and high
DC.

### Stage 4 — `04_attribute.py`  *(login node)*

Seven analyses, each → one table + one figure.

**4a. Where — regional decomposition.** Per case: EUE by region; region NEUE
(`region EUE / region load`); region share of system EUE vs share of system load vs
share of *added* load. A region with 40 % of EUE but 12 % of added load is the headline.
Scatter region NEUE against `load_added_frac`.

**4b. When — weather year and seasonality.** EUE by weather year (15 bars), by month, by
hour-of-day (ET). Split base vs high DC. Key test: **does added DC load change the
*shape* of when EUE occurs, or just the level?** Compare normalized hour-of-day and
month distributions — a shift means the DC load changed the binding condition; pure
scale-up means it didn't.

**4c. Under what conditions.** Feature values in EUE hours vs all hours, EUE-weighted:
`load_pctile, net_load_pctile, cf_solar, cf_wind, margin_mw, load_added_mw`. Table of
(feature, all-hours mean, EUE-weighted mean, top-100-hours mean). Plus 2-D density of
EUE over (net-load percentile × solar CF) to separate load-driven from VRE-driven
events.

**4d. Base → high delta attribution.** `ΔEUE = EUE_high_nodr − EUE_base`. Decompose:
how much of Δ lands in hours that *already* had EUE (amplification) vs previously clean
hours (new failure modes)? Regress Δ region-EUE on added MW, baseline margin, and import
capability across regions to find what predicts vulnerability.

**4e. DR effectiveness and saturation.** *(see §4 — the diminishing-returns question)*

**4f. Weather-year deep-dive.** Worst 2–3 (weather year × region) combinations by EUE:
plot hourly traces around the largest events — load, added load, solar, wind, margin,
EUE, DR energy, DR shortfall, DR availability window shading. One figure per event. This
is what makes the statistics legible and usually what ends up in the deck.

**4g. Cross-case ranking.** Every case ranked by NEUE with stderr bars, faceted by
system, colored by mode, to answer "which configuration is simply best" directly.

---

## 4. The diminishing-returns analysis (4e, called out)

The question — *"at 50 % DR we see the most improvement and after that maybe not"* — is
a **knee/saturation** question on the NEUE-vs-fraction curve. Treat it as first-class,
not a byproduct.

For each `(system, dr_mode, energy_hours)` curve over the 11 fractions:

1. **Level curve.** `NEUE(f)` with Monte Carlo stderr bands, plus horizontal rules at
   `ref_base` (the "how much of the DC-load penalty did we buy back" target) and
   `ref_high_nodr` (the do-nothing case).
2. **Marginal return.** `ΔNEUE/Δf` between consecutive fractions — the discrete
   derivative. Saturation shows up as this trending to zero.
3. **Return per physical MW.** Divide by `Δ borrow_capacity_mw` from `/dr_config`, so
   curves are comparable across modes and across systems with different added load.
   This is the number that actually supports a recommendation.
4. **Knee detection**, reported with the criterion stated (they disagree, and that's
   informative):
   - **Kneedle** (max distance to the chord joining endpoints) — geometric knee.
   - **Fraction achieving X % of total achievable reduction** for X ∈ {80, 90, 95},
     where total achievable = `NEUE(0) − NEUE(1.0)`.
   - **Last fraction whose marginal return exceeds a threshold** (e.g. 10 % of the
     first increment's return).
5. **Availability overlap — disentangling the shed/shift confound.** For each case,
   compute the share of its EUE occurring in hours when its own DR was *allowed* to run,
   using `/dr_config/avail_hours_et` (fixed UTC−5) against the Stage 3 event timestamps.
   Report as `eue_in_window_frac`. If low, the availability window explains the case's
   performance and the payback difference is a red herring. This converts the §1
   confound from a caveat into a measured quantity, and must accompany every
   shed-vs-shift claim.
6. **Is saturation physical or structural?** Cross-check against `dr_shortfall` and
   `dr_energy`: if higher fractions add capacity that is never called, saturation is
   *dispatch-limited* (events don't coincide with availability, or energy capacity binds
   before power capacity). If DR is fully called yet EUE persists, it's
   *magnitude-limited* — the shortfall exceeds what DR can cover. **These have opposite
   policy implications** and the data distinguishes them, so this check is required, not
   optional.
7. **Does the knee move?** Compare knee fraction across modes, energy_hours, and regions
   — and note whether shed's apparent advantage is confounded by its *narrower
   availability window* (§1). Any shed-vs-shift claim must carry that caveat.
8. **Best case overall.** Report the minimum-NEUE case per system, and whether it is
   statistically distinguishable from nearby cases given `eue_stderr` — with 1000
   samples, several top cases may be within noise of each other, and saying so is more
   honest than naming a single winner.

Output: one saturation figure per system (curves + marked knees), plus
`outputs/tables/dr_saturation.csv` with a row per curve giving knee fraction under each
criterion, NEUE at knee, NEUE floor, and the dispatch- vs magnitude-limited verdict.

---

## 5. Known issues to handle explicitly

1. **`/eue` is `(N, R)` in h5py**, not `(R, N)` as `usage.md` states (Julia column-major).
   Assert on load.
2. **Region column order is alphabetical, not numeric** (`p99` between `p126` and
   `z122`). Index by `/regions` labels, never positionally.
3. **`4h`/`8h`/`16h` sets `energy_hours` AND `payback_hours`** — and for shed, the
   availability-window width too. Not a duration limit.
4. **Shed and shift differ in two ways at once** — forgiven payback *and* restricted
   availability windows, pushing in opposite directions. Not a clean A/B; every mode
   comparison must carry the `eue_in_window_frac` diagnostic (§4.5).
4b. **`usage.md`'s availability table is stale** for `shed_16h` (says 12–8 PM, file says
   6 AM–9 PM). Always read `/dr_config`, never the docs.
5. **DR availability uses fixed UTC−5** (no DST), including ERCOT. Match that convention
   in hour-of-day analysis.
6. **Timestamps are UTC**; years run 2007-01-01 → 2021-12-27 (2021 incomplete). Derive
   `weather_year` from `hour_idx // 8760` and *verify* against the timestamp year rather
   than trusting either alone.
7. **Added DC load is close to flat** (p99: 4696 MW peak vs 3521 MW min). "Was the DC
   load shaped differently" likely has a thin answer with these inputs — quantify via
   load factor rather than assuming. **`p126` has a negative minimum (−124 MW)**: the
   high scenario is *below* base in some hours. Do not assume Δload ≥ 0.
8. **Conflicting peak-added numbers** between `experiment_setup.md` (archive) and
   `load_add_summary.md` — resolve from `/dr_config/borrow_capacity_mw`, flag in report.
9. **Per-hour EUE is much noisier than the ~1–2 % case-level stderr suggests.** Report
   extremes as top-100-hour aggregates, not single-hour anecdotes.
10. **Asymmetric sweep** (no shed for ERCOT). Cross-system comparisons subset to the
    common design or state clearly that they don't.
11. **`dr_config` is empty for baselines** — readers must tolerate zero-length datasets.

---

## 6. Build order

| Step | Deliverable | Where | Unblocks |
|---|---|---|---|
| 1 | `config.py`, `paths.yaml`, `registry.py`, `00_build_registry.py` | login | everything |
| 2 | `io_results.py` + `01_extract_eue.py`, reconciled against `cases.csv` | login | 4a, 4b, 4e, 4g |
| 3 | `saturation.py` + analyses 4e/4g — **the diminishing-returns answer** | login | first real result |
| 4 | analyses 4a/4b (Stage 1 only) | login | regional/temporal story |
| 5 | `io_pras.py` + `02_extract_features.py` + `slurm/stage02_features.sh` | **sbatch** | 4c, 4d, 4f |
| 6 | `03_detect_events.py` + concentration metrics | login | 4f |
| 7 | analyses 4c/4d/4f | login | full story |
| 8 | `report.md` generator stitching tables + figures | login | deliverable |

Steps 1–4 need **no compute allocation and no `.pras` reads** — they answer the
saturation question and the regional/temporal question from the 8 MB result files alone.
Recommend running through step 4 and reviewing before committing to the Stage 2 feature
list; the data may make some features obviously irrelevant.
