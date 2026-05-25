"""MCP resources: ``logix://projects/list`` and ``logix://sdk/info``."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from logix_designer_sdk import LogixProject

from logix_mcp._common import _sdk_version, mcp


_LISTING_CAP = 200


def _scan_root() -> Path:
    """Return ``LOGIX_MCP_ROOT`` env var (if set + exists) else the cwd."""
    env = os.environ.get("LOGIX_MCP_ROOT", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.exists() and p.is_dir():
            return p
    return Path.cwd()


@mcp.resource("logix://projects/list")
def projects_list() -> str:
    """List ``*.ACD`` and ``*.L5X`` projects under ``LOGIX_MCP_ROOT`` (or cwd), capped at 200."""
    root = _scan_root()
    matches: list[Path] = []
    try:
        for ext in ("*.ACD", "*.L5X"):
            matches.extend(root.glob(ext))
    except OSError as e:
        return f"[FAIL] projects/list: cannot scan {root}: {e}"

    matches.sort(key=lambda p: p.name.lower())
    capped = matches[:_LISTING_CAP]
    if not capped:
        return f"(no .ACD or .L5X files under {root})"
    lines = [f"Scanning: {root}"]
    for p in capped:
        try:
            size_mb = p.stat().st_size / (1024 * 1024)
            lines.append(f"  {p.name}  ({size_mb:.1f} MB)  {p}")
        except OSError:
            lines.append(f"  {p.name}  (size unknown)  {p}")
    if len(matches) > _LISTING_CAP:
        lines.append(
            f"... ({len(matches) - _LISTING_CAP} more entries; "
            f"listing capped at {_LISTING_CAP})"
        )
    return "\n".join(lines)


_AREA_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Project I/O",
        (
            "open_logix_project",
            "save",
            "save_as",
            "convert",
            "create_new_project",
            "get_processor_types",
            "close",
        ),
    ),
    (
        "Online",
        (
            "get_communications_path",
            "set_communications_path",
            "go_online",
            "go_offline",
            "read_connected_state",
            "read_controller_mode",
            "change_controller_mode",
            "change_controller_type",
            "upload",
            "upload_to_new_project",
            "download",
        ),
    ),
    ("Build", ("build",)),
    (
        "Tags",
        ("get_tag_value", "set_tag_value"),
    ),
    ("Program", ("get_all_executables",)),
    (
        "Partial",
        (
            "partial_export_to_xml_file",
            "partial_import_from_xml_file",
            "partial_import_with_target_from_xml_file",
            "partial_import_rungs_from_xml_file",
        ),
    ),
    (
        "Protection",
        (
            "lock_executable",
            "unlock_executable",
            "is_executable_locked",
            "protect_with_password",
            "protect_with_license",
            "is_executable_protected",
            "unprotect",
            "lock_all",
            "unprotect_all",
            "protect_all_with_password",
            "protect_all_with_license",
        ),
    ),
    (
        "Safety",
        (
            "is_safety_locked",
            "safety_lock",
            "safety_unlock",
            "set_safety_lock_password",
            "set_safety_unlock_password",
            "generate_safety_signature",
            "delete_safety_signature",
            "get_safety_signature",
            "get_safety_network_number",
        ),
    ),
    (
        "SD card",
        ("store_image_on_sd_card", "load_image_from_sd_card"),
    ),
    (
        "Events",
        ("add_event_handler", "remove_event_handler", "clear_event_handlers"),
    ),
)


def _group_methods(names: list[str]) -> list[tuple[str, list[str]]]:
    """Bucket ``names`` into the documented SDK areas; leftovers go to ``Other``."""
    remaining = set(names)
    grouped: list[tuple[str, list[str]]] = []
    for area, keywords in _AREA_KEYWORDS:
        hits: list[str] = []
        for n in names:
            if n not in remaining:
                continue
            for kw in keywords:
                if n == kw or n.startswith(kw + "_"):
                    hits.append(n)
                    break
        for n in hits:
            remaining.discard(n)
        if hits:
            grouped.append((area, sorted(hits)))
    if remaining:
        grouped.append(("Other", sorted(remaining)))
    return grouped


@mcp.resource("logix://sdk/info")
def sdk_info() -> str:
    """Report Python version, installed ``logix_designer_sdk`` version, and grouped ``LogixProject`` methods."""
    py_ver = sys.version.split()[0]
    sdk_ver = _sdk_version()
    methods = sorted(
        name
        for name in dir(LogixProject)
        if not name.startswith("_") and callable(getattr(LogixProject, name, None))
    )

    lines = [
        f"Python: {py_ver}",
        f"logix_designer_sdk: {sdk_ver}",
        f"LogixProject method count: {len(methods)}",
        "",
        "Methods by area (gated tools light up automatically when methods appear):",
    ]
    for area, group in _group_methods(methods):
        lines.append(f"  [{area}]")
        for n in group:
            lines.append(f"    - {n}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discoverable string-enum options for every closed-set parameter the server
# validates.  Models can call ``list_options()`` once at the start of a session
# and learn every legal value without reading the README.  For the one *open*
# set the server accepts -- ``processor_type`` -- the entry points the caller
# at ``get_processor_types(major_revision=<rev>)`` since the legal values are
# determined by which Logix Designer revisions are installed.

_OPTIONS: dict[str, dict[str, object]] = {
    "target": {
        "used_by": ["build_project"],
        "values": ["default", "physical", "echo"],
        "notes": (
            "Maps to RequestedBuildTarget.{DEFAULT_TARGET,"
            "PHYSICAL_CONTROLLER,ECHO_CONTROLLER}."
        ),
    },
    "controller_mode": {
        "used_by": ["change_controller_mode"],
        "values": ["program", "run", "test"],
        "notes": (
            "Maps to RequestedControllerMode.{PROGRAM,RUN,TEST}. download "
            "and SD card operations require PROGRAM mode."
        ),
    },
    "mode": {
        "used_by": ["get_tag", "set_tag", "update_tag"],
        "values": ["offline", "online"],
        "notes": (
            "Maps to OperationMode.{OFFLINE,ONLINE}. online requires a comm "
            "path and go_online() first."
        ),
    },
    "data_type": {
        "used_by": ["get_tag", "set_tag", "update_tag"],
        "values": [
            "BOOL", "SINT", "INT", "DINT", "LINT",
            "USINT", "UINT", "UDINT", "ULINT",
            "REAL", "LREAL", "STRING",
        ],
        "notes": (
            "Required for get_tag (typed dispatch). Case insensitive but "
            "echoed in uppercase."
        ),
    },
    "collision": {
        "used_by": ["import_partial_l5x"],
        "values": ["overwrite", "discard", "cancel"],
        "notes": (
            "Maps to ImportCollisionOptions.{OVERWRITE_ON_COLL,"
            "DISCARD_ON_COLL,CANCEL_ON_COLL}."
        ),
    },
    "pending_edits": {
        "used_by": ["import_with_target_l5x", "import_rungs_from_l5x"],
        "values": ["leave", "accept", "finalize"],
        "notes": (
            "Maps to PartialImportOption.{LEAVE_EDITS,ACCEPT_EDITS,"
            "FINALIZE_EDITS}. Ignored when offline."
        ),
    },
    "load_event": {
        "used_by": ["store_image_on_sd_card"],
        "values": ["on_demand_only", "on_corrupt_ram", "on_power_up"],
        "notes": (
            "Maps to RequestedLoadEvent.{ON_DEMAND_ONLY,ON_CORRUPT_RAM,"
            "ON_POWER_UP}."
        ),
    },
    "load_mode": {
        "used_by": ["store_image_on_sd_card"],
        "values": ["run", "program"],
        "notes": "Maps to RequestedLoadMode.{RUN,PROGRAM}.",
    },
    "afu": {
        "used_by": ["store_image_on_sd_card"],
        "values": ["enabled", "disabled"],
        "notes": "Maps to AutomaticFirmwareUpdate.{ENABLED,DISABLED}.",
    },
    "processor_type": {
        "used_by": ["create_new_project", "change_controller_type"],
        "values": ["(open set; query at runtime)"],
        "notes": (
            "Call get_processor_types(major_revision=<rev>) to enumerate "
            "every legal value for the installed Logix Designer revision; "
            "pass the Name column verbatim."
        ),
    },
}


def _format_one(name: str, spec: dict[str, object]) -> str:
    used_by = ", ".join(spec.get("used_by", []))  # type: ignore[arg-type]
    values = spec.get("values", [])
    notes = spec.get("notes", "")
    if isinstance(values, list):
        value_str = ", ".join(str(v) for v in values)
    else:
        value_str = str(values)
    return (
        f"{name}:\n"
        f"  used_by: {used_by}\n"
        f"  values:  {value_str}\n"
        f"  notes:   {notes}"
    )


@mcp.tool()
async def list_options(parameter: str = "") -> str:
    """List legal values for every closed-set string parameter the server validates.

    Call with no argument to dump every option group (use this at the start
    of a session). Pass ``parameter="target"`` (or any other parameter name
    from the dump) to get just that entry. Use this instead of guessing the
    enum values that ``build_project``, ``change_controller_mode``, ``get_tag``,
    ``set_tag``, ``import_partial_l5x``, ``import_with_target_l5x``,
    ``import_rungs_from_l5x``, and ``store_image_on_sd_card`` accept.

    For ``processor_type`` (open set, depends on installed Logix Designer
    revisions) this tool returns a pointer to ``get_processor_types``.
    """
    key = parameter.strip()
    if not key:
        blocks = [_format_one(name, spec) for name, spec in _OPTIONS.items()]
        return "[OK] list_options (all):\n\n" + "\n\n".join(blocks)
    if key not in _OPTIONS:
        legal = ", ".join(sorted(_OPTIONS))
        return (
            f"[FAIL] list_options\n"
            f"code:    UNKNOWN_PARAMETER\n"
            f"message: no such parameter {key!r}\n"
            f"hint:    pass one of: {legal}"
        )
    return f"[OK] list_options ({key}):\n\n{_format_one(key, _OPTIONS[key])}"


__all__ = ["projects_list", "sdk_info", "list_options"]
