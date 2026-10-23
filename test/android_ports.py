#!/usr/bin/env python3
"""An Android emulator console/adb pair is a lease too (0.15.0).

SimonSays' android_pick_port derived a console port from the block's slot and
then `lsof`-probed 5554..5584: outside harbormaster's pool, so nothing made two
callers' picks disjoint. `--android` leases the pair (console even, adb =
console + 1) under the broker's lock. Loads the script as a module with its
own state dir; the one process it spawns is `/bin/sh -c env`. No daemon, no
emulator, no ports bound.

    python3 test/android_ports.py
"""
import importlib.machinery, importlib.util, os, pathlib, sys, tempfile, time

STATE = tempfile.mkdtemp(prefix="hm-android-")
os.environ["FBPORTS_STATE_DIR"] = STATE
HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec)
loader.exec_module(hm)
hm.STATE_DIR.mkdir(parents=True, exist_ok=True)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

listening = set()
hm._port_open = lambda port, host="127.0.0.1": port in listening
hm._docker_published_ports = lambda: set()

b = hm.Broker.__new__(hm.Broker)
b.lock, b.leases, b.draining = hm.threading.RLock(), {}, {}

check("the range is adb's: even consoles 5554..5584",
      (hm.ANDROID_CONSOLE_FIRST, hm.ANDROID_CONSOLE_LAST) == (5554, 5584))
check("an empty world hands out 5554", b._free_android_console() == 5554)
b.leases["x"] = {"ports": {"base": 11000, "android_console": 5554, "android_adb": 5555}}
check("a leased pair is skipped", b._free_android_console() == 5556)
listening |= {5557}
check("a pair whose ADB port is held is skipped (a hand-booted emulator)", b._free_android_console() == 5558)
listening |= {5558}
check("…and one whose console port is", b._free_android_console() == 5560)
listening |= set(range(5560, 5586))
try:
    b._free_android_console()
    check("a full range refuses", False)
except RuntimeError as e:
    check("a full range refuses, saying so", "android console pool exhausted" in str(e))
listening.clear()
b.leases.clear()

env = hm._android_env({"android_console": 5562, "android_adb": 5563})
check("the caller is told console, adb and the serial adb knows it by",
      env == {"ANDROID_CONSOLE_PORT": "5562", "ANDROID_ADB_PORT": "5563", "ANDROID_SERIAL": "emulator-5562"})

# allocate --android --spawn: the pair is in the answer, the ledger and the
# spawned process's environment.
out_file = pathlib.Path(STATE) / "spawn-env"
r1 = b.allocate(None, android=True, spawn=f"env > {out_file}", label="android-test")
r2 = b.allocate(None, android=True, label="android-test-2")
check("allocate --android returns a pair", r1["ports"].get("android_console") == 5554
      and r1["ports"].get("android_adb") == 5555)
check("a second lease gets the next pair, not the same one", r2["ports"]["android_console"] == 5556)
check("a lease without --android has no pair",
      "android_console" not in b.allocate(None, label="plain")["ports"])
for _ in range(50):
    if out_file.exists() and "ANDROID_SERIAL" in out_file.read_text():
        break
    time.sleep(0.1)
spawned = out_file.read_text() if out_file.exists() else ""
check("the spawned process sees ANDROID_CONSOLE_PORT / ANDROID_ADB_PORT / ANDROID_SERIAL",
      "ANDROID_CONSOLE_PORT=5554" in spawned and "ANDROID_ADB_PORT=5555" in spawned
      and "ANDROID_SERIAL=emulator-5554" in spawned)

# Teardown: the pair is outside the pool, where a hand-booted emulator lands by
# default — so a stranger on it is reported, never killed.
killed, stranger = [], 999999
hm._listeners = lambda: {5554: {stranger}}
hm._kill_wave = lambda pids, wait=5.0: killed.extend(pids) or set(pids)
b.release(r1["leaseId"])
check("teardown never signals a process on the pair it didn't record", stranger not in killed)
check("released pair is free again", b._free_android_console() == 5554)

# World sweep: an unleased listener on the android range is a finding, not
# evicted (nothing attributes it); a leased pair is not a finding.
hm._listeners = lambda: {5556: {stranger}, 5570: {stranger + 1}}
hm._proc_field = lambda pid, fmt: "qemu-system-aarch64 -avd hand"
hm._sim_inventory = lambda: None
f = b._sweep_world(apply=False)
ports = {x["port"]: x for x in f if x["kind"] == "listener"}
check("an unleased emulator on the range is reported", 5570 in ports)
check("…and not evicted", ports.get(5570, {}).get("evict") is False)
check("a leased pair is not a finding", 5556 not in ports)

import shutil; shutil.rmtree(STATE, ignore_errors=True)
print("FAILED" if failed else "all passed")
sys.exit(1 if failed else 0)
