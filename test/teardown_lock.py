#!/usr/bin/env python3
"""An allocate made during a slow teardown is answered at once (0.17.0).

2026-10-22, the studio: the broker held its lock while the reaper tore down
leases (group kills, simctl delete). Allocates queued behind it waited past the
SSB daemon's 30s, failed "no port", and were granted anyway once the lock came
free — blocks reserved for their whole TTL with nobody to release them.
Pure: loads the script as a module; no daemon, no emulators.

    python3 test/teardown_lock.py
"""
import importlib.machinery, importlib.util, os, pathlib, tempfile, threading, time

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

TEARDOWN_S = 3.0
DEAD = 2**22 + 12345                       # a pid nobody has

def broker():
    b = hm.Broker.__new__(hm.Broker)
    b.lock = threading.RLock()
    b._save = lambda: None
    b.leases, b.draining = {}, {}
    b._swept = b._sims_checked = time.time()
    b._record_trees = lambda: None
    b._sweep_world = lambda apply: []
    b.torn = []
    def slow_cleanup(rec):
        time.sleep(TEARDOWN_S)
        b.torn.append(rec["leaseId"])
    b._cleanup = slow_cleanup
    return b

def timed(fn):
    t = time.time()
    out = fn()
    return out, time.time() - t

# The reaper's teardown runs outside the lock.
b = broker()
first = b.allocate(os.getpid(), label="doomed")
b.leases[first["leaseId"]]["owner_pid"] = DEAD     # its owner dies
reaper = threading.Thread(target=b.reap); reaper.start()
time.sleep(0.3)                                      # the teardown is under way
check("the reaped lease is draining", first["leaseId"] in b.draining)
got, took = timed(lambda: b.allocate(os.getpid(), label="during-reap"))
check(f"allocate during a reaper teardown returns promptly ({took:.2f}s)", took < 1.0)
check("it does not get the draining block", got["base"] != first["base"])
reaper.join()
check("the teardown still ran", b.torn == [first["leaseId"]])
check("the drained block is out of draining", not b.draining)
check("the new lease is held", got["leaseId"] in b.leases)

# So does a release's.
b = broker()
one = b.allocate(os.getpid(), label="released")
rel = threading.Thread(target=lambda: b.release(one["leaseId"])); rel.start()
time.sleep(0.3)
got, took = timed(lambda: b.allocate(os.getpid(), label="during-release"))
check(f"allocate during a release teardown returns promptly ({took:.2f}s)", took < 1.0)
check("it does not get the releasing block", got["base"] != one["base"])
rel.join()
check("the released block returns to the pool after its teardown",
      b._free_block() == one["base"])

# A simulator being created holds its block without holding the lock.
b = broker()
real_create = hm._sim_create_boot
hm._sim_create_boot = lambda device, runtime, name: (time.sleep(TEARDOWN_S), "UDID-" + name)[1]
box = {}
simt = threading.Thread(target=lambda: box.update(r=b.allocate(os.getpid(), sim=True, label="sim")))
simt.start()
time.sleep(0.3)
got, took = timed(lambda: b.allocate(os.getpid(), label="during-sim"))
check(f"allocate during a sim create returns promptly ({took:.2f}s)", took < 1.0)
simt.join()
hm._sim_create_boot = real_create
check("the sim lease was granted", box["r"]["sim"]["udid"].startswith("UDID-"))
check("the two leases got different blocks", box["r"]["base"] != got["base"])
check("the sim lease carries its udid", b.leases[box["r"]["leaseId"]]["sim_udid"] == box["r"]["sim"]["udid"])

# A caller that gave up waiting is not granted a block it will never release.
b = broker()
try:
    b.allocate(os.getpid(), label="gone", client_gone=lambda: True)
    check("a gone client is refused", False)
except RuntimeError:
    check("a gone client is refused", True)
check("and no lease is left behind", not b.leases and not b.draining)

hm._sim_create_boot = lambda device, runtime, name: "UDID-" + name
b = broker()
try:
    b.allocate(os.getpid(), sim=True, label="gone-sim", client_gone=lambda: True)
    check("a gone client's sim lease is refused", False)
except RuntimeError:
    check("a gone client's sim lease is refused", True)
check("and what was made for it is torn down", len(b.torn) == 1 and not b.leases and not b.draining)
hm._sim_create_boot = real_create

# The handler sees a real hang-up: a client whose timeout fired and closed.
import http.client, http.server, socket
class Stub:
    def allocate(self, *a, client_gone=None, **k):
        time.sleep(0.6)                      # the caller gives up meanwhile (or not)
        seen.append(client_gone())
        return {"leaseId": "x", "base": 0, "ports": {}}
hm._Handler.broker = Stub()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), hm._Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
seen = []
s = socket.create_connection(("127.0.0.1", port))
body = b"{}"
s.sendall(b"POST /allocate HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
          b"Content-Length: 2\r\n\r\n" + body)
time.sleep(0.2); s.close()                   # timed out and hung up
time.sleep(0.8)
check("a client that hung up reads as gone", seen == [True])
seen.clear()
c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
c.request("POST", "/allocate", body=body, headers={"Content-Type": "application/json"})
check("a client still waiting gets its answer", c.getresponse().status == 200)
check("and reads as present", seen == [False])
srv.shutdown()

raise SystemExit(1 if failed else 0)
