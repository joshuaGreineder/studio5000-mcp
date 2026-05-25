"""Partial import/export tools: slice or merge L5X fragments against an open project."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree
from logix_designer_sdk.enums import ImportCollisionOptions, PartialImportOption

from logix_mcp._common import (
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_output_path,
    preflight_project_path,
    preflight_xpath,
)
from logix_mcp._xml import _resolve_l5x_input


_PROJECT_EXTS = {".ACD", ".L5X", ".L5K"}
_ATOMIC_TAG_TYPES = {
    "BOOL",
    "SINT",
    "INT",
    "DINT",
    "LINT",
    "USINT",
    "UINT",
    "UDINT",
    "ULINT",
    "REAL",
    "LREAL",
    "STRING",
}
_PRIMITIVE_DEFAULTS = {
    "BOOL": ("0", "Decimal"),
    "SINT": ("0", "Decimal"),
    "INT": ("0", "Decimal"),
    "DINT": ("0", "Decimal"),
    "LINT": ("0", "Decimal"),
    "USINT": ("0", "Decimal"),
    "UINT": ("0", "Decimal"),
    "UDINT": ("0", "Decimal"),
    "ULINT": ("0", "Decimal"),
    "REAL": ("0.0", "Float"),
    "LREAL": ("0.0", "Float"),
    "STRING": ("", "ASCII"),
}


def _map_collision(name: str) -> ImportCollisionOptions:
    """Map ``overwrite`` / ``discard`` / ``cancel`` to ``ImportCollisionOptions``."""
    key = (name or "").strip().lower()
    table = {
        "overwrite": ImportCollisionOptions.OVERWRITE_ON_COLL,
        "discard": ImportCollisionOptions.DISCARD_ON_COLL,
        "cancel": ImportCollisionOptions.CANCEL_ON_COLL,
    }
    if key not in table:
        raise ValueError(
            f"collision {name!r} must be one of overwrite / discard / cancel"
        )
    return table[key]


def _map_edits(name: str) -> PartialImportOption:
    """Map ``leave`` / ``accept`` / ``finalize`` to ``PartialImportOption``."""
    key = (name or "").strip().lower()
    table = {
        "leave": PartialImportOption.LEAVE_EDITS,
        "accept": PartialImportOption.ACCEPT_EDITS,
        "finalize": PartialImportOption.FINALIZE_EDITS,
    }
    if key not in table:
        raise ValueError(
            f"pending_edits {name!r} must be one of leave / accept / finalize"
        )
    return table[key]


async def _save_after_import(proj, source: Path, output: str) -> Path:
    """Save the project in-place or to ``output`` (``detailed_l5x`` from extension)."""
    if output:
        out = _resolve(output)
        await proj.save_as(
            str(out),
            force=True,
            detailed_l5x=out.suffix.lower() == ".l5x",
        )
        return out
    await proj.save()
    return source


def _to_bool_text(value: object, default: bool = False) -> str:
    """Return ``true`` / ``false`` from permissive bool-ish input."""
    if value is None:
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return "true" if value else "false"
    s = str(value).strip().lower()
    if s in {"true", "1", "yes", "on"}:
        return "true"
    if s in {"false", "0", "no", "off"}:
        return "false"
    return "true" if default else "false"


def _xml_cdata(text: str) -> str:
    """Wrap ``text`` in CDATA, safely splitting any ``]]>`` tokens."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _normalize_software_revision(text: str) -> str:
    """Normalize software revision to ``NN.00`` shape (best effort)."""
    t = str(text or "").strip()
    if not t:
        return ""
    if "." in t:
        return t
    if t.isdigit():
        return f"{int(t)}.00"
    return t


def _guess_software_revision(path: Path, explicit: str = "") -> str:
    """Pick SoftwareRevision for generated fragments.

    Order:
      1) explicit arg if provided
      2) parse from source .L5X's root ``SoftwareRevision`` attribute
      3) fallback to ``37.00``
    """
    picked = _normalize_software_revision(explicit)
    if picked:
        return picked
    if path.suffix.lower() == ".l5x":
        try:
            root = etree.parse(str(path)).getroot()
            parsed = _normalize_software_revision(root.get("SoftwareRevision", ""))
            if parsed:
                return parsed
        except OSError:
            pass
        except etree.XMLSyntaxError:
            pass
    return "37.00"


def _build_udt_fragment(
    udt_name: str,
    members: list[dict[str, object]],
    family: str,
    class_name: str,
    description: str,
    software_revision: str,
) -> str:
    """Build a minimal L5X fragment that creates one UDT under ``Controller/DataTypes``."""
    if not udt_name or not udt_name.strip():
        raise ValueError("udt_name is empty")
    if not members:
        raise ValueError("members_json must include at least one member")

    member_lines: list[str] = []
    for i, member in enumerate(members, start=1):
        if not isinstance(member, dict):
            raise ValueError(f"member #{i} must be an object")
        name = str(member.get("name", "")).strip()
        data_type = str(member.get("data_type", "")).strip()
        if not name:
            raise ValueError(f"member #{i} is missing required field 'name'")
        if not data_type:
            raise ValueError(f"member #{i} is missing required field 'data_type'")
        dimension = str(member.get("dimension", "0")).strip() or "0"
        radix = str(member.get("radix", "Decimal")).strip() or "Decimal"
        hidden = _to_bool_text(member.get("hidden", False), default=False)
        ext_access = (
            str(member.get("external_access", "Read/Write")).strip() or "Read/Write"
        )
        m_desc = str(member.get("description", "")).strip()
        member_lines.append(
            "      "
            + f'<Member Name="{escape(name)}" DataType="{escape(data_type)}" '
            + f'Dimension="{escape(dimension)}" Radix="{escape(radix)}" '
            + f'Hidden="{hidden}" ExternalAccess="{escape(ext_access)}">'
        )
        if m_desc:
            member_lines.append("        <Description>")
            member_lines.append("          " + _xml_cdata(m_desc))
            member_lines.append("        </Description>")
        member_lines.append("      </Member>")

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{escape(software_revision)}" TargetType="DataTypes" ContainsContext="true">',
        '  <Controller Use="Context" Name="UDTImportFragment">',
        '    <DataTypes Use="Target">',
        f'      <DataType Name="{escape(udt_name.strip())}" '
        + f'Family="{escape((family or "NoFamily").strip())}" '
        + f'Class="{escape((class_name or "User").strip())}">',
    ]
    if description and description.strip():
        lines.extend(
            [
                "        <Description>",
                "          " + _xml_cdata(description.strip()),
                "        </Description>",
            ]
        )
    lines.extend(
        [
            "        <Members>",
            *member_lines,
            "        </Members>",
            "      </DataType>",
            "    </DataTypes>",
            "  </Controller>",
            "</RSLogix5000Content>",
        ]
    )
    return "\n".join(lines)


