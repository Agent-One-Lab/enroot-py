# Utilities

`enroot.utils` contains:

- `run_enroot(...)` / `run_enroot_async(...)`: run `enroot ...` via subprocess (optional host-side `timeout`)
- `list_containers_plain(...)` / `list_containers_fancy(...)`: wrappers around `enroot list`
- helper conversions like `mem_limit_to_bytes(...)`

