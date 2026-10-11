# Utilities

`enroot.utils` contains:

- `run_enroot(...)` / `run_enroot_async(...)`: run `enroot ...` via subprocess (optional host-side `timeout`)
- `list_containers_plain(...)` / `list_containers_fancy(...)`: wrappers around `enroot list`
- `clear_enroot_containers(prefix=None)`: force-remove the local containers whose name starts with
  `prefix` (all of them when `None`). Best effort — one `enroot remove --force` per container,
  survivors are logged — and returns the names that were removed.
- helper conversions like `mem_limit_to_bytes(...)`