def _build_tag_fragment(
    tag_name: str,
    data_type: str,
    initial_value: str,
    radix: str,
    external_access: str,
    description: str,
    software_revision: str,
    decorated_member_lines: list[str] | None = None,
    structured_l5k_value: str = "",
) -> str:
    """Build a minimal L5X fragment that creates one controller-scope Tag."""
    tn = str(tag_name or "").strip()
    dt = str(data_type or "").strip()
    if not tn:
        raise ValueError("tag_name is empty")
    if not dt:
        raise ValueError("data_type is empty")
    rv = str(radix or "Decimal").strip() or "Decimal"
    ea = str(external_access or "Read/Write").strip() or "Read/Write"
    init = initial_value if initial_value is not None else ""

    scalar = dt.upper() in _ATOMIC_TAG_TYPES
    radix_attr = f' Radix="{escape(rv)}"' if scalar else ""
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{escape(software_revision)}" TargetType="Tags" ContainsContext="true">',
        '  <Controller Use="Context" Name="TagImportFragment">',
        '    <Tags Use="Target">',
        f'      <Tag Use="Target" Name="{escape(tn)}" Class="Standard" TagType="Base" '
        + f'DataType="{escape(dt)}"{radix_attr} '
        + f'Constant="false" ExternalAccess="{escape(ea)}" OpcUaAccess="None">',
    ]
    if description and description.strip():
        lines.extend(
            [
                "        <Description>",
                "          " + _xml_cdata(description.strip()),
                "        </Description>",
            ]
        )
    # For atomic data types, include an L5K initializer. For UDTs/AOIs/custom
    # types, provide a minimal Decorated structure marker. Providing scalar L5K
    # for a struct tag triggers XMLSrv_E_IMPORT_ABORTED_NO_CHANGES.
    if scalar:
        lines.extend(
            [
                '        <Data Format="L5K">',
                "          " + _xml_cdata(str(init)),
                "        </Data>",
            ]
        )
    else:
        l5k_struct = str(structured_l5k_value or "").strip()
        members = decorated_member_lines or []
        lines.extend(
            [
                '        <Data Format="L5K">',
                "          " + _xml_cdata(l5k_struct),
                "        </Data>",
                '        <Data Format="Decorated">',
                f'          <Structure DataType="{escape(dt)}">',
                *members,
                "          </Structure>",
                "        </Data>",
            ]
        )
    lines.extend(
        [
            "      </Tag>",
            "    </Tags>",
            "  </Controller>",
            "</RSLogix5000Content>",
        ]
    )
    return "\n".join(lines)


def _build_program_fragment(
    program_name: str,
    main_routine_name: str,
    class_name: str,
    description: str,
    software_revision: str,
) -> str:
    """Build a minimal L5X fragment that creates one Program with one RLL routine."""
    pn = str(program_name or "").strip()
    rn = str(main_routine_name or "").strip() or "MainRoutine"
    cn = str(class_name or "Standard").strip() or "Standard"
    if not pn:
        raise ValueError("program_name is empty")

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{escape(software_revision)}" TargetType="Programs" ContainsContext="true">',
        '  <Controller Use="Context" Name="ProgramImportFragment">',
        '    <Programs Use="Target">',
        f'      <Program Name="{escape(pn)}" '
        + 'TestEdits="false" '
        + f'MainRoutineName="{escape(rn)}" '
        + 'Disabled="false" '
        + f'Class="{escape(cn)}" '
        + 'UseAsFolder="false">',
    ]
    if description and description.strip():
        lines.extend(
            [
                "        <Description>",
                "          " + _xml_cdata(description.strip()),
                "        </Description>",
            ]
        )
    lines.extend(
        [
            "        <Tags/>",
            "        <Routines>",
            f'          <Routine Name="{escape(rn)}" Type="RLL">',
            "            <RLLContent>",
            '              <Rung Number="0" Type="N">',
            "                <Text>" + _xml_cdata("NOP();") + "</Text>",
            "              </Rung>",
            "            </RLLContent>",
            "          </Routine>",
            "        </Routines>",
            "      </Program>",
            "    </Programs>",
            "  </Controller>",
            "</RSLogix5000Content>",
        ]
    )
    return "\n".join(lines)


