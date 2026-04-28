# skills/__init__.py — skill palette baseline (24 skills)
#
# Imports the 3 skill families and builds the unified dict passed to AgentConfig.
#
# Usage:
#   from skills import ALL_SKILLS
#   cfg = AgentConfig(..., skills=ALL_SKILLS, ...)
#
# To extend with domain-specific skills:
#   from skills import ALL_SKILLS
#   from my_domain import extra_skill_a, extra_skill_b
#   skills = {**ALL_SKILLS, "extra_skill_a": extra_skill_a, ...}

from skills.d import SKILLS as _D
from skills.h import SKILLS as _H
from skills.g import SKILLS as _G

ALL_SKILLS: dict = {**_D, **_H, **_G}

__all__ = ["ALL_SKILLS"]
