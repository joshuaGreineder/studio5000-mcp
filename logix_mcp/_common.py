"""Shared infrastructure for the studio5000-mcp FastMCP server.

This module owns the singleton ``mcp = FastMCP("studio5000-mcp")`` instance so
that every per-area module under ``logix_mcp.tools.*`` can do
``from logix_mcp._common import mcp`` and decorate its callables with
``@mcp.tool()`` / ``@mcp.resource()`` against the same registry. Defining the
instance here (rather than in ``server.py``) avoids the circular import that
would otherwise arise when ``server.py`` imports the tool modules.

It also exposes:

* ``_resolve`` / ``_opened``                 — path + LogixProject helpers.
* ``_has_method`` / ``_sdk_version`` /
  ``_gated_tool_response``                   — SDK introspection / gating.
* ``MCPEventLogger``                         — forwards SDK progress to logging
  so long-running build / upload / download / SD-card operations stream
  status to Claude Desktop / Cursor instead of going silent.
* ``_run`` / ``_fmt_err`` / ``_hint_for``    — the layered error handler.
* ``preflight_*``                            — pure validators that return
  ``None`` on success or a ``[FAIL] ...`` string on rejection so tools can
  short-circuit before opening the SDK.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastmcp import FastMCP
from logix_designer_sdk import LogixProject, StdOutEventLogger
from logix_designer_sdk.exceptions import (
    LoggerFailedError,
    LogixSdkError,
    OperationFailedError,
    OperationNotPerformedError,
    ProjectError,
)


# ---------------------------------------------------------------------------
# FastMCP instance — single source of truth for tool / resource registration.
# ---------------------------------------------------------------------------

mcp = FastMCP("studio5000-mcp")


# ---------------------------------------------------------------------------
# Path + LogixProject helpers (kept identical to the legacy single-file
# server so existing behavior is preserved bit-for-bit).
# ---------------------------------------------------------------------------


def _resolve(p: str) -> Path:
    """Expand ``~`` and resolve to an absolute Path."""
    return Path(p).expanduser().resolve()


@asynccontextmanager
async def _opened(path: Path):
    """Open a LogixProject and guarantee ``close()`` runs even on failure."""
    proj = await LogixProject.open_logix_project(str(path))
    try:
        yield proj
    finally:
        proj.close()


# ---------------------------------------------------------------------------
# SDK introspection / version gating.
# ---------------------------------------------------------------------------


def _has_method(name: str) -> bool:
    """True if the installed LogixProject class exposes ``name`` as a callable."""
    return callable(getattr(LogixProject, name, None))


def _sdk_version() -> str:
    """Installed logix_designer_sdk version, or ``'unknown'`` if not resolvable."""
    try:
        return importlib.metadata.version("logix-designer-sdk")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _gated_tool_response(method_name: str) -> str:
    """Friendly message returned by tools whose underlying SDK method is missing."""
    return (
        f"Tool '{method_name}' is not available in the installed "
        f"logix_designer_sdk ({_sdk_version()}). Upgrade Logix Designer SDK "
        f"to use it."
    )


# ---------------------------------------------------------------------------
# MCPEventLogger — forwards SDK progress through Python logging.
#
# We try to subclass StdOutEventLogger so the SDK accepts us anywhere a real
# event logger is expected. The base class is a .NET-backed type, so subclass
# instantiation can fail in odd ways on some installs; if that happens we
# fall back to a duck-typed class that implements the same OperationEvent
# surface (set_progress / log_status_message / log_error_message).
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("logix_mcp")


class _MCPEventLoggerImpl:
    """Shared body for MCPEventLogger — forwards each SDK callback to logging.

    FastMCP's tool context does not expose a synchronous ``mcp.log`` callable
    that's safe to invoke from arbitrary threads, so we route through the
    stdlib ``logging`` module at INFO. The MCP host sees stderr output of
    server processes, so this lets Claude Desktop / Cursor users tail
    progress instead of staring at a silent stdio pipe.
    """

    def set_progress(self, project_file: str, value: int) -> None:  # noqa: D401
        _LOG.info("[PROGRESS %3d%%] %s", int(value), project_file)

    def log_status_message(self, project_file: str, msg: str) -> None:  # noqa: D401
        _LOG.info("[INFO] %s :: %s", project_file, msg)

    def log_error_message(self, project_file: str, msg: str) -> None:  # noqa: D401
        _LOG.error("[ERROR] %s :: %s", project_file, msg)


try:  # Preferred path: subclass the SDK's logger so duck-typing always lines up.
    class MCPEventLogger(StdOutEventLogger):  # type: ignore[misc, valid-type]
        """SDK event logger that forwards progress + status through ``logging``."""

        def set_progress(self, project_file: str, value: int) -> None:
            _MCPEventLoggerImpl.set_progress(self, project_file, value)

        def log_status_message(self, project_file: str, msg: str) -> None:
            _MCPEventLoggerImpl.log_status_message(self, project_file, msg)

        def log_error_message(self, project_file: str, msg: str) -> None:
            _MCPEventLoggerImpl.log_error_message(self, project_file, msg)

    # Sanity-check that we can actually instantiate the subclass. If the .NET
    # bridge rejects subclassing on this install we fall back to the duck-typed
    # implementation below.
    MCPEventLogger()  # noqa: B018 -- side-effect-free smoke test
except Exception:  # noqa: BLE001 -- broad on purpose; SDK uses .NET interop
    class MCPEventLogger(_MCPEventLoggerImpl):  # type: ignore[no-redef]
        """Fallback MCPEventLogger when StdOutEventLogger can't be subclassed."""