async def _infer_struct_member_lines(proj, data_type: str) -> tuple[list[str], str]:
    """Infer default decorated members by exporting DataType definition.

    This currently supports scalar primitive members only. Unsupported member
    shapes are skipped; if all are skipped caller can fall back to minimal
    ``<Structure DataType='...'>`` marker.
    """
    fd, name = tempfile.mkstemp(prefix="logix_mcp_udt_", suffix=".L5X")
    os.close(fd)
    Path(name).unlink(missing_ok=True)
    out = Path(name)
    try:
        await proj.partial_export_to_xml_file(
            f"Controller/DataTypes/DataType[@Name='{data_type}']", str(out)
        )
        tree = etree.parse(str(out))
        root = tree.getroot()
        dtype_el = None
        for el in root.iter():
            if _local(el.tag) == "DataType" and el.get("Name") == data_type:
                dtype_el = el
                break
        if dtype_el is None:
            raise ValueError(
                f"data_type {data_type!r} was not found under Controller/DataTypes."
            )
        lines: list[str] = []
        l5k_values: list[str] = []
        unsupported: list[str] = []
        members_el = None
        for ch in dtype_el:
            if _local(ch.tag) == "Members":
                members_el = ch
                break
        if members_el is None:
            raise ValueError(
                f"data_type {data_type!r} has no <Members>; cannot infer defaults "
                "for generated UDT tag creation."
            )
        for m in members_el:
            if _local(m.tag) != "Member":
                continue
            m_name = (m.get("Name") or "").strip()
            m_dt = (m.get("DataType") or "").strip().upper()
            dim = (m.get("Dimension") or "0").strip()
            if not m_name or not m_dt:
                continue
            # Only scalar primitive members for now.
            if dim not in ("0", ""):
                unsupported.append(f"{m_name}({m_dt}[{dim}])")
                continue
            if m_dt not in _PRIMITIVE_DEFAULTS:
                unsupported.append(f"{m_name}({m_dt})")
                continue
            val, radix = _PRIMITIVE_DEFAULTS[m_dt]
            lines.append(
                "            "
                + f'<DataValueMember Name="{escape(m_name)}" '
                + f'DataType="{escape(m_dt)}" '
                + f'Radix="{escape(radix)}" Value="{escape(val)}"/>'
            )
            l5k_values.append(val)
        if unsupported:
            raise ValueError(
                "create_tag currently auto-initializes only scalar primitive UDT "
                "members. Unsupported members in "
                f"{data_type!r}: {', '.join(unsupported)}. Use import_partial_l5x "
                "with an exported tag fragment for this UDT shape."
            )
        if not l5k_values:
            raise ValueError(
                f"data_type {data_type!r} has no supported scalar primitive members; "
                "cannot synthesize a valid structured L5K initializer."
            )
        return lines, "[" + ",".join(l5k_values) + "]"
    except OSError as e:
        raise ValueError(
            f"could not inspect data_type {data_type!r} to build tag defaults: {e}"
        ) from e
    except etree.XMLSyntaxError as e:
        raise ValueError(
            f"invalid exported XML while inspecting data_type {data_type!r}: {e}"
        ) from e
    finally:
        try:
            out.unlink(missing_ok=True)
        except OSError:
            pass


