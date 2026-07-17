#!/usr/bin/env python3
"""Use a Philips Hue room as a concurrency-safe Codex work indicator."""

import argparse
import fcntl
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request


DEFAULT_BUSY = {
    "on": True,
    "bri": 110,
    "hue": 46920,
    "sat": 230,
    "transitiontime": 3,
}
DEFAULT_COMPLETE = {
    "on": True,
    "bri": 254,
    "hue": 25500,
    "sat": 254,
    "transitiontime": 1,
}
SUPPORTED_GROUP_TYPES = {"Room", "Zone", "LightGroup"}
PROJECT_NAME = "codex-hue"


class HueError(RuntimeError):
    pass


def data_dir():
    override = os.environ.get("CODEX_HUE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex" / "hue-indicator"


def config_path():
    return data_dir() / "config.json"


def state_path():
    return data_dir() / "state.json"


def lock_path():
    return data_dir() / "state.lock"


def queue_path():
    return data_dir() / "events.json"


def queue_lock_path():
    return data_dir() / "events.lock"


def worker_lock_path():
    return data_dir() / "worker.lock"


def log_path():
    return data_dir() / "indicator.log"


def codex_home():
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codex"


def hooks_path():
    return codex_home() / "hooks.json"


def ensure_data_dir():
    data_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(data_dir(), 0o700)
    except OSError:
        pass


def log(message):
    try:
        ensure_data_dir()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write("{} {}\n".format(timestamp, message))
    except OSError:
        pass


def read_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path, value):
    ensure_data_dir()
    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix="." + path.name + ".", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


class FileLock:
    def __init__(self, path, nonblocking=False):
        self.path = path
        self.nonblocking = nonblocking

    def __enter__(self):
        ensure_data_dir()
        self.descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        flags = fcntl.LOCK_EX
        if self.nonblocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(self.descriptor, flags)
        except BlockingIOError:
            os.close(self.descriptor)
            self.descriptor = None
            return None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.descriptor is None:
            return
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)


def StateLock():
    return FileLock(lock_path())


def QueueLock():
    return FileLock(queue_lock_path())


class HueClient:
    def __init__(self, host, username=None, fingerprint=None, port=443, timeout=3.0):
        self.host = host
        self.port = int(port)
        self.username = username
        self.fingerprint = normalize_fingerprint(fingerprint) if fingerprint else None
        self.timeout = float(timeout)

    def request(self, method, path, payload=None):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(
            self.host, self.port, timeout=self.timeout, context=context
        )
        try:
            connection.connect()
            certificate = connection.sock.getpeercert(binary_form=True)
            actual_fingerprint = hashlib.sha256(certificate).hexdigest()
            if self.fingerprint and not hmac.compare_digest(
                actual_fingerprint, self.fingerprint
            ):
                raise HueError("Hue Bridge certificate fingerprint changed")

            body = None
            headers = {"Accept": "application/json"}
            if payload is not None:
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            if response.status < 200 or response.status >= 300:
                raise HueError("Hue Bridge returned HTTP {}".format(response.status))
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HueError("Hue Bridge returned invalid JSON") from error
            check_hue_errors(decoded)
            return decoded
        finally:
            connection.close()

    def api_path(self, suffix=""):
        if not self.username:
            raise HueError("Hue Bridge username is not configured")
        return "/api/{}{}".format(self.username, suffix)

    def groups(self):
        return self.request("GET", self.api_path("/groups"))

    def group(self, group_id):
        return self.request("GET", self.api_path("/groups/{}".format(group_id)))

    def light(self, light_id):
        return self.request("GET", self.api_path("/lights/{}".format(light_id)))

    def lights(self):
        return self.request("GET", self.api_path("/lights"))

    def group_action(self, group_id, action):
        return self.request(
            "PUT", self.api_path("/groups/{}/action".format(group_id)), action
        )

    def light_state(self, light_id, action):
        return self.request(
            "PUT", self.api_path("/lights/{}/state".format(light_id)), action
        )


def normalize_fingerprint(value):
    return str(value).replace(":", "").strip().lower()


def check_hue_errors(value):
    errors = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and "error" in item:
                error = item["error"]
                errors.append(error.get("description", str(error)))
    elif isinstance(value, dict) and "error" in value:
        error = value["error"]
        errors.append(error.get("description", str(error)))
    if errors:
        raise HueError("; ".join(errors))


