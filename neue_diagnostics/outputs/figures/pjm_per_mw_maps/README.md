# PJM per-MW DR-effect maps

Per-region maps of **EUE change per MW of added datacenter load**:

    value = (EUE_case − EUE_noDR) / peak-added-MW      [MWh EUE per MW]

- **EUE_noDR** = high-DC, no-DR case (`baseline_with_load_added`)
- **peak-added-MW** = each region's peak added datacenter load (fixed per region,
  so maps are comparable across cases; it is also the region's DR capacity at
  100 % deployment)

**Colors (diverging):** blue = DR *removed* EUE per MW (negative, good), red = DR
*increased* EUE per MW (positive, bad), near-white ≈ no effect, grey = no EUE or
no added load. Each region is labeled with the per-MW value and the raw ΔEUE (MWh).

Decade bins: `−1000…−100 / −100…−10 / −10…−1 / −1…0 / 0…1 / 1…10 / 10…100` MWh/MW.

| folder | contents |
|---|---|
| `_full_penalty_reference/` | the +DC no-DR penalty vs **base DC** (a different metric — ratio above pre-existing EUE; kept for context) |
| `shed_1h_alwayson/` | always-on 100 % shed — see caveat below |
| `shed_4h/ 8h/ 16h/`  | windowed shed, 11 fractions each |
| `shift_4h/ 8h/ 16h/` | shift, 11 fractions each |

Files within a family sort by DR fraction (`…_0.05` → `…_1.00`).

**What it shows:** *where DR capacity is most productive per MW.* The small,
deliverability-constrained regions dominate — e.g. under always-on shed, **p124
removes 451 MWh per MW** of its 30 MW of added load, vs p99 at 182 MWh/MW (huge
total, but it has 4,696 MW of added load) and p123 at just 2.8.

**Caveat — `shed_1h` is always-on.** Its "1h" is the energy/payback duration; its
availability window is empty (always on). So its per-MW effect is *not*
apples-to-apples with the windowed `shed_4h/8h/16h`, which can only use their
capacity inside a daily window. It wins partly on availability, not just mechanism.

Regenerate with:
`python scripts/07_rel_eue_map.py --system pjm --per-mw --all-dr --label-color "#33cc33" --label-pos "p113:0.08,0.50"`
(then re-run the folder move). The full-penalty reference is
`python scripts/07_rel_eue_map.py --system pjm --case baseline_with_load_added`.