def _local(tag: str) -> str:
    """Return local XML tag name (strip namespace prefix)."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _extract_rllcontent_for_import(xml_text: str) -> etree._Element:
    """Extract / normalize an ``RLLContent`` element from several input shapes.

    Supported roots:
      - ``RLLContent``
      - ``Rung`` (wrapped into RLLContent)
      - ``Routine`` (first nested RLLContent)
      - ``RSLogix5000Content`` (first nested RLLContent)
    """
    raw = (xml_text or "").strip()
    if not raw:
        raise ValueError("rung import XML is empty")
    try:
        root = etree.fromstring(raw.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        raise ValueError(f"invalid rung import XML: {e}") from e

    rt = _local(root.tag)
    if rt == "RLLContent":
        rll = root
    elif rt == "Rung":
        rll = etree.Element("RLLContent")
        rll.append(root)
    elif rt in ("Routine", "RSLogix5000Content"):
        found = None
        for el in root.iter():
            if _local(el.tag) == "RLLContent":
                found = el
                break
        if found is None:
            raise ValueError(
                "XML does not contain RLLContent. Supported roots: "
                "RLLContent, Rung, Routine, RSLogix5000Content with RLLContent."
            )
        rll = found
    else:
        raise ValueError(
            "Unsupported rung XML root. Use RLLContent, Rung, Routine, or "
            "RSLogix5000Content containing RLLContent."
        )

    # Ensure target marker for the dedicated rung-import API.
    if not rll.get("Use"):
        rll.set("Use", "Target")
    return rll


def _wrap_rllcontent_fragment(rll: etree._Element, software_revision: str) -> str:
    """Wrap RLLContent in minimal RSLogix5000Content context for SDK import."""
    root = etree.Element(
        "RSLogix5000Content",
        SchemaRevision="1.0",
        SoftwareRevision=software_revision,
    )
    ctrl = etree.SubElement(root, "Controller", Use="Context", Name="RungImportFragment")
    progs = etree.SubElement(ctrl, "Programs", Use="Context")
    prog = etree.SubElement(progs, "Program", Use="Context", Name="MCP_Program")
    rts = etree.SubElement(prog, "Routines", Use="Context")
    rt = etree.SubElement(rts, "Routine", Use="Context", Name="MCP_Routine", Type="RLL")
    rt.append(rll)
    return etree.tostring(root, encoding="unicode")


def _extract_program_routine_names(x_path: str) -> tuple[str, str]:
    """Best-effort parse Program/Routine names from Rockwell XPath."""
    xp = (x_path or "").strip()
    pm = re.search(r"Program\[@Name=['\"]([^'\"]+)['\"]\]", xp)
    rm = re.search(r"Routine\[@Name=['\"]([^'\"]+)['\"]\]", xp)
    return (
        pm.group(1) if pm else "MCP_Program",
        rm.group(1) if rm else "MCP_Routine",
    )


def _normalize_rll_target_x_path(routine_x_path: str) -> str:
    """Normalize target to the routine RLLContent node expected by SDK API."""
    xp = (routine_x_path or "").strip()
    if not xp:
        return xp
    if xp.endswith("/RLLContent"):
        return xp
    return xp + "/RLLContent"


def _wrap_rllcontent_for_target(
    rll: etree._Element, software_revision: str, routine_x_path: str
) -> str:
    """Wrap RLLContent with context names aligned to target routine XPath."""
    program_name, routine_name = _extract_program_routine_names(routine_x_path)
    root = etree.Element(
        "RSLogix5000Content",
        SchemaRevision="1.0",
        SoftwareRevision=software_revision,
    )
    ctrl = etree.SubElement(root, "Controller", Use="Context", Name="RungImportFragment")
    progs = etree.SubElement(ctrl, "Programs", Use="Context")
    prog = etree.SubElement(progs, "Program", Use="Context", Name=program_name)
    rts = etree.SubElement(prog, "Routines", Use="Context")
    rt = etree.SubElement(rts, "Routine", Use="Context", Name=routine_name, Type="RLL")
    rt.append(rll)
    return etree.tostring(root, encoding="unicode")


def _build_program_routine_import_fragment(
    program_name: str,
    routine_name: str,
    rll: etree._Element,
    software_revision: str,
) -> str:
    """Build a Program-root fragment that upserts one routine with RLLContent."""
    rll_copy = etree.fromstring(etree.tostring(rll, encoding="utf-8"))
    if not rll_copy.get("Use"):
        rll_copy.set("Use", "Target")
    root = etree.Element(
        "RSLogix5000Content",
        SchemaRevision="1.0",
        SoftwareRevision=software_revision,
        TargetType="Programs",
        ContainsContext="true",
    )
    ctrl = etree.SubElement(root, "Controller", Use="Context", Name="RoutineImportFragment")
    progs = etree.SubElement(ctrl, "Programs", Use="Target")
    prog = etree.SubElement(progs, "Program", Name=program_name)
    routines = etree.SubElement(prog, "Routines", Use="Target")
    routine = etree.SubElement(routines, "Routine", Name=routine_name, Type="RLL")
    routine.append(rll_copy)
    return etree.tostring(root, encoding="unicode")


def _clone_xml_element(el: etree._Element) -> etree._Element:
    """Deep-copy an lxml element while preserving attributes/children."""
    return etree.fromstring(etree.tostring(el, encoding="utf-8"))


def _find_first_child(parent: etree._Element, name: str) -> etree._Element | None:
    """Return first direct child whose local tag name matches ``name``."""
    for child in parent:
        if _local(child.tag) == name:
            return child
    return None


def _build_merged_rllcontent(
    existing_rll: etree._Element, incoming_rll: etree._Element, ip: int, rc: int
) -> etree._Element:
    """Return merged RLLContent after applying insert/replace splice semantics."""
    existing_rungs = [c for c in list(existing_rll) if _local(c.tag) == "Rung"]
    incoming_rungs = [c for c in list(incoming_rll) if _local(c.tag) == "Rung"]
    if ip > len(existing_rungs):
        raise ValueError(
            f"insert_position {ip} is out of range for target routine "
            f"(rung_count={len(existing_rungs)})."
        )
    if ip + rc > len(existing_rungs):
        raise ValueError(
            f"replace_count {rc} at insert_position {ip} exceeds target routine "
            f"rung_count={len(existing_rungs)}."
        )

    merged_rungs = (
        [_clone_xml_element(r) for r in existing_rungs[:ip]]
        + [_clone_xml_element(r) for r in incoming_rungs]
        + [_clone_xml_element(r) for r in existing_rungs[ip + rc :]]
    )

    merged = etree.Element("RLLContent", Use="Target")
    for idx, rung in enumerate(merged_rungs):
        rung.set("Number", str(idx))
        merged.append(rung)
    return merged


def _build_program_fallback_fragment_from_export(
    exported_program_xml: str,
    program_name: str,
    routine_name: str,
    incoming_rll: etree._Element,
    ip: int,
    rc: int,
) -> str:
    """Patch exported Program XML with merged rung content for fallback import."""
    root = etree.fromstring(exported_program_xml.encode("utf-8"))
    program = None
    for el in root.iter():
        if _local(el.tag) == "Program" and (el.get("Name") or "").strip() == program_name:
            program = el
            break
    if program is None:
        raise ValueError(
            f"fallback could not locate Program[{program_name!r}] in exported XML."
        )

    routines_el = _find_first_child(program, "Routines")
    if routines_el is None:
        raise ValueError(
            f"fallback could not locate <Routines> under Program[{program_name!r}]."
        )
    routine = None
    for el in routines_el:
        if _local(el.tag) == "Routine" and (el.get("Name") or "").strip() == routine_name:
            routine = el
            break
    if routine is None:
        raise ValueError(
            f"fallback could not locate Routine[{routine_name!r}] in Program[{program_name!r}]."
        )
    if (routine.get("Type") or "").strip().upper() != "RLL":
        raise ValueError(
            f"fallback only supports RLL routines; target routine type is "
            f"{(routine.get('Type') or '(empty)')!r}."
        )

    existing_rll = _find_first_child(routine, "RLLContent")
    if existing_rll is None:
        raise ValueError(
            f"fallback could not locate <RLLContent> in Routine[{routine_name!r}]."
        )
    merged_rll = _build_merged_rllcontent(existing_rll, incoming_rll, ip, rc)
    routine.replace(existing_rll, merged_rll)
    return etree.tostring(root, encoding="unicode")


async def _fallback_import_rungs_by_program_patch(
    proj,
    routine_x_path: str,
    incoming_rll: etree._Element,
    ip: int,
    rc: int,
) -> None:
    """Fallback rung import by patching exported Program XML then re-importing."""
    program_name, routine_name = _extract_program_routine_names(routine_x_path)
    escaped_program = program_name.replace("'", "&apos;")
    program_x_path = (
        "Controller/Programs/"
        + f"Program[@Name='{escaped_program}']"
    )
    with tempfile.NamedTemporaryFile(suffix=".L5X", delete=False) as fh:
        export_path = Path(fh.name)
    try:
        exported_xml = ""
        export_err: Exception | None = None
        for export_target in (program_x_path, "Controller/Programs"):
            try:
                await proj.partial_export_to_xml_file(export_target, str(export_path))
                exported_xml = export_path.read_text(encoding="utf-8", errors="replace")
                # Validate that this export actually contains the requested routine.
                _build_program_fallback_fragment_from_export(
                    exported_xml, program_name, routine_name, incoming_rll, ip, rc
                )
                export_err = None
                break
            except Exception as e:
                export_err = e
                if _is_retryable_import_target_error(e):
                    continue
                if "could not locate Routine" in str(e) or "could not locate Program" in str(e):
                    continue
                raise
        if export_err is not None:
            raise export_err
        fb_xml = _build_program_fallback_fragment_from_export(
            exported_xml, program_name, routine_name, incoming_rll, ip, rc
        )
        fb_file, fb_tmp = _resolve_l5x_input("", fb_xml)
        try:
            program_target = "Controller/Programs/" + f"Program[@Name='{escaped_program}']"
            last_err: Exception | None = None
            for target_x_path in (program_target, "Controller/Programs"):
                try:
                    await proj.partial_import_from_xml_file(
                        target_x_path,
                        fb_file,
                        ImportCollisionOptions.OVERWRITE_ON_COLL,
                        False,
                    )
                    last_err = None
                    break
                except Exception as import_err:
                    last_err = import_err
                    if "XMLSrv_E_INCOMPATIBLE_IMPORT_TARGET" in str(import_err):
                        continue
                    raise
            if last_err is not None:
                raise last_err
        finally:
            if fb_tmp is not None:
                try:
                    fb_tmp.unlink()
                except OSError:
                    pass
    finally:
        try:
            export_path.unlink(missing_ok=True)
        except OSError:
            pass


def _should_use_rung_fallback(exc: Exception) -> bool:
    """Return True when SDK requires program-level fallback import path."""
    msg = str(exc or "")
    return (
        "RxE_NOT_SUPPORTED" in msg
        or "allows only to import RLLContent" in msg
        or "only to import RLLContent" in msg
        or "XMLSrv_E_INCOMPATIBLE_IMPORT_TARGET" in msg
    )


def _is_retryable_import_target_error(exc: Exception) -> bool:
    """Return True when SDK error suggests trying a different target xpath."""
    msg = str(exc or "")
    lower = msg.lower()
    return (
        "xmlsrv_e_incompatible_import_target" in lower
        or ("xpath" in lower and "not valid" in lower)
        or ("x path" in lower and "not valid" in lower)
    )


def _infer_fragment_collection_target(l5x_file: str) -> str:
    """Infer collection-level target from fragment content.

    Returns one of:
      - Controller/Programs
      - Controller/Tags
      - Controller/DataTypes
      - Controller/Modules
      - "" (unknown)
    """
    try:
        tree = etree.parse(l5x_file)
        root = tree.getroot()
    except (OSError, etree.XMLSyntaxError):
        return ""
    collection_tags = {"Programs", "Tags", "DataTypes", "Modules"}
    for el in root.iter():
        if _local(el.tag) in collection_tags:
            return f"Controller/{_local(el.tag)}"
    return ""


def _infer_fragment_import_targets(l5x_file: str, requested_x_path: str) -> list[str]:
    """Infer ordered import target candidates from fragment content.

    This extends collection-only inference to better handle routine fragments
    nested under Programs for valid Program/Routine import payloads.
    """
    requested = (requested_x_path or "").strip()
    targets: list[str] = []
    if requested:
        targets.append(requested)

    try:
        root = etree.parse(l5x_file).getroot()
    except (OSError, etree.XMLSyntaxError):
        inferred = _infer_fragment_collection_target(l5x_file)
        if inferred and inferred not in targets:
            targets.append(inferred)
        return targets

    program_name = ""
    routines_targeted = False
    has_programs = False
    has_routines = False
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "Programs":
            has_programs = True
        elif tag == "Routines":
            has_routines = True
            if (el.get("Use") or "").strip().lower() == "target":
                parent = el.getparent()
                if parent is not None and _local(parent.tag) == "Program":
                    routines_targeted = True
                    program_name = (parent.get("Name") or "").strip()

    if routines_targeted and program_name:
        esc_name = program_name.replace("'", "&apos;")
        program_path = "Controller/Programs/" + f"Program[@Name='{esc_name}']"
        routines_path = program_path + "/Routines"
        for candidate in (routines_path, program_path):
            if candidate not in targets:
                targets.append(candidate)

    if has_programs and "Controller/Programs" not in targets:
        targets.append("Controller/Programs")
    if has_routines and "Controller/Programs" not in targets:
        targets.append("Controller/Programs")

    inferred = _infer_fragment_collection_target(l5x_file)
    if inferred and inferred not in targets:
        targets.append(inferred)
    return targets


@mcp.tool()
async def export_component_l5x(
    path: str, x_path: str, output: str, force: bool = False
) -> str:
    """Export a single component identified by ``x_path`` to an ``.L5X`` via ``partial_export_to_xml_file``."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    pf = preflight_output_path(output, {".L5X"})
    if pf:
        return pf

    async def _do() -> str:
        p = _resolve(path)
        out = _resolve(output)
        if out.exists():
            if not force:
                raise ValueError(
                    f"output already exists: {out} (pass force=true to overwrite)"
                )
            try:
                out.unlink()
            except OSError as e:
                raise ValueError(f"could not remove existing {out}: {e}") from e
        async with _opened(p) as proj:
            await proj.partial_export_to_xml_file(x_path, str(out))
        return f"[OK] Exported component {x_path} from {p} -> {out}"

    return await _run(
        "export_component_l5x",
        _do,
        path=path,
        x_path=x_path,
        output=output,
        force=force,
    )


