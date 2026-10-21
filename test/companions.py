#!/usr/bin/env python3
"""An idb companion whose simulator is gone is ended, and its socket removed (0.14.0).

2026-10-20, the Mac Studio: 19 `idb_companion --udid <UDID>` for simulators
that no longer existed, some from Oct 19, and 109 stale sockets in /tmp/idb.
A lease deleted its device; nothing ended the device's companion. Pure: loads
the script as a module; no daemon, no simctl.

    python3 test/companions.py
"""
import importlib.machinery, importlib.util, os, pathlib, sys, tempfile

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

GONE, LIVE, NEW = ("30F1C7AD-5B65-432C-8F8F-9C51A11E452D", "11613214-19C5-4ACB-BE96-CF3B39EFFBF1",
                   "45420093-F383-482C-8E10-266871ACD66C")
def comp(udid):
    return (f"/opt/homebrew/bin/idb_companion --udid {udid} --grpc-domain-sock "
            f"/tmp/idb/{udid}_companion.sock --only simulator")
ps = "\n".join([
    f" 2743 1-04:00:00 {comp(GONE)}",
    f"10320 2-00:00:00 {comp(LIVE)}",
    f"10803     02:10 {comp(NEW)}",
    f"11000 1-00:00:00 /usr/bin/grep idb_companion --udid {GONE}",   # not a companion
    f"11001 1-00:00:00 /opt/homebrew/bin/idb_companion --notify stdout",  # names no device
])
comps = hm._companions(ps)
check("every companion bound to a device is read", sorted(c["pid"] for c in comps) == [2743, 10320, 10803])
check("its device and age", [c for c in comps if c["pid"] == 2743][0] == {"pid": 2743, "udid": GONE, "upS": 28 * 3600})

known = {LIVE}
dead = hm.dead_companions(comps, known)
check("only the one whose device is gone", [c["pid"] for c in dead] == [2743])
check("a device that exists keeps its companion", all(c["udid"] != LIVE for c in dead))
check("a young companion is left (its device may be newer than the read)", all(c["udid"] != NEW for c in dead))
check("lower-case UDIDs match", hm._companions(f"1 1-00:00:00 {comp(GONE.lower())}")[0]["udid"] == GONE)

socks = [f"{GONE}_companion.sock", f"{LIVE}_companion.sock", f"{NEW}_companion.sock", "notes.txt"]
stale = hm.stale_companion_sockets(socks, known, live={NEW})
check("a gone device's socket nobody holds is removed", stale == [f"{GONE}_companion.sock"])
check("a held socket stays, device or not", f"{NEW}_companion.sock" not in stale)
check("anything else in the directory is left", "notes.txt" not in stale)

sys.exit(1 if failed else 0)
