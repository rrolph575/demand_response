# ERCOT regional NEUE-change maps

Per-region NEUE change vs the high-DC no-DR case: `NEUE_case − NEUE_noDR` [ppm].
Same metric, diverging blue(lower)/red(higher) scheme, and **the same fixed bins
as PJM** (`−1000…100 ppm`) — so PJM and ERCOT maps are directly comparable.
ERCOT's sweep is shift-only (no shed, no 16 h). See `../pjm_neue_diff_maps/README.md`.

Regenerate:
`python scripts/07_rel_eue_map.py --system ercot --neue-diff --all-dr --bins="-1000,-100,-10,-1,0,1,10,100" --label-color "#33cc33"`
