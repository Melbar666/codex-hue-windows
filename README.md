# codex-hue-windows

Use a Philips Hue room or zone as a whole-room status indicator for local Codex work on Windows, macOS, and Linux.

- **Blue:** at least one Codex turn is active.
- **Green pulse:** a Codex turn returned control.
- **Restore:** after the final active turn ends, every light returns to the state captured before Codex started.

> A green pulse means that the Codex `Stop` hook fired. It does **not** prove that the underlying task succeeded.

## Verified compatibility

| Codex workflow | Status | Notes |
|---|---:|---|
| Codex CLI on Windows | Verified | Uses `%USERPROFILE%\.codex\hooks.json`. |
| Codex desktop app on Windows, local workflow | Verified | The desktop UI launches a local Codex backend process, which uses the same hooks file. No separate interactive CLI window is required. |
| Unified ChatGPT desktop app in Codex mode, local workflow | Expected | OpenAI is moving existing Codex desktop users to the unified desktop app; local Codex workflows remain local. |
| Pure cloud-delegated task | Not supported | A task that never runs through this PC's local Codex runtime cannot execute local hooks or reach the local Hue Bridge. |
| macOS and Linux | Upstream-compatible | Covered by automated tests; the PowerShell installer is Windows-specific. |

Manual Windows acceptance completed on July 17, 2026:

- package installation;
- Hue Bridge discovery and pairing;
- room selection;
- green pulse and exact light-state restoration;
- Codex hook installation;
- real Codex CLI hook run;
- real Codex desktop-app local hook run.

## Why this repository exists

