#!/usr/bin/env python3
"""The Firestore emulator's JVM gets a heap cap (see emulator_java_env). Pure:
loads the script as a module, no daemon, no ports.

    python3 test/emulator_heap.py
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

f = hm.emulator_java_env
check("capped at 2g by default", f({}) == {"JAVA_TOOL_OPTIONS": "-Xmx2g"})
check("the size is overridable", f({"FBPORTS_EMULATOR_HEAP": "4g"}) == {"JAVA_TOOL_OPTIONS": "-Xmx4g"})
check("'0' turns it off", f({"FBPORTS_EMULATOR_HEAP": "0"}) == {})
check("'off' turns it off", f({"FBPORTS_EMULATOR_HEAP": "off"}) == {})
check("existing options are kept, the cap appended",
      f({"JAVA_TOOL_OPTIONS": "-Dfile.encoding=UTF-8"}) == {"JAVA_TOOL_OPTIONS": "-Dfile.encoding=UTF-8 -Xmx2g"})
check("a caller's own -Xmx wins", f({"JAVA_TOOL_OPTIONS": "-Dx=1 -Xmx6g"}) == {})
check("-XX:MaxRAM… is not mistaken for -Xmx", "Xmx2g" in f({"JAVA_TOOL_OPTIONS": "-XX:MaxRAMPercentage=10"})["JAVA_TOOL_OPTIONS"])

print(f"\n{'all passed' if not failed else f'{failed} failed'}")
sys.exit(1 if failed else 0)
