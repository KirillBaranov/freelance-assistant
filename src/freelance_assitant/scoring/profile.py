"""Load executor profile from config/profile.yaml."""

from __future__ import annotations

from typing import Any

import yaml

from freelance_assitant.config import CONFIG_DIR

_profile: dict[str, Any] | None = None


def load_profile() -> dict[str, Any]:
    global _profile
    if _profile is not None:
        return _profile

    path = CONFIG_DIR / "profile.yaml"
    if not path.exists():
        _profile = {
            "primary_skills": [],
            "secondary_skills": [],
            "preferred_categories": [],
            "avoid_keywords": [],
            "min_budget_rub": 3000,
            "preferred_max_duration_days": 14,
        }
        return _profile

    with open(path) as f:
        _profile = yaml.safe_load(f) or {}

    return _profile


def reload_profile() -> dict[str, Any]:
    global _profile
    _profile = None
    return load_profile()
