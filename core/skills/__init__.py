# skills/__init__.py
from __future__ import annotations
import importlib.util
import inspect
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


def _format_signature(name: str, fn) -> str:
    """Render an exact `name(param, opt=default, ...)` call signature from the
    skill function itself.

    This goes into the system prompt next to every skill. It is the cheapest
    fix for the most common skill-call failure: the model inventing or
    over-generalizing parameters (e.g. passing `overwrite` to append_file, or
    `output_mode` to grep_search). Showing the precise parameter list — and,
    by omission, which parameters do NOT exist — kills that whole error class.
    Derived from the live function, so it can never go stale.
    """
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return f"{name}(...)"
    parts = []
    for p in sig.parameters.values():
        if p.name in ("self", "cls"):
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"*{p.name}")
            continue
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            parts.append(f"**{p.name}")
            continue
        if p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            d = repr(p.default)
            if len(d) > 24:  # keep long string defaults from bloating the prompt
                d = d[:21] + "..."
            parts.append(f"{p.name}={d}")
    return f"{name}({', '.join(parts)})"


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
        # Strip wip_ prefix to find the actual function name and registry key.
        # This allows skill folders to be prefixed with wip_ for testing
        # without changing the function name or the agent-visible skill name.
        skill_name = folder.name[len("wip_"):] if folder.name.startswith("wip_") else folder.name
        fn = getattr(mod, skill_name, None)
        if fn is None:
            continue
        registry[skill_name] = fn
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            summary_part = text.split("---")[0].strip()
            # Extract just the description line (after the # title)
            lines = [ln for ln in summary_part.splitlines() if ln.strip() and not ln.startswith("#")]
            summary = lines[0] if lines else summary_part
            # Append the exact call signature on its own line so the model
            # sees the precise parameters every turn, not only after a
            # get_skill_details call.
            sig = _format_signature(skill_name, fn)
            summaries.append(f"**{skill_name}**: {summary}\n  Call: {sig}")
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
