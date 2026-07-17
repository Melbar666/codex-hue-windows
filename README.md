# codex-hue-windows

Use a Philips Hue room or zone as a whole-room status indicator for Codex on Windows, macOS, and Linux.

- **Blue:** at least one Codex turn is active.
- **Green pulse:** a Codex turn returned control.
- **Restore:** after the last active turn, each light returns to its captured state.

> A green pulse means the Codex `Stop` hook fired. It does not prove that the underlying task succeeded.

## Why this repository exists

The upstream project, [`Minetorpia/codex-hue`](https://github.com/Minetorpia/codex-hue), originally used POSIX `fcntl` file locking and a POSIX detached-process option. This port keeps the same Hue behavior and hook format while adding:

- dependency-free Windows file locking through `msvcrt`;
- a detached Windows queue worker;
- Windows, Linux, and macOS CI;
- Windows installation and removal scripts.

The original project is MIT licensed. See `LICENSE` and `UPSTREAM.md`.

## Requirements

- Windows 10 or Windows 11
- Python 3.9 or newer
- Codex with hooks support
- A Philips Hue Bridge on the same local network
- A Hue room or zone containing at least one color-capable light

## Install on Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-CodexHueWindows.ps1
```

The installer creates an isolated environment under `%LOCALAPPDATA%\CodexHueWindows\venv`. It does not pair the Bridge or alter hooks automatically.

## Configure

```powershell
& "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe" setup
& "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe" test
& "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe" install-hooks
```

During `setup`, press the round link button on the Hue Bridge only when the program asks for it. Discovery can be bypassed:

```powershell
& "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe" setup --bridge 192.168.178.20 --room "Office"
```

Restart Codex afterward. Review and trust the new hooks when Codex prompts you.

## Commands

| Command | Purpose |
|---|---|
| `codex-hue discover` | Find Hue Bridges |
| `codex-hue setup` | Pair and select a room or zone |
| `codex-hue rooms` | List rooms and zones |
| `codex-hue set-room NAME` | Change the room or zone |
| `codex-hue test` | Pulse green and restore the previous state |
| `codex-hue status` | Show non-secret status and log path |
| `codex-hue reset` | Clear stale work and restore saved lighting |
| `codex-hue install-hooks` | Merge handlers into Codex hooks |
| `codex-hue uninstall-hooks` | Remove only these handlers |

Runtime data stays under `%USERPROFILE%\.codex\hue-indicator`. `config.json` contains a Hue API credential; do not commit or share it.

## Uninstall

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall-CodexHueWindows.ps1
```

The uninstaller removes the hook handlers and the isolated application environment. It intentionally leaves Hue configuration and logs in place.

## Development

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Hue status changes use the Bridge's local HTTPS API. The Bridge certificate fingerprint is pinned during setup. Pair only on a trusted local network.

This community project is not affiliated with OpenAI, Signify, or Philips Hue.
