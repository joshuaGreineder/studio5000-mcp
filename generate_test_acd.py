"""Create a minimal test_project.ACD via Logix Designer SDK (requires Studio 5000 / LD)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from logix_designer_sdk import LogixProject


async def main() -> None:
    root = Path(__file__).resolve().parent
    out = root / "test_project.ACD"
    if out.exists():
        out.unlink()
    last_err: Exception | None = None
    for major in range(40, 27, -1):
        try:
            procs = await LogixProject.get_processor_types(major)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        if not procs:
            continue
        cpu_name = sorted(procs.keys())[0]
        try:
            await LogixProject.create_new_project(
                str(out),
                major,
                cpu_name,
                "TestController",
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        print(f"Wrote {out} (Logix v{major}, {cpu_name})")
        return
    print("Could not create test ACD. Try a Studio revision supported on this machine.", file=sys.stderr)
    if last_err:
        print(last_err, file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