The upstream project, [`Minetorpia/codex-hue`](https://github.com/Minetorpia/codex-hue), originally used POSIX `fcntl` file locking and a POSIX detached-process option. This port preserves its Hue behavior, hook format, certificate pinning, event ordering, and concurrency handling while adding:

- dependency-free Windows file locking through `msvcrt`;
- a detached Windows queue worker;
- Windows, Linux, and macOS CI;
- Windows installation and removal scripts;
- a tested Windows desktop-app and CLI workflow.

The original project is MIT licensed. See [`LICENSE`](LICENSE) and [`UPSTREAM.md`](UPSTREAM.md).

## Requirements

- Windows 10 or Windows 11
- Python 3.9 or newer, including the `py` launcher
- Git
- Codex with hooks support
- A Philips Hue Bridge on the same local network
- A Hue room or zone containing at least one color-capable light

## Quick start on Windows

Open **PowerShell**, then clone and enter the repository:

```powershell
Set-Location C:\Dev
git clone https://github.com/Melbar666/codex-hue-windows.git
Set-Location .\codex-hue-windows
```

Install the package:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-CodexHueWindows.ps1
```

The installer creates an isolated environment here:

```text
%LOCALAPPDATA%\CodexHueWindows\venv
```

It does not pair the Bridge and does not change Codex hooks automatically.

### Already cloned?

```powershell
Set-Location C:\Dev\codex-hue-windows
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-CodexHueWindows.ps1
```

Rerun the installer after pulling repository updates so the isolated installation receives the new package version.

## Pair the Bridge and select a room

Define the installed command once for the current PowerShell session:

```powershell
$CodexHue = "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe"
```

Start setup:

```powershell
& $CodexHue setup
```

The command discovers a Bridge and asks you to press its round link button. Press the button only when prompted, then select a room or zone by number or name.

Discovery can be bypassed when the Bridge address and room are already known:

```powershell
& $CodexHue setup --bridge 192.168.178.20 --room "Office"
```

Bridge credentials and the pinned certificate fingerprint are stored locally under:

```text
%USERPROFILE%\.codex\hue-indicator
```

## Test Hue before installing hooks

```powershell
& $CodexHue test
```

Expected result:

1. The selected room pulses green.
2. Each light returns to its exact previous on/off, brightness, and color state.
3. The command reports that the room was restored.

Do not continue to hook installation until this test succeeds.

## Install Codex hooks

```powershell
& $CodexHue install-hooks
```

This merges the Hue handlers into:

```text
%USERPROFILE%\.codex\hooks.json
```

Existing unrelated hooks are preserved. A timestamped backup is created before the file is changed.

After installation:

1. Fully exit every running Codex CLI and desktop-app process.
2. Restart the Codex client you want to test.
3. Review and trust the hooks if Codex asks for approval.

The hooks are installed once per Windows user. The CLI and local desktop-app workflows share the same Codex home and therefore use the same hook configuration.

## Real acceptance test

### Codex CLI

Start Codex from any local project:

```powershell
Set-Location C:\Dev\codex-hue-windows
codex
```

Submit this harmless test prompt:

```text
Reply only with: Hue test completed.
```

Expected sequence:

1. The selected room turns blue when the prompt is submitted.
2. It pulses green when Codex returns control.
3. It restores the lighting state that existed before the turn.

### Codex desktop app

1. Fully close and restart the Codex desktop app.
2. Open a local folder or project.
3. Start a local thread.
4. Submit the same harmless test prompt.

The same blue → green → restore sequence should occur.

Seeing a `codex.exe` process in Task Manager while using the desktop app is normal for a local Codex workflow. The desktop interface uses a local Codex backend; this does not mean that you accidentally opened a second interactive CLI session.

### Local versus cloud execution

This project reacts to hooks executed on the Windows PC.

It works when the task runs through the local Codex runtime, including verified CLI and local desktop-app workflows. A purely cloud-delegated task cannot trigger the local hooks because it does not execute `%USERPROFILE%\.codex\hooks.json` on this machine and cannot directly contact the local Hue Bridge.

## Concurrent Codex turns

The indicator is concurrency-aware:

- the first active turn captures the room state and turns the room blue;
- completion of each turn produces a green pulse;
- the room returns to blue while any other turn remains active;
- the original room state is restored only after the final active turn ends.

This allows CLI and desktop-app turns to overlap without restoring the lights too early.

## Commands

| Command | Purpose |
|---|---|
| `codex-hue discover` | Find Hue Bridges on the local network |
| `codex-hue setup` | Pair with a Bridge and select a room or zone |
| `codex-hue rooms` | List available rooms and zones |
| `codex-hue set-room NAME` | Change the selected room or zone |
| `codex-hue test` | Pulse green and restore the previous state |
| `codex-hue status` | Show non-secret status, selected room, and log path |
| `codex-hue reset` | Clear stale active turns and restore saved lighting |
| `codex-hue install-hooks` | Merge Hue handlers into the Codex hooks file |
| `codex-hue uninstall-hooks` | Remove only the Hue handlers |

The installed executable is:

```text
%LOCALAPPDATA%\CodexHueWindows\venv\Scripts\codex-hue.exe
```

## Troubleshooting

First define the executable if this PowerShell session does not already have `$CodexHue`:

```powershell
$CodexHue = "$env:LOCALAPPDATA\CodexHueWindows\venv\Scripts\codex-hue.exe"
```

### Show current status

```powershell
& $CodexHue status
```

### Read the indicator log

```powershell
Get-Content "$env:USERPROFILE\.codex\hue-indicator\indicator.log" -Tail 100
```

### Inspect the installed hooks

```powershell
Get-Content "$env:USERPROFILE\.codex\hooks.json"
```

### The direct Hue test works, but Codex does nothing

Check these points in order:

1. `install-hooks` completed successfully.
2. Codex was fully exited and restarted after hook installation.
3. Any hook trust prompt was accepted.
4. The task is a local Codex workflow, not a pure cloud task.
5. The log contains a new event after submitting the prompt.
6. The hooks file still contains the `codex-hue` handlers.

### The room remains blue

A Codex process may still have an active turn, or an earlier client may have ended without delivering its final hook. After confirming that no Codex task is still running, reset the indicator:

```powershell
& $CodexHue reset
```

The command clears stale active-turn state and restores the previously saved lighting state.

### Setup selects the wrong Bridge

Run setup with an explicit Bridge address:

```powershell
& $CodexHue setup --bridge 192.168.178.20
```

### Change the selected room

List all available targets:

```powershell
& $CodexHue rooms
```

Then select one:

```powershell
& $CodexHue set-room "Office"
```

### Reinstall after an update

```powershell
Set-Location C:\Dev\codex-hue-windows
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-CodexHueWindows.ps1
```

## Runtime files

Runtime data remains outside the repository:

```text
%USERPROFILE%\.codex\hue-indicator\config.json
%USERPROFILE%\.codex\hue-indicator\state.json
%USERPROFILE%\.codex\hue-indicator\indicator.log
```

`config.json` contains a Hue API credential. Do not commit, publish, or share it.

The Codex hooks file is:

```text
%USERPROFILE%\.codex\hooks.json
```

## Uninstall

Run from the cloned repository:

```powershell
Set-Location C:\Dev\codex-hue-windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall-CodexHueWindows.ps1
```

The uninstaller:

- removes only the `codex-hue` handlers from the shared Codex hooks file;
- removes the isolated application environment;
- intentionally leaves the Hue configuration, state, and log directory in place.

To remove the retained runtime data as well, inspect it first and then delete it manually:

```powershell
Remove-Item "$env:USERPROFILE\.codex\hue-indicator" -Recurse
```

## Development

Create an isolated development environment:

```powershell
Set-Location C:\Dev\codex-hue-windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The automated test suite covers hook merging, event ordering, duplicate completion handling, concurrent turn behavior, Windows file locking, and detached worker configuration.

A real Hue Bridge is not contacted by the automated test suite. Run `codex-hue test` and the real acceptance test after changes that affect Hue communication, hooks, or process handling.

## Security and privacy

Hue status changes use the Bridge's local HTTPS API. The Bridge certificate fingerprint is pinned during setup. Pair only on a trusted local network.

The project does not need Hue cloud access. Its local credential grants control of the paired Bridge and must be protected.

## OpenAI references

- [Codex runs locally through the CLI, IDE extension, or desktop app](https://openai.com/index/building-codex-windows-sandbox/)
- [Using Codex with a ChatGPT plan: Codex Local versus Codex Cloud](https://help.openai.com/en/articles/11369540)
- [Moving from the Codex app to the unified ChatGPT desktop app](https://help.openai.com/en/articles/20001276-moving-to-the-new-chatgpt-desktop-app)

This community project is not affiliated with OpenAI, Signify, or Philips Hue.
