"""Config loading and path resolution.

Everything the pipeline knows about where data lives comes from config/paths.yaml
and config/analysis.yaml. Swapping input files is a config edit, not a code edit.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Config:
    """Resolved view of paths.yaml + analysis.yaml."""

    def __init__(self, paths: dict, analysis: dict, project_root: Path):
        self.paths = paths
        self.analysis = analysis
        self.project_root = project_root

        self.sweep_root = Path(paths["sweep_root"])
        self.pras_root = Path(paths["pras_root"])
        self.cache_dir = self._resolve(paths.get("cache_dir", "cache"))
        self.output_dir = self._resolve(paths.get("output_dir", "outputs"))
        self.systems = paths["systems"]

    def _resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else self.project_root / p

    # -- system accessors ----------------------------------------------------

    def system_names(self) -> list[str]:
        return list(self.systems)

    def system(self, name: str) -> dict:
        if name not in self.systems:
            raise KeyError(
                f"unknown system {name!r}; configured systems are "
                f"{sorted(self.systems)}"
            )
        return self.systems[name]

    def results_dir(self, name: str) -> Path:
        return self.sweep_root / self.system(name)["results_subdir"]

    def cases_csv(self, name: str) -> Path | None:
        rel = self.system(name).get("cases_csv")
        return self.sweep_root / rel if rel else None

    def pras_path(self, name: str, scenario: str) -> Path:
        """scenario is 'base' or 'high'."""
        return self.pras_root / self.system(name)["pras"][scenario]

    # -- output helpers ------------------------------------------------------

    def table_path(self, filename: str) -> Path:
        d = self.output_dir / "tables"
        d.mkdir(parents=True, exist_ok=True)
        return d / filename

    def figure_path(self, filename: str) -> Path:
        d = self.output_dir / "figures"
        d.mkdir(parents=True, exist_ok=True)
        return d / filename

    def cache_path(self, *parts: str) -> Path:
        p = self.cache_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def load_config(
    paths_yaml: str | Path | None = None,
    analysis_yaml: str | Path | None = None,
    project_root: Path | None = None,
) -> Config:
    root = Path(project_root) if project_root else PROJECT_ROOT
    paths_yaml = Path(paths_yaml) if paths_yaml else root / "config" / "paths.yaml"
    analysis_yaml = (
        Path(analysis_yaml) if analysis_yaml else root / "config" / "analysis.yaml"
    )

    with open(paths_yaml) as fh:
        paths = yaml.safe_load(fh)
    with open(analysis_yaml) as fh:
        analysis = yaml.safe_load(fh)

    for key in ("sweep_root", "pras_root", "systems"):
        if key not in paths:
            raise ValueError(f"{paths_yaml} is missing required key {key!r}")

    return Config(paths, analysis, root)
