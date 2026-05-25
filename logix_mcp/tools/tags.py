"""Tag tools: ``list_tags`` (L5X parse), ``update_tag`` / ``set_tag`` (typed write), ``get_tag`` (typed read)."""
from __future__ import annotations

from logix_designer_sdk.enums import OperationMode

from logix_mcp._common import (
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_data_type,
    preflight_output_path,
    preflight_project_path,
)
from logix_mcp._xml import _fmt_table, _l5x_tree_for_path, _tag_rows


_PROJECT_EXTS = {".ACD", ".L5X", ".L5K"}
_MODE_MAP = {
    "offline": OperationMode.OFFLINE,
    "online": OperationMode.ONLINE,
}


def _build_tag_xpath(tag_name: str, tag_path: str = "") -> str:
    """Return ``tag_path`` if provided, else ``Controller/Tags/Tag[@Name='<tag_name>']``.

    If ``tag_name`` already looks like a Rockwell XPath (contains ``/`` or
    ``[@``) it is returned as-is so callers can pass scoped tag paths.
    """
    tp = (tag_path or "").strip()
    if tp:
        return tp
    n = (tag_name or "").strip()
    if "/" in n or "[@" in n:
        return n
    return f"Controller/Tags/Tag[@Name='{n}']"


def _coerce_value(raw: str, data_type: str) -> object:
    """Convert a string value to the Python type expected by ``set_tag_value_<dt>``."""
    dt = data_type.upper()
    s = str(raw).strip()
    if dt == "BOOL":
        if s.lower() in ("true", "1", "yes", "on"):
            return True
        if s.lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"BOOL value {raw!r} must be true/false/1/0")
    if dt in ("SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT"):
        return int(s)
    if dt in ("REAL", "LREAL"):
        return float(s)
    if dt == "STRING":
        return s
    raise ValueError(f"unsupported data_type {data_type!r}")


@mcp.tool()
async def list_tags(path: str) -> str:
    """List Controller tags via a temporary detailed L5X export parsed with lxml."""
    pf = preflight_project_path(path)
    if pf:
        return pf

    async def _do() -> str:
        p = _resolve(path)
        tree = await _l5x_tree_for_path(p)
        rows = _tag_rows(tree.getroot())
        table = _fmt_table(rows, ("Name", "DataType", "Scope", "Value"))
        return f"[OK] Tags for {p}:\n{table}"

    return await _run("list_tags", _do, path=path)


async def _update_tag_impl(
    path: str,
    tag_name: str,
    new_value: str,
    output: str = "",
    data_type: str = "",
) -> str:
    """Shared body for ``update_tag`` and its alias ``set_tag``."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf
    if data_type:
        pf = preflight_data_type(data_type)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        x_path = _build_tag_xpath(tag_name)
        async with _opened(p) as proj:
            if data_type:
                dt = data_type.upper()
                value = _coerce_value(new_value, dt)
                setter = getattr(proj, f"set_tag_value_{dt.lower()}", None)
                if setter is None:
                    raise ValueError(
                        f"set_tag_value_{dt.lower()} is not available on the "
                        f"installed Logix Designer SDK"
                    )
                await setter(x_path, value)
            else:
                await proj.set_tag_value(x_path, str(new_value))

            if output:
                out = _resolve(output)
                await proj.save_as(
                    str(out),
                    force=True,
                    detailed_l5x=out.suffix.lower() == ".l5x",
                )
                target = out
            else:
                await proj.save()
                target = p
        suffix = f" ({data_type.upper()})" if data_type else ""
        return f"[OK] Updated {tag_name} = {new_value}{suffix} -> {target}"

    return await _run(
        "update_tag",
        _do,
        path=path,
        tag_name=tag_name,
        output=output,
        data_type=data_type,
    )


@mcp.tool()
async def update_tag(
    path: str,
    tag_name: str,
    new_value: str,
    output: str = "",
    data_type: str = "",
) -> str:
    """Set a Controller tag offline via ``set_tag_value[_<dt>]`` then save (in-place or ``save_as``)."""
    return await _update_tag_impl(path, tag_name, new_value, output, data_type)


@mcp.tool()
async def set_tag(
    path: str,
    tag_name: str,
    new_value: str,
    output: str = "",
    data_type: str = "",
) -> str:
    """Alias for ``update_tag`` — same offline typed-write behavior."""
    return await _update_tag_impl(path, tag_name, new_value, output, data_type)


@mcp.tool()
async def get_tag(
    path: str,
    tag_name: str,
    data_type: str,
    mode: str = "offline",
    tag_path: str = "",
) -> str:
    """Read a typed tag value via ``get_tag_value_<dt>`` in ``offline`` or ``online`` mode."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_data_type(data_type)
    if pf:
        return pf
    m_key = str(mode).strip().lower()
    if m_key not in _MODE_MAP:
        from logix_mcp._common import _fmt_err  # local to avoid widening exports
        return _fmt_err(
            "get_tag",
            ValueError(f"mode {mode!r} not allowed"),
            "INVALID_INPUT",
            "Use mode='offline' or mode='online'.",
            path=path,
            tag_name=tag_name,
            mode=mode,
        )

    async def _do() -> str:
        p = _resolve(path)
        x_path = _build_tag_xpath(tag_name, tag_path)
        op_mode = _MODE_MAP[m_key]
        dt = data_type.upper()
        async with _opened(p) as proj:
            getter = getattr(proj, f"get_tag_value_{dt.lower()}", None)
            if getter is None:
                raise ValueError(
                    f"get_tag_value_{dt.lower()} is not available on the "
                    f"installed Logix Designer SDK"
                )
            value = await getter(x_path, op_mode)
        return f"{tag_name} = {value} ({dt}, {m_key})"

    return await _run(
        "get_tag",
        _do,
        path=path,
        tag_name=tag_name,
        data_type=data_type,
        mode=mode,
    )


__all__ = ["list_tags", "update_tag", "set_tag", "get_tag"]