# ---------------------------------------------------------------------------
# Error handling: _hint_for, _fmt_err, _run.
# ---------------------------------------------------------------------------

_GENERIC_HINT = (
    "Confirm the file exists, is not locked by Studio 5000, uses a supported "
    "extension (.ACD / .L5X / .L5K), and that Logix Designer / Studio 5000 "
    "is installed. For online actions verify the comm path and controller mode."
)


# Ordered list of (token, hint). First token found in the SDK message wins.
# Tokens are case-sensitive on purpose to match the strings the SDK actually
# emits in OperationFailedError messages.
_HINT_TABLE: list[tuple[str, str]] = [
    (
        "allows only to import RLLContent",
        "partial_import_rungs_from_xml_file requires a fragment whose root "
        "node is RLLContent. Do not wrap the payload in Routine or "
        "RSLogix5000Content when calling the rung-import API.",
    ),
    (
        "XMLSrv_E_IMPORT_ABORTED_NO_CHANGES",
        "Import was aborted and nothing changed. The fragment likely violates "
        "Rockwell L5X schema/target rules or resolves to an identical object. "
        "Export a known-good object from the destination project and diff "
        "Program/Routine/RLLContent structure and attributes first.",
    ),
    (
        "XMLSrv_E_INCOMPATIBLE_IMPORT_TARGET",
        "The fragment target type does not match x_path. For "
        "partial_import_from_xml_file prefer collection targets matching the "
        "fragment root (e.g. DataTypes -> Controller/DataTypes, "
        "Tags -> Controller/Tags, Programs -> Controller/Programs, "
        "Routines -> Controller/Programs/Program[@Name='...']/Routines).",
    ),
    (
        "XMLSrv_E_TARGET_NOT_FOUND",
        "The target object/x_path was not found in the destination project. "
        "Create/import the parent object first or point x_path to an existing "
        "target in this project.",
    ),
    (
        "RxE_DATA_TOO_NEW",
        "Project was created with a newer Logix Designer. Install a newer "
        "version or convert from a machine that has it.",
    ),
    (
        "Required Logix Designer version",
        "Install that exact major revision of Studio 5000 / Logix Designer, "
        "then retry.",
    ),
    (
        "Minimum supported revision is 31",
        "convert_project only supports targets >= 31; pick 31+.",
    ),
    (
        "No Logix Services exist for major revision",
        "That major revision isn't installed; install it or pick one returned "
        "by get_processor_types.",
    ),
    (
        "Not supported processor type",
        "Pass a processor name from get_processor_types(major_revision).",
    ),
    (
        "RxCsE_MORPH_TO_THIS_CONTROLLER_NOT_SUPPORTED",
        "Morph between these controller families isn't allowed (e.g. "
        "ICE2 -> ICE1). Pick a compatible processor type.",
    ),
    (
        "Unable to convert project to type",
        "Target type equals current type; no morph needed.",
    ),
    (
        "See error log",
        "Open Studio 5000 import/export error log details for the precise XML "
        "node/attribute failure. The SDK summary message alone is often too "
        "coarse to identify the bad fragment.",
    ),
]


