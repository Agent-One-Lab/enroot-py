# Errors

All client errors come from `enroot.errors`.

- `errors.APIError`: backend command failed or API-level precondition failed
- `errors.NotFound`: missing container/exec id
- `errors.ImageNotFound`: missing image
- `errors.TimeoutError`: an operation exceeded its configured timeout

