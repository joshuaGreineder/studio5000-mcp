# Example Workflows

## 1) Enumerate processors then create project

1. `get_processor_types(major_revision=37)`
2. Pick a `Name` value, then:
3. `create_new_project(output=..., major_revision=37, processor_type=..., controller_name=...)`

## 2) Create UDT + tag + program

1. `create_udt(...)`
2. `create_tag(...)`
3. `create_program(...)`
4. `build_project(path=..., target="default")`

## 3) Patch logic and validate

1. `import_rungs_from_l5x(...)`
2. `build_project(...)`
3. `search_rungs(...)`

## 4) Add module definitions

1. Prepare module L5X fragment (or export from known-good project).
2. `add_io_module(path=..., module_l5x_path=..., collision="overwrite")`
3. `build_project(...)`