def _hint_for(message: str) -> str:
    """Map an SDK error message to the most specific actionable hint we have.

    The lookup is intentionally token-based and case-sensitive for the
    documented Rockwell tokens (e.g. ``RxE_DATA_TOO_NEW``) and case-insensitive
    for free-form English phrases. Falls back to ``_GENERIC_HINT``.
    """
    if not message:
        return _GENERIC_HINT
    msg = str(message)
    msg_l = msg.lower()

    for token, hint in _HINT_TABLE:
        if token in msg:
            return hint

    if "controller mode" in msg_l or "program mode" in msg_l:
        return (
            "Run change_controller_mode(mode='program') before download / "
            "destructive ops."
        )
    if "is in use" in msg_l or "locked" in msg_l and "safety" not in msg_l:
        return "Close the file in Studio 5000 and retry."
    if "access is denied" in msg_l:
        return (
            "File is read-only or in a protected directory; pick a writable "
            "output path."
        )
    if "does not exist" in msg_l or "cannot find" in msg_l:
        return "Verify the absolute path."
    if "partial_export" in msg_l and "exists" in msg_l:
        return (
            "The SDK refuses to overwrite; pass force=True or pick a new "
            "output path."
        )
    if "xpath" in msg_l:
        return (
            "Use a Rockwell XPath like "
            "Controller/Programs/Program[@Name='MainProgram']/Routines/"
            "Routine[@Name='MainRoutine']. See PartialImportExport docs."
        )
    if "communication path" in msg_l or "comm path" in msg_l:
        return (
            "Use the RSWho-style path, e.g. AB_ETH-1\\10.0.0.1\\Backplane\\0."
        )
    if "safety" in msg_l and ("locked" in msg_l or "lock" in msg_l):
        return "Call safety_unlock(password) first."
    if "signature" in msg_l:
        return (
            "A safety signature already exists; delete_safety_signature "
            "before regenerating."
        )

    return _GENERIC_HINT


def _fmt_err(
    action: str,
    exc: BaseException,
    code: str,
    hint: str,
    **context: Any,
) -> str:
    """Render the deterministic ``[FAIL] ...`` block tools return on errors."""
    msg = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    cls_name = exc.__class__.__name__
    if context:
        ctx = " ".join(f"{k}={context[k]}" for k in context)
    else:
        ctx = "(none)"
    return (
        f"[FAIL] {action}\n"
        f"code:    {code}\n"
        f"class:   {cls_name}\n"
        f"message: {msg}\n"
        f"hint:    {hint}\n"
        f"context: {ctx}"
    )


async def _run(
    action: str,
    fn: Callable[[], Awaitable[str]],
    **context: Any,
) -> str:
    """Run an awaitable tool body inside the typed exception cascade.

    Re-raises ``asyncio.CancelledError`` so Ctrl+C / cancel scopes still work.
    Every other expected error category is converted to a ``[FAIL] ...``
    block via ``_fmt_err`` + ``_hint_for``.
    """
    try:
        return await fn()
    except asyncio.CancelledError:
        raise
    except OperationFailedError as e:
        return _fmt_err(action, e, "OPERATION_FAILED", _hint_for(getattr(e, "message", str(e))), **context)
    except OperationNotPerformedError as e:
        return _fmt_err(action, e, "NOT_PERFORMED", _hint_for(getattr(e, "message", str(e))), **context)
    except LoggerFailedError as e:
        return _fmt_err(action, e, "LOGGER_FAILED", "Internal SDK logger error; retry once.", **context)
    except ProjectError as e:
        return _fmt_err(action, e, "PROJECT_ERROR", _hint_for(getattr(e, "message", str(e))), **context)
    except LogixSdkError as e:
        return _fmt_err(action, e, "SDK_ERROR", _hint_for(getattr(e, "message", str(e))), **context)
    except FileNotFoundError as e:
        return _fmt_err(action, e, "FILE_NOT_FOUND", "Verify the path; use absolute paths.", **context)
    except PermissionError as e:
        return _fmt_err(action, e, "PERMISSION_DENIED", "File is locked (Studio open?) or read-only.", **context)
    except OSError as e:
        return _fmt_err(action, e, "OS_ERROR", "Check disk space, path length, and file locks.", **context)
    except ValueError as e:
        return _fmt_err(action, e, "INVALID_INPUT", "Fix the argument and retry.", **context)


# ---------------------------------------------------------------------------
# Preflight validators.
#
# Each returns ``None`` on success or a ``[FAIL] ...`` string on rejection,
# so tool bodies do:
#
#     pf = preflight_project_path(path)
#     if pf:
#         return pf
#
# Validators NEVER raise — Phase 2 tools rely on this contract.
# ---------------------------------------------------------------------------

