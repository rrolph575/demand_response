# PJM regional NEUE-change maps

Per-region **NEUE change vs the high-DC no-DR case**:

    value = NEUE_case − NEUE_noDR      [ppm],   NEUE = 1e6 * EUE / load

- **negative (blue)** = DR *lowered* that region's NEUE (good)
- **positive (red)**  = DR *raised* it (worse)
- **grey** = no EUE / no load

**Consistent legend across every figure** — all cases and BOTH systems share the
same fixed bins (`−1000…−100…−10…−1…0…1…10…100 ppm`), so any two maps (PJM or
ERCOT, any case) are directly comparable. Each region is labeled `p#` + signed ppm.

| folder | contents |
|---|---|
| `shed_1h_alwayson/` | always-on 100 % shed (always-on caveat — see per-MW README) |
| `shed_4h/ 8h/ 16h/`  | windowed shed, 11 fractions each |
| `shift_4h/ 8h/ 16h/` | shift, 11 fractions each |

Files within a family sort by DR fraction. Regenerate:
`python scripts/07_rel_eue_map.py --system pjm --neue-diff --all-dr --bins="-1000,-100,-10,-1,0,1,10,100" --label-color "#33cc33" --label-pos "p113:0.08,0.50"`