@mcp.tool()
async def import_partial_l5x(
    path: str,
    x_path: str,
    l5x_path: str = "",
    l5x_text: str = "",
    collision: str = "overwrite",
    continue_on_errors: bool = False,
    output: str = "",
) -> str:
    """Merge an L5X fragment at ``x_path`` via ``partial_import_from_xml_file``; ``collision`` ∈ {overwrite, discard, cancel}."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        l5x_file, tmp = _resolve_l5x_input(l5x_path, l5x_text)
        coll = _map_collision(collision)
        try:
            async with _opened(p) as proj:
                try:
                    await proj.partial_import_from_xml_file(
                        x_path, l5x_file, coll, bool(continue_on_errors)
                    )
                    used_x_path = x_path
                except Exception as e:
                    if not _is_retryable_import_target_error(e):
                        raise
                    retry_err: Exception = e
                    used_x_path = x_path
                    for candidate in _infer_fragment_import_targets(l5x_file, x_path):
                        if candidate == x_path:
                            continue
                        try:
                            await proj.partial_import_from_xml_file(
                                candidate, l5x_file, coll, bool(continue_on_errors)
                            )
                            used_x_path = candidate
                            break
                        except Exception as retry_exc:
                            retry_err = retry_exc
                            if _is_retryable_import_target_error(retry_exc):
                                continue
                            raise
                    else:
                        raise retry_err
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Partial import at {used_x_path} (collision={collision}, "
            f"continue_on_errors={bool(continue_on_errors)}) -> {target}"
        )

    return await _run(
        "import_partial_l5x",
        _do,
        path=path,
        x_path=x_path,
        collision=collision,
        output=output,
    )


@mcp.tool()
async def import_with_target_l5x(
    path: str,
    x_path: str,
    target_name: str,
    l5x_path: str = "",
    l5x_text: str = "",
    pending_edits: str = "leave",
    output: str = "",
) -> str:
    """Single-target partial import / rename via ``partial_import_with_target_from_xml_file``; ``pending_edits`` ∈ {leave, accept, finalize}."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        if not target_name or not target_name.strip():
            raise ValueError("target_name is empty")
        p = _resolve(path)
        l5x_file, tmp = _resolve_l5x_input(l5x_path, l5x_text)
        edits = _map_edits(pending_edits)
        try:
            async with _opened(p) as proj:
                await proj.partial_import_with_target_from_xml_file(
                    x_path, target_name, l5x_file, edits
                )
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Partial import-with-target at {x_path} "
            f"(target_name={target_name}, pending_edits={pending_edits}) -> {target}"
        )

    return await _run(
        "import_with_target_l5x",
        _do,
        path=path,
        x_path=x_path,
        target_name=target_name,
        pending_edits=pending_edits,
        output=output,
    )


