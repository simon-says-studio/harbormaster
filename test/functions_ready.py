#!/usr/bin/env python3
"""A suite with functions is ready when its triggers are, not its ports (0.21.0).

2026-11-05, walk2gether-voice-agent's voice-walk simulation: firebase-tools
binds every emulator's port, THEN the functions emulator loads its source and
registers its Firestore triggers. acquire returned on open ports, and writes in
the seconds after it were never delivered to any trigger. A functions suite now
waits for the CLI's "All emulators ready!" line (printed after every
emulator's connect(), trigger registration included); a suite without functions
does not wait for it.

Drives the real EmulatorPool boot loop against a fake `firebase` on PATH that
binds the injected config's ports at once and prints the mark only later. No
daemon, no emulators.

    python3 test/functions_ready.py
"""
import importlib.machinery, importlib.util, json, os, pathlib, socket, sys, tempfile, time

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
os.environ["FBPORTS_STATE_DIR"] = tempfile.mkdtemp()
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec); loader.exec_module(hm)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

# `firebase emulators:start --config X [--only a,b]`: bind the --only ports from
# X at once, print the CLI's early lines, then the ready mark after
# FAKE_MARK_DELAY seconds ("never": never), noting when in FAKE_MARK_AT.
FAKE = r'''#!/usr/bin/env python3
import json, os, socket, sys, time
a = sys.argv
cfg = json.load(open(a[a.index("--config") + 1]))
only = a[a.index("--only") + 1].split(",")
socks = []
for svc in only:
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", cfg["emulators"][svc]["port"])); s.listen(); socks.append(s)
print("i  functions: Watching \"/x\" for Cloud Functions...", flush=True)
delay = os.environ["FAKE_MARK_DELAY"]
if delay != "never":
    time.sleep(float(delay))
    print("✔  functions: Loaded functions definitions from source: onUserCreated.", flush=True)
    print("✔  functions[us-central1-onUserCreated]: firestore function initialized.", flush=True)
    open(os.environ["FAKE_MARK_AT"], "w").write(str(time.time()))
    print("\x1b[90m│\x1b[39m ✔  \x1b[1mAll emulators ready! It is now safe to connect your app.\x1b[22m", flush=True)
time.sleep(60)
'''

work = pathlib.Path(tempfile.mkdtemp())
bindir = work / "bin"; bindir.mkdir()
(bindir / "firebase").write_text(FAKE); (bindir / "firebase").chmod(0o755)
os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
proj = work / "proj"; proj.mkdir()
(proj / "firebase.json").write_text(json.dumps(
    {"emulators": {"auth": {}, "firestore": {}, "functions": {}}}))
mark_at = work / "mark-at"
os.environ["FAKE_MARK_AT"] = str(mark_at)

def free_block():
    for base in range(16000, 20000, hm.BLOCK):
        if not any(hm._port_open(p) for p in hm._block_ports(base).values()):
            return base
    raise SystemExit("no free 20-port block in 16000-19999")

pool = hm.Broker.__new__(hm.Broker)
n = [0]
last_base = [None]
def boot(only, delay):
    if mark_at.exists():
        mark_at.unlink()
    os.environ["FAKE_MARK_DELAY"] = delay
    n[0] += 1
    base = last_base[0] = free_block()
    t = time.time()
    try:
        pid, *_ = pool._boot(str(proj), base, only, None, f"t{n[0]}")
        return time.time() - t, pid, None
    except RuntimeError as e:
        return time.time() - t, None, e

def stop(pid):
    if pid:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass

# 1. functions in the suite: not ready until the mark, though the ports open at once.
took, pid, err = boot(["auth", "firestore", "functions"], "2.5")
returned_at = time.time()
check("a functions suite boots", err is None)
check(f"…and is not ready before its triggers are registered (took {took:.1f}s, mark at 2.5s)",
      mark_at.exists() and returned_at >= float(mark_at.read_text()))
check("…and is ready promptly once they are", took < 2.5 + 1.5)
stop(pid)

# 2. no functions: ready on open ports, never waits for a mark that may not come.
took, pid, err = boot(["auth", "firestore"], "never")
check(f"a suite without functions is ready on open ports alone (took {took:.1f}s)",
      err is None and took < 2.0)
stop(pid)

# 3. functions, and the mark never comes: a clear error, and the suite is killed.
hm.FUNCTIONS_READY_TIMEOUT = 2
took, pid, err = boot(["auth", "firestore", "functions"], "never")
check(f"a functions suite whose triggers never register fails at the timeout (took {took:.1f}s)",
      err is not None and 2 <= took < 6)
check("…naming why", err is not None and "All emulators ready!" in str(err)
      and "triggers" in str(err))
time.sleep(0.5)
check("…and the suite is killed (its functions port is closed)",
      not hm._port_open(hm._block_ports(last_base[0])["functions"]))

# 4. the log scan: incremental, and a mark split across two reads still counts.
log = work / "split.log"
log.write_text("i  functions: loading...\n✔  All emulators re")
seen = hm._LogMark(log, hm.EMULATORS_READY_MARK)
check("a half-written mark is not the mark", seen() is False)
with open(log, "a") as f:
    f.write("ady! It is now safe to connect your app.\n")
check("…its second half completes it", seen() is True)
check("a missing log is simply not ready", hm._LogMark(work / "nope.log", "x")() is False)

print(f"\n{'FAILED' if failed else 'passed'}")
sys.exit(1 if failed else 0)
