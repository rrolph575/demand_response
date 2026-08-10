# ERCOT per-MW DR-effect maps

Per-region maps of **EUE change per MW of added datacenter load**:

    value = (EUE_case − EUE_noDR) / peak-added-MW      [MWh EUE per MW]

Same metric, scheme, and bins as the PJM set (see `../pjm_per_mw_maps/README.md`).
Blue = DR removed EUE per MW (good), red = DR increased EUE per MW (bad), grey =
no EUE / no added load. EUE_noDR = `baseline_with_load_added`; denominator = each
region's peak added load (fixed per region).

| folder | contents |
|---|---|
| `_full_penalty_reference/` | the +DC no-DR penalty vs base DC (context) |
| `shift_4h/ 8h/` | shift DR, 11 fractions each |

**ERCOT's sweep is shift-only** — no shed, no 16 h — so there is no shed folder.

**What it shows:** ERCOT shift *redistributes* EUE. It removes EUE per MW in the
big-shortfall regions (p64 −58, p65 −43, p63 −34 MWh/MW) but makes others *worse*:
p67/Houston gains new EUE from load payback (+33 MWh/MW, +73,006 MWh), and the
west-Texas regions p60/p61/p62 pick up EUE they did not have. Net system EUE still
falls (the big regions dominate), but the per-MW map exposes the redistribution
the saturation curve hides — the same shift behavior seen in PJM.

Regenerate with:
`python scripts/07_rel_eue_map.py --system ercot --per-mw --all-dr --label-color "#33cc33"`
(then re-run the folder move).
