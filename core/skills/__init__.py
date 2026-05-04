# skills/__init__.py
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def _load_skills():
    registry = {}
    summaries = []
    for folder in sorted(SKILLS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        skill_file = folder / "skill.py"
        readme = folder / "README.md"
        if not skill_file.exists():
            continue
        mod_name = f"skills.{folder.name}.skill"
        spec = importlib.util.spec_from_file_location(mod_name, skill_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod  # register BEFORE exec so late imports work
        sys.modules[f"skills.{folder.name}"] = mod
        spec.loader.exec_module(mod)
        fn = getattr(mod, folder.name, None)
        if fn is None:
            continue
        registry[folder.name] = fn
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            summary_part = text.split("---")[0].strip()
            # Extract just the description line (after the # title)
            lines = [l for l in summary_part.splitlines() if l.strip() and not l.startswith("#")]
            summary = lines[0] if lines else summary_part
            summaries.append(f"**{folder.name}**: {summary}")
    return registry, "\n".join(summaries)


ALL_SKILLS, SKILLS_SUMMARY = _load_skills()


def get_skill_details(name: str) -> str:
    """
    Load the full documentation for a skill.
    Returns the complete README.md content (parameters, return value, notes).
    Call this before using a skill you are unsure about.
    """
    readme = SKILLS_DIR / name / "README.md"
    if not readme.exists():
        available = sorted(
            f.name for f in SKILLS_DIR.iterdir()
            if f.is_dir() and not f.name.startswith("_")
        )
        return (
            f"ERROR: no documentation found for skill '{name}'.\n"
            f"Available skills: {available}"
        )
    return readme.read_text(encoding="utf-8")


# Add get_skill_details to the registry so the agent can call it
ALL_SKILLS["get_skill_details"] = get_skill_details

__all__ = ["ALL_SKILLS", "SKILLS_SUMMARY", "get_skill_details"]