_PROJECT_EXTS = {".acd", ".l5x", ".l5k"}
_BUILD_TARGETS = {"default", "physical", "echo"}
_CONTROLLER_MODES = {"program", "run", "test"}
_TYPED_TAG_DTS = {
    "BOOL", "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "REAL", "LREAL",
    "STRING",
}

_XPATH_EXAMPLES = (
    "Controller/Tags/Tag[@Name='MyTag']",
    "Controller/Programs/Program[@Name='MainProgram']/Routines/"
    "Routine[@Name='MainRoutine']",
    "Controller/Programs/Program[@Name='MainProgram']/Tags/Tag[@Name='Local1']",
    "Controller/AddOnInstructionDefinitions/"
    "AddOnInstructionDefinition[@Name='MyAOI']",
    "Controller/DataTypes/DataType[@Name='MyUDT']",
)

# Loose RSWho fragment: one or more dotted-quad-ish segments separated by
# backslashes. Used as an "ip-like" relaxation alongside the ``Backplane``
# keyword check so we accept either shape.
_COMM_IP_RE = re.compile(r"\\\d{1,3}(?:\.\d{1,3}){3}\\")


def _reject(action: str, code: str, message: str, hint: str, **context: Any) -> str:
    """Build a synthetic [FAIL] block for preflight rejections."""
    return _fmt_err(action, ValueError(message), code, hint, **context)


def preflight_project_path(path: str) -> Optional[str]:
    """Reject if ``path`` doesn't end in a Logix project extension or is missing."""
    if not path or not str(path).strip():
        return _reject(
            "preflight_project_path",
            "INVALID_INPUT",
            "path is empty",
            "Pass an absolute path to a .ACD, .L5X, or .L5K project.",
            path=path,
        )
    p = _resolve(path)
    suff = p.suffix.lower()
    if suff not in _PROJECT_EXTS:
        return _reject(
            "preflight_project_path",
            "INVALID_INPUT",
            f"unsupported extension {suff!r}",
            "Use a .ACD, .L5X, or .L5K file.",
            path=str(p),
        )
    if not p.exists():
        return _reject(
            "preflight_project_path",
            "FILE_NOT_FOUND",
            f"file does not exist: {p}",
            "Verify the absolute path and that the file isn't on a "
            "disconnected drive.",
            path=str(p),
        )
    if not p.is_file():
        return _reject(
            "preflight_project_path",
            "INVALID_INPUT",
            f"path is not a file: {p}",
            "Pass a path to the project file, not a directory.",
            path=str(p),
        )
    return None


def preflight_output_path(path: str, allowed_exts: set[str]) -> Optional[str]:
    """Reject if output extension isn't allowed or parent isn't a writable dir."""
    if not path or not str(path).strip():
        return _reject(
            "preflight_output_path",
            "INVALID_INPUT",
            "output path is empty",
            f"Provide an output path ending in one of "
            f"{sorted(allowed_exts)}.",
            path=path,
        )
    p = _resolve(path)
    suff = p.suffix.lower()
    allowed_norm = {e.lower() for e in allowed_exts}
    if suff not in allowed_norm:
        return _reject(
            "preflight_output_path",
            "INVALID_INPUT",
            f"output extension {suff!r} not in allowed set",
            f"Use one of {sorted(allowed_norm)} for this operation.",
            path=str(p),
        )
    parent = p.parent
    if not parent.exists() or not parent.is_dir():
        return _reject(
            "preflight_output_path",
            "FILE_NOT_FOUND",
            f"parent directory does not exist: {parent}",
            "Create the directory first or pick an existing folder.",
            path=str(p),
        )
    if not os.access(str(parent), os.W_OK):
        return _reject(
            "preflight_output_path",
            "PERMISSION_DENIED",
            f"parent directory is not writable: {parent}",
            "Pick a directory you have write access to.",
            path=str(p),
        )
    return None


def preflight_comm_path(comm_path: str) -> Optional[str]:
    """Reject empty / wrong-shape RSWho comm paths.

    Accepts anything that:
      * is non-empty after strip,
      * contains at least one backslash separator,
      * AND mentions ``Backplane`` OR matches a ``\\<ip>\\`` shape.
    """
    if not comm_path or not str(comm_path).strip():
        return _reject(
            "preflight_comm_path",
            "INVALID_INPUT",
            "comm_path is empty",
            "Use an RSWho-style path, e.g. AB_ETH-1\\10.0.0.1\\Backplane\\0.",
            comm_path=comm_path,
        )
    cp = str(comm_path).strip()
    if "\\" not in cp:
        return _reject(
            "preflight_comm_path",
            "INVALID_INPUT",
            "comm_path missing backslash separators",
            "Use an RSWho-style path, e.g. AB_ETH-1\\10.0.0.1\\Backplane\\0.",
            comm_path=cp,
        )
    has_backplane = "backplane" in cp.lower()
    has_ip = bool(_COMM_IP_RE.search(cp))
    if not (has_backplane or has_ip):
        return _reject(
            "preflight_comm_path",
            "INVALID_INPUT",
            "comm_path doesn't look like RSWho format",
            "Expected something like AB_ETH-1\\10.0.0.1\\Backplane\\0 — "
            "include the IP segment or the literal 'Backplane' keyword.",
            comm_path=cp,
        )
    return None