@mcp.tool()
async def import_rungs_from_l5x(
    path: str,
    routine_x_path: str,
    insert_position: int,
    replace_count: int,
    l5x_path: str = "",
    l5x_text: str = "",
    pending_edits: str = "leave",
    output: str = "",
) -> str:
    """Insert / replace rungs in a routine via ``partial_import_rungs_from_xml_file``.

    Accepted source shapes for ``l5x_text`` / ``l5x_path``:
      - ``<RLLContent>...``
      - ``<Rung ...>...``
      - ``<Routine>...<RLLContent>...``
      - full ``<RSLogix5000Content>...<RLLContent>...``
    The tool normalizes these to the SDK-required wrapper automatically.
    """
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(routine_x_path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        ip = int(insert_position)
        rc = int(replace_count)
        if ip < 0:
            raise ValueError("insert_position must be >= 0")
        if rc < 0:
            raise ValueError("replace_count must be >= 0")
        # Normalize contradictory user inputs to the exact shape expected by
        # PartialImportRungsFromXmlFileAsync (RLLContent target inside a
        # minimal RSLogix5000Content context).
        src_text = ""
        if (l5x_text or "").strip():
            src_text = l5x_text
        elif (l5x_path or "").strip():
            src_text = _resolve(l5x_path).read_text(encoding="utf-8", errors="replace")
        else:
            raise ValueError("Provide l5x_text or l5x_path")
        target_x_path = _normalize_rll_target_x_path(routine_x_path)
        rll = _extract_rllcontent_for_import(src_text)
        l5x_file, tmp = _resolve_l5x_input(
            "",
            etree.tostring(rll, encoding="unicode"),
        )
        edits = _map_edits(pending_edits)
        try:
            async with _opened(p) as proj:
                try:
                    await proj.partial_import_rungs_from_xml_file(
                        target_x_path, ip, rc, l5x_file, edits
                    )
                except Exception as e:
                    if not _should_use_rung_fallback(e):
                        raise
                    try:
                        await _fallback_import_rungs_by_program_patch(
                            proj, routine_x_path, rll, ip, rc
                        )
                    except ValueError:
                        raise
                    except Exception as fb_err:
                        fb_msg = str(fb_err or "")
                        if "XMLSrv_E_IMPORT_ABORTED_NO_CHANGES" in fb_msg:
                            raise ValueError(
                                "SDK fallback import aborted with "
                                "XMLSrv_E_IMPORT_ABORTED_NO_CHANGES. The patched "
                                "Program fragment was accepted syntactically but "
                                "produced no change according to Logix XML "
                                "services. This usually means the effective rung "
                                "splice is identical to current routine content, "
                                "or this controller revision rejects the specific "
                                "rung/text shape for fallback program-level "
                                "imports. Export the destination Program and diff "
                                "Program/Routines/Routine[@Name]/RLLContent plus "
                                "insert_position/replace_count semantics."
                            ) from fb_err
                        raise
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Rung import into {target_x_path} "
            f"(insert_position={ip}, replace_count={rc}, "
            f"pending_edits={pending_edits}) -> {target}"
        )

    return await _run(
        "import_rungs_from_l5x",
        _do,
        path=path,
        routine_x_path=routine_x_path,
        insert_position=insert_position,
        replace_count=replace_count,
        pending_edits=pending_edits,
        output=output,
    )


