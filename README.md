# codex-hue

Turn a Philips Hue room into a whole-room status indicator for Codex. The room
turns blue while Codex is working, pulses green whenever a turn finishes, and
then either returns to blue (if other turns are still active) or restores every
light to its previous state.

The integration uses Codex hooks and the Hue Bridge's local HTTPS API. After
discovery and pairing, status changes stay on your local network.

| Codex state | Hue behavior |
| --- | --- |
| A turn starts | Save the room's state and set the room to blue |
| One of several turns finishes | Pulse green, then return to blue |
| The last active turn finishes | Pulse green, then restore each light |

## Requirements

- Python 3.9 or newer on macOS or Linux
- Codex with hooks support
- A Philips Hue Bridge on the same local network
- A Hue room or zone containing color-capable lights

Windows is not currently supported because the concurrency locks use POSIX
`fcntl` file locking.

## Install

Clone or download this repository, enter its directory, create an isolated
Python environment, and install it:

```shell
cd codex-hue
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Pair with your Bridge and select a room:

```shell
codex-hue setup
```

The command discovers the Bridge, then explicitly tells you when to press its
round link button. It waits up to 60 seconds for the press and then asks which
room or zone to use. Discovery can be bypassed when necessary:

```shell
codex-hue setup --bridge 192.168.1.20 --room "Living Room"
```

Test the selected room, then install the Codex hooks:

```shell
codex-hue test
codex-hue install-hooks
```

Restart Codex. Review and trust the new hooks when Codex prompts you; hooks do
not run until they are trusted. Start a new Codex turn to try it.

The hook configuration invokes the exact Python environment used to run
`install-hooks`. Keep that environment installed. Re-run `install-hooks` after
moving to a different environment.

## Commands

| Command | Purpose |
| --- | --- |
| `codex-hue discover` | Find Hue Bridges on the network |
| `codex-hue setup` | Discover, pair, and select a room or zone |
| `codex-hue rooms` | List rooms and zones after pairing |
| `codex-hue set-room NAME` | Change the selected room or zone |
| `codex-hue test` | Pulse green and restore the room |
| `codex-hue status` | Show non-secret status and the log path |
| `codex-hue reset` | Clear stale work and restore the saved state |
| `codex-hue install-hooks` | Merge the handlers into Codex's global hooks |
| `codex-hue uninstall-hooks` | Remove only this project's handlers |

`install-hooks` preserves unrelated handlers in `~/.codex/hooks.json`, makes a
timestamped backup when that file exists, and is safe to run more than once.

## How multiple tasks work

Each `UserPromptSubmit` hook adds a session-and-turn pair to a shared active set.
Every `Stop` hook removes that pair and triggers a green completion pulse. A
file-locked event queue serializes simultaneous hooks, so one completion is not
lost merely because another Codex task is running.

In Codex hook terms, `Stop` means the agent finished that turn and returned
control. It is not a guarantee that the underlying work succeeded. The first
active turn's room snapshot is restored after the last active turn stops.

## Configuration and privacy

Runtime data is stored outside the repository:

```text
~/.codex/hue-indicator/config.json
~/.codex/hue-indicator/state.json
~/.codex/hue-indicator/indicator.log
```

`config.json` contains a Hue API username that can control your Bridge. Treat it
as a credential and never publish it. The directory and files are created with
owner-only permissions. You can relocate runtime data with
`CODEX_HUE_DATA_DIR`; `CODEX_HOME` changes where `hooks.json` is read and
written.

The Bridge certificate's SHA-256 fingerprint is captured during setup and
pinned for later requests. A changed certificate is rejected, although—as with
other trust-on-first-use systems—initial setup should be performed on a trusted
local network.

The defaults in `config.json` use Hue API v1 `hue`, `sat`, and `bri` values. You
may edit `busy`, `complete`, and the timing fields after setup.

## Troubleshooting

- **No Bridge is discovered:** pass its LAN address with `--bridge`. Check your
  router or the Hue app for the address.
- **Pairing times out:** run `setup` again and press the physical Bridge button
  only after the command asks.
- **Hooks do not run:** restart Codex, inspect its hooks settings, and approve
  the handlers. Run `codex-hue status` and inspect the reported log.
- **Room remains blue:** run `codex-hue reset`. Very old active turns are also
  expired automatically after 24 hours.
- **Certificate fingerprint changed:** verify that the Bridge was replaced or
  reset before pairing again. Do not blindly modify the fingerprint.
- **Some lights do not show color:** non-color lights can still change brightness
  but cannot display the blue/green status colors.

## Uninstall

```shell
codex-hue uninstall-hooks
```

Restart Codex afterward. You can then remove the Python environment and, if you
no longer need it, the `~/.codex/hue-indicator` runtime directory.

## Development

```shell
python -m pip install -e .
python -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) before
opening a change or reporting a security issue.

Useful upstream references:

- [Codex hooks documentation](https://learn.chatgpt.com/docs/hooks)
- [Philips Hue local API getting started guide](https://developers.meethue.com/develop/get-started-2/)

This community project is not affiliated with, endorsed by, or sponsored by
OpenAI, Signify, or Philips Hue. Codex and Philips Hue are trademarks of their
respective owners.
