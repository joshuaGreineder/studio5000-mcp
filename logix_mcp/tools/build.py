"""Build tools: ``build_project`` (with target) + backwards-compatible alias."""
from __future__ import annotations

from logix_designer_sdk.enums import RequestedBuildTarget

from logix_mcp._common import (
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_build_target,
    preflight_project_path,
)


_TARGET_MAP = {
    "default": RequestedBuildTarget.DEFAULT_TARGET,
    "physical": RequestedBuildTarget.PHYSICAL_CONTROLLER,
    "echo": RequestedBuildTarget.ECHO_CONTROLLER,
}


@mcp.tool()
async def build_project(path: str, target: str = "default") -> str:
    """Build the project against ``default`` / ``physical`` / ``echo`` (maps to ``RequestedBuildTarget``)."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_build_target(target)
    if pf:
        return pf

    async def _do() -> str:
        p = _resolve(path)
        t_key = str(target).strip().lower()
        t_enum = _TARGET_MAP[t_key]
        async with _opened(p) as proj:
            await proj.build(t_enum)
        return f"[OK] Build ({t_key}) completed for {p}"

    return await _run("build_project", _do, path=path, target=target)


@mcp.tool()
async def validate_project(path: str) -> str:
    """Backwards-compatible alias for ``build_project(path, 'default')``."""
    return await build_project(path, "default")


__all__ = ["build_project", "validate_project"]