def preflight_xpath(x_path: str) -> Optional[str]:
    """Reject XPaths that don't start the way Rockwell SDK expects.

    Valid forms:
      * ``Controller``
      * ``Controller/...``
      * ``//Controller/...`` (some callers provide this style)
    """
    if not x_path or not str(x_path).strip():
        return _reject(
            "preflight_xpath",
            "INVALID_INPUT",
            "x_path is empty",
            "Use a Rockwell XPath. Examples:\n  - "
            + "\n  - ".join(_XPATH_EXAMPLES),
            x_path=x_path,
        )
    xp = str(x_path).strip()
    xp_norm = xp.lstrip("/")
    if xp_norm != "Controller" and not xp_norm.startswith("Controller/"):
        return _reject(
            "preflight_xpath",
            "INVALID_INPUT",
            "x_path must start at Controller or Controller/...",
            "Rockwell XPaths begin with Controller (optionally //Controller). "
            "Examples:\n  - "
            + "\n  - ".join(_XPATH_EXAMPLES),
            x_path=xp,
        )
    return None


def preflight_build_target(target: str) -> Optional[str]:
    """Reject build targets outside {default, physical, echo}."""
    if not target:
        return _reject(
            "preflight_build_target",
            "INVALID_INPUT",
            "target is empty",
            "Use one of: default, physical, echo.",
            target=target,
        )
    t = str(target).strip().lower()
    if t not in _BUILD_TARGETS:
        return _reject(
            "preflight_build_target",
            "INVALID_INPUT",
            f"target {target!r} not allowed",
            f"Use one of: {sorted(_BUILD_TARGETS)}.",
            target=target,
        )
    return None


def preflight_controller_mode(mode: str) -> Optional[str]:
    """Reject controller modes outside {program, run, test}."""
    if not mode:
        return _reject(
            "preflight_controller_mode",
            "INVALID_INPUT",
            "mode is empty",
            "Use one of: program, run, test.",
            mode=mode,
        )
    m = str(mode).strip().lower()
    if m not in _CONTROLLER_MODES:
        return _reject(
            "preflight_controller_mode",
            "INVALID_INPUT",
            f"mode {mode!r} not allowed",
            f"Use one of: {sorted(_CONTROLLER_MODES)}.",
            mode=mode,
        )
    return None


def preflight_data_type(dt: str) -> Optional[str]:
    """Reject typed get/set tag data_types outside the supported enum set."""
    if not dt:
        return _reject(
            "preflight_data_type",
            "INVALID_INPUT",
            "data_type is empty",
            f"Use one of: {sorted(_TYPED_TAG_DTS)}.",
            data_type=dt,
        )
    d = str(dt).strip().upper()
    if d not in _TYPED_TAG_DTS:
        return _reject(
            "preflight_data_type",
            "INVALID_INPUT",
            f"data_type {dt!r} not in supported set",
            f"Use one of: {sorted(_TYPED_TAG_DTS)}.",
            data_type=dt,
        )
    return None


def preflight_confirm(confirm: bool, action: str) -> Optional[str]:
    """Refuse mutating online operations unless ``confirm=True`` was passed."""
    if confirm:
        return None
    return _reject(
        action,
        "CONFIRM_REQUIRED",
        "destructive online operation requires explicit opt-in",
        f"Re-run with confirm=true to actually mutate the controller. "
        f"This call will {action}.",
        confirm=False,
    )


__all__ = [
    "mcp",
    "_resolve",
    "_opened",
    "_has_method",
    "_sdk_version",
    "_gated_tool_response",
    "MCPEventLogger",
    "_run",
    "_fmt_err",
    "_hint_for",
    "preflight_project_path",
    "preflight_output_path",
    "preflight_comm_path",
    "preflight_xpath",
    "preflight_build_target",
    "preflight_controller_mode",
    "preflight_data_type",
    "preflight_confirm",
]
