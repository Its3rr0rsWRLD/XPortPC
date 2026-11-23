"""The xgameruntime.dll gateway under a title-shaped driver (tests/xgr/gateway_title.cpp): unknown CLSID/IID queries
get logging fallback objects, unknown and inferred slots answer failure codes without touching their arguments (XNetworking slot 15 with the
arguments a title was seen to use), XUserAddAsync's default user works through the table, and the gateway's log
says what happened. A run with X2W_XGR_INFERRED=1 serves the inferred slots; one with X2W_XGR_STRICT=1 keeps the old
0x80070032 answer.

Usage: gateway_check.py gateway_title.exe x2w_xgr.dll
"""
import os
import re
import subprocess
import sys


def run(title, gateway, *extra, env=None):
    environment = dict(os.environ)
    for name in ("X2W_XGR_MODE", "X2W_XGR_CALLS", "X2W_XGR_STRICT", "X2W_XGR_INFERRED", "X2W_GAMERTAG", "X2W_USER_ID"):
        environment.pop(name, None)
    environment.update(env or {})
    result = subprocess.run([title, gateway, *extra], capture_output=True, text=True, timeout=90, env=environment)
    return result.returncode, result.stdout, result.stderr


def main(title, gateway):
    failures = []
    code, out, err = run(title, gateway)
    print(out.strip())
    if code != 0 or "failures=0" not in out:
        failures.append(f"fallback run: exit {code}\n{out}\n{err}")
    expected = {
        "unknown CLSID fallback logged": r"xgr-fallback \{[0-9a-f-]+\}\{[0-9a-f-]+\} clsid=\S+ iid=\S+ unknown CLSID: slots log and answer 0x80004001",
        "unlisted IID of a known class logged": r"xgr-fallback XUser\{[0-9a-f-]+\} .*unlisted IID of a known class: slots log and answer 0x89245106",
        "IID of another class logged": r"xgr-fallback XUser\{bf2346b2-[0-9a-f-]+\} .*IID of another class: slots log and answer 0x89245106",
        "unknown slot 15 logged with index and four args": r"xgr-unknown-slot \{[0-9a-f-]+\}\{[0-9a-f-]+\} slot 15 args 0x[0-9a-f]+ 0x7ffffffffffffffc 0x40 0x[0-9a-f]+ -> 0x80004001",
        "XUser unknown slot answers no-default-user": r"xgr-unknown-slot IXUserImpl slot 40 args .* -> 0x89245106",
        "networking slot 15 unmapped, logged": r"xgr-unknown-slot IXNetworkingImpl_bf2346b2 slot 15 args 0x[0-9a-f]+ 0x7ffffffffffffffc 0x40 0x[0-9a-f]+ -> 0x80004001 caller",
        "networking slot 8 (not served) logged": r"xgr-unknown-slot IXNetworkingImpl_bf2346b2 slot 8 args",
        "inferred networking slot named, not served": r"xgr-unknown-slot IXNetworkingImpl_bf2346b2 slot 3 args .* -> 0x80004001 \(inferred XNetworkingGetConnectivityHint, not served\)",
        "inferred XUser slot named, not served": r"xgr-unknown-slot IXUserImpl slot 9 args .* -> 0x89245106 \(inferred XUserGetId, not served\)",
    }
    forbidden = {
        "no assumption served by default": r"xgr-assume",
        "slot 15 never writes an object": r"xgr-slot15",
    }
    for what, pattern in forbidden.items():
        if re.search(pattern, err):
            failures.append(f"log line present: {what}\n  /{pattern}/")
    for what, pattern in expected.items():
        if not re.search(pattern, err):
            failures.append(f"log line missing: {what}\n  /{pattern}/")
    code, out, err = run(title, gateway, "inferred", env={"X2W_XGR_INFERRED": "1"})
    print(out.strip())
    if code != 0 or "failures=0" not in out:
        failures.append(f"inferred run: exit {code}\n{out}\n{err}")
    for what, pattern in {
        "inferred networking slot served and logged": r"xgr-assume IXNetworkingImpl_bf2346b2\.3 IXNetworkingImpl_bf2346b2 slot 3 taken to be XNetworkingGetConnectivityHint",
        "inferred XUser slot served and logged": r"xgr-assume IXUserImpl\.9 IXUserImpl slot 9 taken to be XUserGetId",
        "slot 15 still unmapped": r"xgr-unknown-slot IXNetworkingImpl_bf2346b2 slot 15 args",
    }.items():
        if not re.search(pattern, err):
            failures.append(f"inferred run: log line missing: {what}\n  /{pattern}/")
    code, out, err = run(title, gateway, "strict", env={"X2W_XGR_STRICT": "1"})
    print(out.strip())
    if code != 0 or "failures=0" not in out:
        failures.append(f"strict run: exit {code}\n{out}\n{err}")
    if failures:
        print(err[-6000:] if err else "")
        raise SystemExit("\n".join(failures))
    print("xgr_gateway: fallback objects, unknown and inferred slots (untouched arguments), XUser paths hold")


if __name__ == "__main__":
    main(*sys.argv[1:])
