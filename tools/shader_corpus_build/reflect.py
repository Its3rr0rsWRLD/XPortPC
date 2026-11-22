"""Minimal SPIR-V reflection for the offline pipeline builder (stdlib only). Usage: reflect.py file.spv -> JSON."""
import json, struct, sys

def reflect(path):
    data = open(path, "rb").read()
    w = struct.unpack("<%dI" % (len(data) // 4), data)
    if w[0] != 0x07230203:
        raise ValueError("not spirv")
    i = 5
    types, consts, vars_, dec, mdec, entry = {}, {}, [], {}, {}, []
    caps = set()
    while i < len(w):
        n, op = w[i] >> 16, w[i] & 0xFFFF
        a = w[i + 1:i + n]
        if op == 17: caps.add(a[0])
        elif op == 15: entry.append(a[0])
        elif op in (19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 32, 5341):
            if op in (19, 20, 26, 5341): types[a[0]] = (op, a[1:])
            elif op in (30,): types[a[0]] = (op, a[1:])
            else: types[a[0]] = (op, a[1:])
        elif op in (43, 50): consts[a[1]] = a[2] if len(a) > 2 else 0
        elif op == 59: vars_.append((a[0], a[1], a[2]))
        elif op == 71: dec.setdefault(a[0], {})[a[1]] = a[2:]
        elif op == 72: mdec.setdefault((a[0], a[1]), {})[a[2]] = a[3:]
        i += n

    def strip(t):
        """follow pointer/arrays: returns (base type id, array count)"""
        cnt = 1
        while True:
            op, ar = types[t]
            if op == 32: t = ar[1]
            elif op == 28: cnt *= max(1, consts.get(ar[1], 1)); t = ar[0]
            elif op == 29: cnt *= 16; t = ar[0]
            else: return t, cnt

    def size(t):
        op, ar = types[t]
        if op in (21, 22): return ar[0] // 8
        if op == 20: return 4
        if op == 23: return size(ar[0]) * ar[1]
        if op == 24:
            return ar[1] * 16
        if op == 28:
            st = None
            return consts.get(ar[1], 1) * (dec.get(t, {}).get(6, [size(ar[0])])[0])
        if op == 30:
            end = 0
            for m, mt in enumerate(ar):
                off = mdec.get((t, m), {}).get(35, [0])[0]
                end = max(end, off + size(mt))
            return end
        return 4

    def comp(t):
        op, ar = types[t]
        if op in (23, 24, 28, 29): return comp(ar[0])
        if op == 21: return 'i' if ar[1] else 'u'
        return 'f'

    def locs(t):
        op, ar = types[t]
        if op == 24: return ar[1] * locs(ar[0])
        if op == 28: return consts.get(ar[1], 1) * locs(ar[0])
        if op == 23 and comp(t) != 'f' and False: return 1
        if op == 23 and types[ar[0]][0] == 22 and types[ar[0]][1][0] == 64 and ar[1] > 2: return 2
        return 1

    out = {"models": [], "binds": {}, "push": 0, "vin": {}, "fout": {}, "fin": [], "vout": [], "bad": [], "depth": False, "caps": sorted(caps)}
    # entry execution model is the first word after header of OpEntryPoint; re-parse for models
    i = 5
    while i < len(w):
        n, op = w[i] >> 16, w[i] & 0xFFFF
        if op == 15: out["models"].append(w[i + 1])
        i += n
    for tid, vid, sc in vars_:
        base, cnt = strip(tid)
        d = dec.get(vid, {})
        bop, bar = types[base]
        if sc in (2, 12, 0):
            if 34 not in d or 33 not in d: continue
            s, b = d[34][0], d[33][0]
            bdec = dec.get(base, {})
            if bop == 5341: out["bad"].append("accel"); continue
            if bop == 30:
                t = 7 if (sc == 12 or 3 in bdec) else 6
            elif bop == 26: t = 0
            elif bop == 27: t = 1
            elif bop == 25:
                dim, smp = bar[1], bar[5]
                if dim == 6: out["bad"].append("subpass"); continue
                t = (4 if dim == 5 else 2) if smp == 1 else (5 if dim == 5 else 3)
            else: continue
            k = (s, b)
            old = out["binds"].get(k)
            out["binds"][k] = (t, max(cnt, old[1] if old else 0))
        elif sc == 9:
            out["push"] = max(out["push"], size(base) if bop == 30 else 16)
        elif sc in (1, 3):
            if 11 in d:
                if sc == 3 and d[11][0] == 22: out["depth"] = True
                continue
            if 30 not in d:
                continue
            loc = d[30][0]
            if sc == 1: out["vin"][loc] = comp(base)  # also frag inputs (location list)
            else: out["fout"][loc] = comp(base)
            for e in range(1, locs(base) * cnt):
                (out["vin"] if sc == 1 else out["fout"])[loc + e] = comp(base)
    out["binds"] = [[s, b, t, c] for (s, b), (t, c) in sorted(out["binds"].items())]
    out["vin"] = {str(k): v for k, v in out["vin"].items()}
    out["fout"] = {str(k): v for k, v in out["fout"].items()}
    return out

if __name__ == "__main__":
    print(json.dumps(reflect(sys.argv[1])))