def bridge_fingerprint(host, port=443, timeout=3.0):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(
        host, int(port), timeout=float(timeout), context=context
    )
    try:
        connection.connect()
        certificate = connection.sock.getpeercert(binary_form=True)
        return hashlib.sha256(certificate).hexdigest()
    finally:
        connection.close()


def discover_bridges():
    bridges = []
    seen = set()

    try:
        local_host = socket.gethostbyname("philips-hue.local")
        bridges.append({"id": None, "internalipaddress": local_host, "source": "mDNS"})
        seen.add(local_host)
    except OSError:
        pass

    request = urllib.request.Request(
        "https://discovery.meethue.com/", headers={"User-Agent": "codex-hue-indicator/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            discovered = json.load(response)
        for bridge in discovered:
            host = bridge.get("internalipaddress")
            if host and host not in seen:
                item = dict(bridge)
                item["source"] = "Hue discovery service"
                bridges.append(item)
                seen.add(host)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return bridges


def load_config():
    config = read_json(config_path(), None)
    if not isinstance(config, dict):
        raise HueError("Hue indicator is not configured; run setup first")
    required = ("bridge_host", "certificate_sha256", "username", "group_id")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise HueError("Hue configuration is incomplete: {}".format(", ".join(missing)))
    return config


def client_from_config(config):
    return HueClient(
        config["bridge_host"],
        username=config["username"],
        fingerprint=config["certificate_sha256"],
        port=config.get("bridge_port", 443),
        timeout=config.get("request_timeout_seconds", 3.0),
    )


def default_state():
    return {"active": {}, "completed": {}, "snapshot": None}


def load_state():
    state = read_json(state_path(), default_state())
    if not isinstance(state, dict):
        return default_state()
    state.setdefault("active", {})
    state.setdefault("completed", {})
    state.setdefault("snapshot", None)
    return state


def save_state(state):
    write_json_atomic(state_path(), state)


def snapshot_room(client, group_id):
    group = client.group(group_id)
    all_lights = client.lights()
    snapshot = {"lights": {}, "captured_at": time.time()}
    for light_id in group.get("lights", []):
        try:
            light = all_lights[str(light_id)]
            snapshot["lights"][str(light_id)] = dict(light.get("state", {}))
        except (HueError, KeyError) as error:
            log("Could not snapshot light {}: {}".format(light_id, error))
    return snapshot


def restorable_state(original, transitiontime=2):
    if not isinstance(original, dict) or "on" not in original:
        return None
    result = {"on": bool(original["on"]), "transitiontime": int(transitiontime)}
    if not original["on"]:
        return result

    if "bri" in original:
        result["bri"] = original["bri"]
    color_mode = original.get("colormode")
    if color_mode == "hs":
        if "hue" in original:
            result["hue"] = original["hue"]
        if "sat" in original:
            result["sat"] = original["sat"]
    elif color_mode == "xy" and "xy" in original:
        result["xy"] = original["xy"]
    elif color_mode == "ct" and "ct" in original:
        result["ct"] = original["ct"]
    if "effect" in original and original["effect"] in ("none", "colorloop"):
        result["effect"] = original["effect"]
    return result


def restore_room(client, snapshot, transitiontime=2, request_gap_seconds=0.12):
    if not snapshot:
        return
    for light_id, original in snapshot.get("lights", {}).items():
        action = restorable_state(original, transitiontime=transitiontime)
        if not action:
            continue
        try:
            client.light_state(light_id, action)
        except HueError as error:
            log("Could not restore light {}: {}".format(light_id, error))
        if request_gap_seconds:
            time.sleep(float(request_gap_seconds))


def trim_state(state, stale_after_seconds):
    now = time.time()
    stale = []
    for key, details in state["active"].items():
        if now - float(details.get("started_at", now)) > stale_after_seconds:
            stale.append(key)
    for key in stale:
        del state["active"][key]

    state["completed"] = {
        key: timestamp
        for key, timestamp in state["completed"].items()
        if now - float(timestamp) < stale_after_seconds
    }
    return stale


def event_key(session_id, turn_id):
    return "{}:{}".format(session_id or "unknown-session", turn_id or "unknown-turn")


def process_event(event_name, session_id, turn_id, client=None):
    config = load_config()
    if client is None:
        client = client_from_config(config)
    group_id = str(config["group_id"])
    key = event_key(session_id, turn_id)
    stale_after = float(config.get("stale_after_seconds", 86400))

    with StateLock():
        state = load_state()
        stale = trim_state(state, stale_after)
        if stale:
            log("Expired {} stale active turn(s)".format(len(stale)))

        if not state["active"] and state.get("snapshot") and event_name == "UserPromptSubmit":
            restore_room(
                client,
                state["snapshot"],
                transitiontime=config.get("restore_transitiontime", 2),
                request_gap_seconds=config.get("restore_request_gap_seconds", 0.12),
            )
            state["snapshot"] = None

        if event_name == "UserPromptSubmit":
            if key not in state["active"]:
                if not state["active"]:
                    state["snapshot"] = snapshot_room(client, group_id)
                state["active"][key] = {"started_at": time.time()}
            save_state(state)
            client.group_action(group_id, config.get("busy", DEFAULT_BUSY))
            log("Turn started; {} active".format(len(state["active"])))
            return

        if event_name == "Stop":
            if key in state["completed"]:
                log("Ignored duplicate completion for {}".format(key))
                return

            fallback_snapshot = None
            if not state.get("snapshot"):
                fallback_snapshot = snapshot_room(client, group_id)
            state["active"].pop(key, None)
            state["completed"][key] = time.time()
            save_state(state)

            client.group_action(group_id, config.get("complete", DEFAULT_COMPLETE))
            time.sleep(float(config.get("completion_hold_seconds", 1.0)))

            if state["active"]:
                client.group_action(group_id, config.get("busy", DEFAULT_BUSY))
            else:
                restore_room(
                    client,
                    state.get("snapshot") or fallback_snapshot,
                    transitiontime=config.get("restore_transitiontime", 2),
                    request_gap_seconds=config.get("restore_request_gap_seconds", 0.12),
                )
                state["snapshot"] = None
            save_state(state)
            time.sleep(float(config.get("completion_gap_seconds", 0.35)))
            log("Turn completed; {} active".format(len(state["active"])))
            return

        log("Ignored unsupported hook event {}".format(event_name))


def enqueue_event(event_name, session_id, turn_id):
    queued = {
        "id": "{}-{}-{}".format(os.getpid(), time.time_ns(), event_name),
        "event_name": event_name,
        "session_id": session_id or "",
        "turn_id": turn_id or "",
    }
    with QueueLock():
        queue = read_json(queue_path(), [])
        if not isinstance(queue, list):
            queue = []
        queue.append(queued)
        write_json_atomic(queue_path(), queue)


def spawn_drain_worker():
    command = [
        sys.executable,
        "-m",
        "codex_hue",
        "_drain",
    ]
    if os.environ.get("CODEX_HUE_FOREGROUND") == "1":
        drain_events()
        return
    with open(os.devnull, "rb") as stdin_handle, open(
        os.devnull, "ab"
    ) as output_handle:
        subprocess.Popen(
            command,
            stdin=stdin_handle,
            stdout=output_handle,
            stderr=output_handle,
            close_fds=True,
            start_new_session=True,
        )


def dispatch_event(event_name, session_id, turn_id):
    enqueue_event(event_name, session_id, turn_id)
    spawn_drain_worker()


def drain_events():
    worker_lock = FileLock(worker_lock_path(), nonblocking=True)
    with worker_lock as acquired:
        if acquired is None:
            return
        while True:
            with QueueLock():
                queue = read_json(queue_path(), [])
                if not isinstance(queue, list) or not queue:
                    return
                queued = dict(queue[0])
            try:
                process_event(
                    queued.get("event_name", ""),
                    queued.get("session_id", ""),
                    queued.get("turn_id", ""),
                )
            except Exception as error:
                log(
                    "{} worker failed: {}".format(
                        queued.get("event_name", "unknown"), error
                    )
                )
            finally:
                with QueueLock():
                    latest = read_json(queue_path(), [])
                    if latest and latest[0].get("id") == queued.get("id"):
                        latest.pop(0)
                        write_json_atomic(queue_path(), latest)


def hook_command():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    event_name = payload.get("hook_event_name", "")
    if event_name in ("UserPromptSubmit", "Stop"):
        try:
            dispatch_event(
                event_name, payload.get("session_id", ""), payload.get("turn_id", "")
            )
        except Exception as error:
            log("Could not dispatch {}: {}".format(event_name, error))
    if event_name in ("UserPromptSubmit", "Stop"):
        print(json.dumps({"continue": True}))
    return 0


def pair(host, port, wait_seconds):
    fingerprint = bridge_fingerprint(host, port=port)
    client = HueClient(host, fingerprint=fingerprint, port=port)
    device_name = "codex_hue_indicator#{}".format(socket.gethostname().split(".")[0])
    deadline = time.monotonic() + float(wait_seconds)
    while True:
        try:
            response = client.request(
                "POST", "/api", {"devicetype": device_name, "generateclientkey": True}
            )
            for item in response:
                success = item.get("success") if isinstance(item, dict) else None
                if success and success.get("username"):
                    return fingerprint, success["username"]
        except HueError as error:
            if "link button not pressed" not in str(error).lower():
                raise
        if time.monotonic() >= deadline:
            raise HueError("Pairing timed out; press the Bridge button and try setup again")
        time.sleep(1.0)


def selectable_groups(groups):
    result = []
    for group_id, group in groups.items():
        group_type = group.get("type", "")
        if group_type in SUPPORTED_GROUP_TYPES:
            result.append(
                {
                    "id": str(group_id),
                    "name": group.get("name", "Unnamed"),
                    "type": group_type,
                    "lights": list(group.get("lights", [])),
                }
            )
    return sorted(result, key=lambda item: (item["type"] != "Room", item["name"].lower()))


def select_group(groups, selector):
    candidates = selectable_groups(groups)
    selector_folded = str(selector).casefold()
    matches = [
        item
        for item in candidates
        if item["id"] == str(selector) or item["name"].casefold() == selector_folded
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise HueError("No Hue room or zone matched {!r}".format(selector))
    raise HueError("More than one Hue group matched {!r}; use its numeric id".format(selector))


def base_config(host, port, fingerprint, username):
    return {
        "version": 1,
        "bridge_host": host,
        "bridge_port": int(port),
        "certificate_sha256": fingerprint,
        "username": username,
        "group_id": None,
        "group_name": None,
        "busy": DEFAULT_BUSY,
        "complete": DEFAULT_COMPLETE,
        "completion_hold_seconds": 1.0,
        "completion_gap_seconds": 0.35,
        "request_timeout_seconds": 3.0,
        "restore_transitiontime": 2,
        "restore_request_gap_seconds": 0.12,
        "stale_after_seconds": 86400,
    }


def print_groups(groups):
    candidates = selectable_groups(groups)
    if not candidates:
        print("No Hue rooms or zones were found.")
        return
    print("Available Hue rooms and zones:")
    for item in candidates:
        print(
            "  {:>3}  {:<28} {:<10} {} light(s)".format(
                item["id"], item["name"], item["type"], len(item["lights"])
            )
        )


def choose_bridge(bridges):
    if len(bridges) == 1:
        return bridges[0]["internalipaddress"]
    print("Discovered Hue Bridges:")
    for index, bridge in enumerate(bridges, start=1):
        print(
            "  {}. {} ({})".format(
                index,
                bridge.get("internalipaddress"),
                bridge.get("id") or bridge.get("source") or "unknown",
            )
        )
    while True:
        selection = input("Choose a Bridge [1-{}]: ".format(len(bridges))).strip()
        try:
            return bridges[int(selection) - 1]["internalipaddress"]
        except (ValueError, IndexError):
            print("Enter a number from 1 to {}.".format(len(bridges)))


def choose_group(groups):
    candidates = selectable_groups(groups)
    if not candidates:
        raise HueError("No Hue rooms or zones were found")
    print_groups(groups)
    while True:
        selection = input("Choose a room or zone by number or name: ").strip()
        try:
            return select_group(groups, selection)
        except HueError as error:
            print("{}".format(error))


def setup_command(args):
    host = args.bridge
    if not host:
        bridges = discover_bridges()
        if not bridges:
            raise HueError("No Hue Bridge was discovered; pass --bridge with its local IP")
        host = choose_bridge(bridges)

    print("Using Hue Bridge at {}:{}".format(host, args.port))
    print("Press the round link button on the Hue Bridge now.")
    fingerprint, username = pair(host, args.port, args.wait)
    config = base_config(host, args.port, fingerprint, username)
    client = client_from_config(config)
    groups = client.groups()

    group = select_group(groups, args.room) if args.room else choose_group(groups)
    config["group_id"] = group["id"]
    config["group_name"] = group["name"]
    write_json_atomic(config_path(), config)
    print(
        "Configured Hue {}: {} (id {})".format(
            group["type"], group["name"], group["id"]
        )
    )
    print("Next: run 'codex-hue test', then 'codex-hue install-hooks'.")
    return 0


def discover_command():
    bridges = discover_bridges()
    if not bridges:
        raise HueError("No Hue Bridge was discovered on the local network")
    for bridge in bridges:
        print(
            "{}  {}  {}".format(
                bridge.get("id") or "unknown",
                bridge.get("internalipaddress"),
                bridge.get("source") or "unknown",
            )
        )


def set_room_command(selector):
    config = read_json(config_path(), None)
    if not isinstance(config, dict) or not config.get("username"):
        raise HueError("Run setup before selecting a room")
    client = client_from_config(config)
    group = select_group(client.groups(), selector)
    config["group_id"] = group["id"]
    config["group_name"] = group["name"]
    write_json_atomic(config_path(), config)
    print("Configured Hue {}: {} (id {})".format(group["type"], group["name"], group["id"]))


def rooms_command():
    config = read_json(config_path(), None)
    if not isinstance(config, dict) or not config.get("username"):
        raise HueError("Run setup before listing rooms")
    print_groups(client_from_config(config).groups())


def test_command():
    config = load_config()
    client = client_from_config(config)
    with StateLock():
        state = load_state()
        temporary_snapshot = snapshot_room(client, str(config["group_id"]))
        client.group_action(str(config["group_id"]), config.get("complete", DEFAULT_COMPLETE))
        time.sleep(float(config.get("completion_hold_seconds", 1.0)))
        if state["active"]:
            client.group_action(str(config["group_id"]), config.get("busy", DEFAULT_BUSY))
        else:
            restore_room(
                client,
                temporary_snapshot,
                transitiontime=config.get("restore_transitiontime", 2),
                request_gap_seconds=config.get("restore_request_gap_seconds", 0.12),
            )
    print("Pulsed {} green and restored its prior state.".format(config["group_name"]))


def reset_command():
    config = load_config()
    client = client_from_config(config)
    with StateLock():
        state = load_state()
        if state.get("snapshot"):
            restore_room(
                client,
                state["snapshot"],
                transitiontime=config.get("restore_transitiontime", 2),
                request_gap_seconds=config.get("restore_request_gap_seconds", 0.12),
            )
        save_state(default_state())
    print("Cleared active turns and restored the saved room state.")


def status_command():
    config = read_json(config_path(), {})
    state = load_state()
    result = {
        "configured": bool(config.get("group_id")),
        "bridge_host": config.get("bridge_host"),
        "group_id": config.get("group_id"),
        "group_name": config.get("group_name"),
        "active_turns": len(state.get("active", {})),
        "has_saved_room_state": bool(state.get("snapshot")),
        "log": str(log_path()),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def is_our_hook_handler(handler):
    if not isinstance(handler, dict):
        return False
    command = str(handler.get("command", ""))
    return "codex_hue" in command and command.rstrip().endswith(" hook")


def remove_our_hook_handlers(document):
    hooks = document.setdefault("hooks", {})
    removed = 0
    for event_name in ("UserPromptSubmit", "Stop"):
        groups = hooks.get(event_name, [])
        if not isinstance(groups, list):
            continue
        remaining_groups = []
        for group in groups:
            if not isinstance(group, dict):
                remaining_groups.append(group)
                continue
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list):
                remaining_groups.append(group)
                continue
            kept = [handler for handler in handlers if not is_our_hook_handler(handler)]
            removed += len(handlers) - len(kept)
            if kept:
                updated = dict(group)
                updated["hooks"] = kept
                remaining_groups.append(updated)
        hooks[event_name] = remaining_groups
    return removed


def codex_hue_hook_group(status_message):
    arguments = [sys.executable, "-m", "codex_hue", "hook"]
    return {
        "hooks": [
            {
                "type": "command",
                "command": shlex.join(arguments),
                "commandWindows": subprocess.list2cmdline(arguments),
                "timeout": 5,
                "statusMessage": status_message,
            }
        ]
    }


def load_hooks_document(path):
    if not path.exists():
        return {"hooks": {}}
    try:
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise HueError("Could not read {}: {}".format(path, error)) from error
    if not isinstance(document, dict):
        raise HueError("{} must contain a JSON object".format(path))
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HueError("The 'hooks' value in {} must be a JSON object".format(path))
    return document


def backup_hooks(path):
    if not path.exists():
        return None
    backup = path.with_name(
        "{}.backup-{}".format(path.name, time.strftime("%Y%m%d-%H%M%S"))
    )
    shutil.copy2(path, backup)
    try:
        os.chmod(backup, 0o600)
    except OSError:
        pass
    return backup


def install_hooks_command():
    path = hooks_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    document = load_hooks_document(path)
    remove_our_hook_handlers(document)
    document["hooks"].setdefault("UserPromptSubmit", []).append(
        codex_hue_hook_group("Setting Hue room to busy")
    )
    document["hooks"].setdefault("Stop", []).append(
        codex_hue_hook_group("Notifying Hue room of completion")
    )
    backup = backup_hooks(path)
    write_json_atomic(path, document)
    print("Installed Codex hooks in {}.".format(path))
    if backup:
        print("Backed up the previous file to {}.".format(backup))
    print("Restart Codex, review the hooks when prompted, and trust them to enable.")


def uninstall_hooks_command():
    path = hooks_path()
    document = load_hooks_document(path)
    removed = remove_our_hook_handlers(document)
    if not removed:
        print("No codex-hue hooks were installed in {}.".format(path))
        return
    backup = backup_hooks(path)
    write_json_atomic(path, document)
    print("Removed {} codex-hue hook(s) from {}.".format(removed, path))
    if backup:
        print("Backed up the previous file to {}.".format(backup))


def build_parser():
    parser = argparse.ArgumentParser(prog=PROJECT_NAME, description=__doc__)
    public_commands = (
        "{setup,discover,set-room,rooms,test,reset,status,install-hooks,"
        "uninstall-hooks}"
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar=public_commands
    )

    setup_parser = subparsers.add_parser("setup", help="discover and pair with a Hue Bridge")
    setup_parser.add_argument("--bridge", help="local bridge hostname or IP")
    setup_parser.add_argument("--port", type=int, default=443)
    setup_parser.add_argument("--room", help="Hue room/zone name or numeric id")
    setup_parser.add_argument("--wait", type=float, default=60.0)

    subparsers.add_parser("discover", help="discover Hue Bridges on the local network")
    set_room_parser = subparsers.add_parser("set-room", help="select a Hue room or zone")
    set_room_parser.add_argument("selector")
    subparsers.add_parser("rooms", help="list Hue rooms and zones")
    subparsers.add_parser("test", help="pulse the configured room and restore it")
    subparsers.add_parser("reset", help="clear active turns and restore saved lighting")
    subparsers.add_parser("status", help="show non-secret indicator status")
    subparsers.add_parser("install-hooks", help="add codex-hue to the Codex hooks file")
    subparsers.add_parser("uninstall-hooks", help="remove codex-hue from the Codex hooks file")
    subparsers.add_parser("hook")
    subparsers.add_parser("_drain")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "setup":
            return setup_command(args)
        if args.command == "discover":
            discover_command()
        elif args.command == "set-room":
            set_room_command(args.selector)
        elif args.command == "rooms":
            rooms_command()
        elif args.command == "test":
            test_command()
        elif args.command == "reset":
            reset_command()
        elif args.command == "status":
            status_command()
        elif args.command == "install-hooks":
            install_hooks_command()
        elif args.command == "uninstall-hooks":
            uninstall_hooks_command()
        elif args.command == "hook":
            return hook_command()
        elif args.command == "_drain":
            drain_events()
        return 0
    except HueError as error:
        print("Error: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
