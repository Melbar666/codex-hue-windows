# Upstream

This repository is derived from `Minetorpia/codex-hue`:

- Repository: https://github.com/Minetorpia/codex-hue
- Upstream version imported: `0.1.0`
- License: MIT

The Windows port preserves the original CLI, Hue state handling, hook merge behavior, certificate pinning, and concurrency-aware event queue.

Windows-specific changes:

1. POSIX `fcntl.flock` is paired with a dependency-free `msvcrt.locking` implementation on Windows.
2. The background queue worker uses Windows process creation flags instead of POSIX `start_new_session`.
3. CI covers Windows, Linux, and macOS.
4. Stable Windows install and uninstall scripts are included.

Keep the `upstream` Git remote configured so later changes can be reviewed and merged deliberately.
