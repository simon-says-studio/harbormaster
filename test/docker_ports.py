#!/usr/bin/env python3
"""A block docker holds is not free (harbormaster _free_block, 0.10.0).

On Linux dockerd publishes a container's ports through iptables and, with no
userland proxy, nothing listens on them — a connect finds them quiet. Simon
Says' local Supabase stacks are containers on 20-port blocks; on simon-linux-1
(2026-10-09) four jobs were handed a block a stack still held. Pure: loads the
script as a module, no daemon, no ports, no docker.

    python3 test/docker_ports.py
"""
import importlib.machinery, importlib.util, pathlib, sys

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec)
loader.exec_module(hm)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

ps = "0.0.0.0:11004->9000/tcp, :::11004->9000/tcp\n0.0.0.0:11040-11041->8000-8001/tcp\n\n127.0.0.1:5432->5432/tcp"
check("parses single ports, ranges and both address families",
      hm._parse_published(ps) == {11004, 11040, 11041, 5432})
check("nothing published parses to nothing", hm._parse_published("") == set())

# A broker with no daemon behind it: no ledger, no reconcile.
b = hm.Broker.__new__(hm.Broker)
b.leases = {"a": {"block": hm.POOL_BASE + hm.BLOCK}}          # block 1 is leased
hm._port_open = lambda port, host="127.0.0.1": False           # nothing answers a connect
hm._docker_published_ports = lambda: {hm.POOL_BASE + 4}       # docker holds a port in block 0
check("a block docker publishes into is skipped, as is a leased one",
      b._free_block() == hm.POOL_BASE + 2 * hm.BLOCK)
hm._docker_published_ports = lambda: set()
check("without docker's answer the connect decides, as before",
      b._free_block() == hm.POOL_BASE)

fresh = importlib.util.module_from_spec(spec); loader.exec_module(fresh)
def boom(*a, **k): raise OSError("no docker")
fresh.subprocess.run = boom
check("no docker is the empty set, never a failure", fresh._docker_published_ports() == set())

print(f"\n{'FAILED' if failed else 'passed'}")
sys.exit(1 if failed else 0)