@mcp.tool()
async def create_udt(
    path: str,
    udt_name: str,
    members_json: str,
    family: str = "NoFamily",
    class_name: str = "User",
    description: str = "",
    software_revision: str = "",
    overwrite: bool = False,
    output: str = "",
) -> str:
    """Create one UDT by generating an L5X fragment and importing it under ``Controller/DataTypes``.

    ``members_json`` must be a JSON array of objects. Required keys per member:
    ``name`` and ``data_type``. Optional keys:
    ``dimension``, ``radix``, ``hidden``, ``external_access``, ``description``.
    """
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        raw = json.loads(members_json)
        if isinstance(raw, dict) and "members" in raw:
            raw = raw.get("members")
        if not isinstance(raw, list):
            raise ValueError("members_json must decode to a list (or {\"members\": [...]})")
        members = list(raw)
        l5x_text = _build_udt_fragment(
            udt_name=udt_name,
            members=members,  # type: ignore[arg-type]
            family=family,
            class_name=class_name,
            description=description,
            software_revision=_guess_software_revision(p, software_revision),
        )
        l5x_file, tmp = _resolve_l5x_input("", l5x_text)
        collision = _map_collision("overwrite" if overwrite else "cancel")
        try:
            async with _opened(p) as proj:
                await proj.partial_import_from_xml_file(
                    "Controller/DataTypes",
                    l5x_file,
                    collision,
                    False,
                )
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] UDT {udt_name!r} created "
            f"(members={len(members)}, overwrite={overwrite}) -> {target}"
        )

    return await _run(
        "create_udt",
        _do,
        path=path,
        udt_name=udt_name,
        overwrite=overwrite,
        output=output,
    )


@mcp.tool()
async def create_tag(
    path: str,
    tag_name: str,
    data_type: str = "DINT",
    initial_value: str = "0",
    radix: str = "Decimal",
    external_access: str = "Read/Write",
    description: str = "",
    software_revision: str = "",
    overwrite: bool = False,
    output: str = "",
) -> str:
    """Create one controller-scope tag using generated L5X and partial import."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        dt_up = str(data_type or "").strip().upper()
        decorated_lines: list[str] | None = None
        structured_l5k_value = ""
        if dt_up and dt_up not in _ATOMIC_TAG_TYPES:
            # For custom UDT tags, attempt to infer member list so Decorated
            # payload is concrete and accepted by XML import.
            async with _opened(p) as proj:
                decorated_lines, inferred_l5k = await _infer_struct_member_lines(
                    proj, data_type
                )
            user_struct_init = str(initial_value if initial_value is not None else "").strip()
            structured_l5k_value = (
                user_struct_init if user_struct_init and user_struct_init != "0" else inferred_l5k
            )
        l5x_text = _build_tag_fragment(
            tag_name=tag_name,
            data_type=data_type,
            initial_value=initial_value,
            radix=radix,
            external_access=external_access,
            description=description,
            software_revision=_guess_software_revision(p, software_revision),
            decorated_member_lines=decorated_lines,
            structured_l5k_value=structured_l5k_value,
        )
        l5x_file, tmp = _resolve_l5x_input("", l5x_text)
        collision = _map_collision("overwrite" if overwrite else "cancel")
        try:
            async with _opened(p) as proj:
                await proj.partial_import_from_xml_file(
                    "Controller/Tags",
                    l5x_file,
                    collision,
                    False,
                )
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Tag {tag_name!r} created (data_type={data_type}, "
            f"overwrite={overwrite}) -> {target}"
        )

    return await _run(
        "create_tag",
        _do,
        path=path,
        tag_name=tag_name,
        data_type=data_type,
        overwrite=overwrite,
        output=output,
    )


@mcp.tool()
async def create_program(
    path: str,
    program_name: str,
    main_routine_name: str = "MainRoutine",
    class_name: str = "Standard",
    description: str = "",
    software_revision: str = "",
    overwrite: bool = False,
    output: str = "",
) -> str:
    """Create one Program (with a starter RLL main routine) via partial import."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        l5x_text = _build_program_fragment(
            program_name=program_name,
            main_routine_name=main_routine_name,
            class_name=class_name,
            description=description,
            software_revision=_guess_software_revision(p, software_revision),
        )
        l5x_file, tmp = _resolve_l5x_input("", l5x_text)
        collision = _map_collision("overwrite" if overwrite else "cancel")
        try:
            async with _opened(p) as proj:
                await proj.partial_import_from_xml_file(
                    "Controller/Programs",
                    l5x_file,
                    collision,
                    False,
                )
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Program {program_name!r} created "
            f"(main_routine={main_routine_name!r}, overwrite={overwrite}) -> {target}"
        )

    return await _run(
        "create_program",
        _do,
        path=path,
        program_name=program_name,
        main_routine_name=main_routine_name,
        class_name=class_name,
        overwrite=overwrite,
        output=output,
    )


