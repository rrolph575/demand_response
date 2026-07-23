#!/bin/bash
# Render a markdown report to PDF.
#
#     ./scripts/make_pdf.sh                          # brief_results_summary.md
#     ./scripts/make_pdf.sh FINDINGS.md
#
# Needs pandoc (ships inside the reeds2 conda env) and a LaTeX engine
# (texlive module). Neither is on PATH by default, so both are set up here.
#
# Font note: this machine has DejaVu Sans but NOT DejaVu Serif. DejaVu Sans is
# used deliberately -- it covers the Unicode in these reports (arrows, ≤, ×,
# ·, em dashes) that Nimbus Roman and Latin Modern do not.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SRC="${1:-brief_results_summary.md}"
OUT="${SRC%.md}.pdf"

export PATH=/home/rrolph/.conda-envs/reeds2/bin:$PATH
module load texlive/20220321 2>/dev/null || \
    echo "note: 'module load texlive' failed; assuming a LaTeX engine is on PATH"

command -v pandoc  >/dev/null || { echo "pandoc not found"  >&2; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex not found" >&2; exit 1; }

pandoc "$SRC" -o "$OUT" \
    --pdf-engine=xelatex \
    --resource-path=.:outputs/figures \
    --include-in-header=config/pdf_header.tex \
    -V geometry:"margin=0.9in" \
    -V papersize:letter \
    -V fontsize:10pt \
    -V colorlinks:true -V linkcolor:MidnightBlue -V urlcolor:MidnightBlue \
    -V mainfont:"DejaVu Sans" \
    -V monofont:"DejaVu Sans Mono" \
    --toc --toc-depth=2 \
    --metadata title="Datacenter load, demand response, and resource adequacy" \
    --metadata subtitle="PJM and ERCOT · ReEDS 2032 · PRAS" \
    --metadata date="$(date +%Y-%m-%d)"

echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
