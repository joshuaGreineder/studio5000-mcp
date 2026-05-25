# Expected tool output (substrings)

After `install.bat` and with `test_project.ACD` present, manual or scripted checks should include:

| Call | Expect substring in result |
|------|----------------------------|
| `open_project("test_project.ACD")` (full path) | `Opened OK`, `CommunicationsPath`, `ConnectedState` (often `OFFLINE` when not connected) |
| `list_tags("test_project.ACD")` | Markdown-style table with headers `Name`, `Type`, or `(no tags found` if project has no tag XML |
| `update_tag("test_project.ACD", "TestController:MyTag", "42", "test_edited.ACD", "DINT")` (tag path may vary) | `Tag updated`, `Written:`, and path to `test_edited.ACD` |
| `export_l5x("test_project.ACD", "test.L5X")` | `Exported:` and `.L5X` |

**Note:** `TestController:TagName` is illustrative; use a tag path that exists in your project, or add a DINT `MyTag` in Studio, then re-export.

`validate_project` / `build` may fail on empty minimal projects; treat errors as project-specific.