def _build_routine_fragment(
    program_name: str,
    routine_name: str,
    routine_type: str,
    initial_rll_text: str,
    software_revision: str,
) -> str:
    """Build a minimal L5X fragment that creates one routine in a Program."""
    pn = str(program_name or "").strip()
    rn = str(routine_name or "").strip()
    rt = str(routine_type or "RLL").strip().upper() or "RLL"
    if not pn:
        raise ValueError("program_name is empty")
    if not rn:
        raise ValueError("routine_name is empty")
    if rt != "RLL":
        raise ValueError(
            f"routine_type {routine_type!r} is not supported yet; use 'RLL'."
        )
    rung_text = str(initial_rll_text if initial_rll_text is not None else "").strip()
    if not rung_text:
        rung_text = "NOP();"
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            f'<RSLogix5000Content SchemaRevision="1.0" SoftwareRevision="{escape(software_revision)}" TargetType="Routines" ContainsContext="true">',
            '  <Controller Use="Context" Name="RoutineCreateFragment">',
            '    <Programs Use="Context">',
            f'      <Program Name="{escape(pn)}" Use="Context">',
            '        <Routines Use="Target">',
            f'          <Routine Name="{escape(rn)}" Type="RLL">',
            "            <RLLContent>",
            '              <Rung Number="0" Type="N">',
            f"                <Text>{_xml_cdata(rung_text)}</Text>",
            "              </Rung>",
            "            </RLLContent>",
            "          </Routine>",
            "        </Routines>",
            "      </Program>",
            "    </Programs>",
            "  </Controller>",
            "</RSLogix5000Content>",
        ]
    )


@mcp.tool()
async def create_routine(
    path: str,
    program_name: str,
    routine_name: str,
    routine_type: str = "RLL",
    initial_rll_text: str = "",
    overwrite: bool = False,
    output: str = "",
) -> str:
    """Create one routine under an existing Program via generated L5X import.

    ``routine_type`` currently supports ``RLL`` only. ``initial_rll_text``
    seeds rung 0 text for RLL routines (defaults to ``NOP();``).
    """
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        pn = str(program_name or "").strip()
        rn = str(routine_name or "").strip()
        if not pn:
            raise ValueError("program_name is empty")
        if not rn:
            raise ValueError("routine_name is empty")
        esc_name = pn.replace("'", "&apos;")
        program_x_path = "Controller/Programs/" + f"Program[@Name='{esc_name}']"
        l5x_text = _build_routine_fragment(
            program_name=pn,
            routine_name=rn,
            routine_type=routine_type,
            initial_rll_text=initial_rll_text,
            software_revision=_guess_software_revision(p, ""),
        )
        l5x_file, tmp = _resolve_l5x_input("", l5x_text)
        collision = _map_collision("overwrite" if overwrite else "cancel")
        with tempfile.NamedTemporaryFile(suffix=".L5X", delete=False) as probe_fh:
            probe_path = Path(probe_fh.name)
        try:
            async with _opened(p) as proj:
                # Preflight: fail fast with a clear message if Program is missing.
                await proj.partial_export_to_xml_file(program_x_path, str(probe_path))
                await proj.partial_import_from_xml_file(
                    program_x_path + "/Routines",
                    l5x_file,
                    collision,
                    False,
                )
                target = await _save_after_import(proj, p, output)
        finally:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] Routine {rn!r} created under Program {pn!r} "
            f"(routine_type={str(routine_type or 'RLL').upper()}, "
            f"overwrite={overwrite}) -> {target}"
        )

    return await _run(
        "create_routine",
        _do,
        path=path,
        program_name=program_name,
        routine_name=routine_name,
        routine_type=routine_type,
        overwrite=overwrite,
        output=output,
    )


@mcp.tool()
async def add_io_module(
    path: str,
    module_l5x_path: str = "",
    module_l5x_text: str = "",
    collision: str = "cancel",
    continue_on_errors: bool = False,
    output: str = "",
) -> str:
    """Add/configure I/O module definitions by importing module L5X under ``Controller/Modules``.

    This is a dedicated convenience wrapper over partial import for module
    fragments. Provide either ``module_l5x_path`` (file) or
    ``module_l5x_text`` (inline XML) whose target is one or more
    ``/RSLogix5000Content/Controller/Modules/Module`` elements.
    """
    pf = preflight_project_path(path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, _PROJECT_EXTS)
        if pf:
            return pf

    async def _do() -> str:
        p = _resolve(path)
        l5x_file, tmp = _resolve_l5x_input(module_l5x_path, module_l5x_text)
        coll = _map_collision(collision)
        try:
            async with _opened(p) as proj:
                await proj.partial_import_from_xml_file(
                    "Controller/Modules",
                    l5x_file,
                    coll,
                    bool(continue_on_errors),
                )
                target = await _save_after_import(proj, p, output)
        finally:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return (
            f"[OK] I/O module import into Controller/Modules "
            f"(collision={collision}, continue_on_errors={bool(continue_on_errors)}) "
            f"-> {target}"
        )

    return await _run(
        "add_io_module",
        _do,
        path=path,
        collision=collision,
        output=output,
    )


__all__ = [
    "export_component_l5x",
    "import_partial_l5x",
    "import_with_target_l5x",
    "import_rungs_from_l5x",
    "create_udt",
    "create_tag",
    "create_program",
    "create_routine",
    "add_io_module",
]
