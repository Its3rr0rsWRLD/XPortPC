# bcpack-rs by Ahmet Dedeler (https://github.com/Ahmet-Dedeler, https://ahmetdedeler.com)
# Source: https://github.com/Ahmet-Dedeler/bcpack-rs
# Revision: 5bf5cc56ed56f1ababf1f9592300bd182ff90bd8
# SPDX-License-Identifier: MIT OR Apache-2.0
# If you copy, vendor or port this file, keep this header and credit bcpack-rs in your README.
"""MDU entropy layer extracted from bcpack-rs; see README.md for provenance.

Xbox2Windows modification: bounded virtual-zero restoration on fragment flush.
"""
from .bcpack_tables import BASE_TABLE, FREQ_TABLE, RF_TABLE, RN_TABLE, RS_TABLE

L = 1 << 24
LEGAL = (L, L >> 8, L >> 16)
FEED_WINDOW = 8

# BC1 lane layout: alphabet_bits = symbol width - 1 (the Verilog `alphabet_bits` input)
BC1_ALPHABET_BITS = (7, 7, 4, 5, 4, 4, 5, 4, 7, 7, 7, 7)
BC1_ENDPOINT_WIDTHS = (5, 6, 5, 5, 6, 5)   # lanes 2..7 = R0 G0 B0 R1 G1 B1

IDLE, HDR0, HDR1, HDR2, PROC, DRAIN = range(6)


class BCPackError(Exception):
    pass


# ---------------------------------------------------------------------------
# Model (mdu_minirans.v inverse / forward paths)
# ---------------------------------------------------------------------------
class Model:
    def __init__(self, eab, q):
        self.eab, self.q = eab, q
        self.base = BASE_TABLE[eab][q]
        self.freq = FREQ_TABLE[eab][q]
        self.rf = RF_TABLE[eab][q]
        self.rs = RS_TABLE[eab][q]
        self.rn = RN_TABLE[eab][q]
        self.nseg = eab + 2           # segment k is enabled iff eab >= k - 1

    def inverse(self, cf):
        """Symbol for the low 16 state bits: comparator chain, then reciprocal divide."""
        b = self.base
        seg = 0
        for k in range(self.nseg - 1, 0, -1):
            if cf >= b[k]:
                seg = k
                break
        base_x = 0 if seg == 0 else 1 << (seg - 1)
        dist = ((cf - b[seg]) + self.rn[seg]) & 0xFFFF
        steps = (((dist * self.rf[seg]) & 0xFFFFFFFF) >> 15 >> self.rs[seg]) & 0x1FF
        return (base_x + steps) & 0x1FF

    def forward(self, sym):
        """(freq, cumulative freq) of sym; slot 0 is reserved (cf 0 -> f-1, 1)."""
        seg = sym.bit_length()
        st = 0 if seg == 0 else 1 << (seg - 1)
        fa = self.freq[seg]
        cfa = (self.base[seg] + fa * (sym - st)) & 0xFFFF
        if cfa == 0:
            return (fa - 1) & 0xFFFF, 1
        return fa, cfa


_MODELS = {}


def model(eab, q):
    m = _MODELS.get((eab, q))
    if m is None:
        m = _MODELS[(eab, q)] = Model(eab, q)
    return m


# ---------------------------------------------------------------------------
# Cycle-level multi-lane decoder
# ---------------------------------------------------------------------------
class Lane:
    __slots__ = ("idx", "ab", "target", "state", "ib", "ib_full", "sym", "sym_full", "in_rem",
                 "out_rem", "p0", "p1", "hdr3", "flush", "q", "eab", "model", "done", "go",
                 "stall", "syms", "nbytes", "final", "frags", "virtual_zeros")

    def __init__(self, idx, ab, target):
        self.idx, self.ab, self.target = idx, ab, target
        self.state = IDLE
        self.ib = 0
        self.ib_full = False
        self.sym = 0
        self.sym_full = False
        self.in_rem = self.out_rem = 0
        self.p0 = self.p1 = 0
        self.hdr3 = self.flush = False
        self.q = self.eab = 0
        self.model = None
        self.done = False
        self.go = True
        self.stall = False
        self.syms = []
        self.nbytes = 0
        self.final = None
        self.frags = []        # (header byte, payload budget)
        self.virtual_zeros = 0

    def need_byte(self):
        if self.ib_full:
            return False
        if self.state in (HDR0, HDR1, HDR2):
            return True
        return self.state == PROC and self.in_rem > 0

    def forward_state(self, x, sym):
        f, cf = self.model.forward(sym)
        return (f * (x >> 16) + (x & 0xFFFF) - cf) & 0xFFFFFFFF


def decode_lanes(data, alphabet_bits, targets, window=FEED_WINDOW, source=None):
    """Run the lanes over one shared byte stream.

    data: the chunk bytes (trailing zero padding allowed). source: optional
    callable(lane_index) -> next byte, used by the synthetic encoder to learn
    the interleave order (then `data` is ignored and the order is recorded).
    Returns dict(syms, consumed, cycles, lanes, order). Raises BCPackError
    unless every lane finished with a legal end state.
    """
    n = len(alphabet_bits)
    lanes = [Lane(i, alphabet_bits[i], targets[i]) for i in range(n)]
    slots = [False] * n
    pos = 0
    end = len(data) if source is None else 1 << 62
    order = []
    cycle = 0
    max_cycles = 64 * (sum(targets) + (len(data) if source is None else 0)) + 1000
    last_prog, last_change = None, 0
    while cycle < max_cycles:
        # phase 0: forward update, byte feed (lane order, <= window per clock), symbol hand-off
        served = 0
        for ln in lanes:
            sym_ready = not slots[ln.idx]
            blocked_out = ln.sym_full and not sym_ready
            need = ln.need_byte()
            req = need and not blocked_out
            valid = req and served < window and pos < end
            ln.stall = (need and not valid) or blocked_out
            if ln.stall:
                continue
            if ln.state in (PROC, DRAIN):
                ln.p0 = ln.forward_state(ln.p1, ln.sym) if ln.sym_full else ln.p1
            if valid:
                if source is None:
                    ln.ib = data[pos]
                else:
                    ln.ib = source(ln.idx)
                    order.append(ln.idx)
                pos += 1
                served += 1
                ln.nbytes += 1
                ln.ib_full = True
            if ln.sym_full:
                slots[ln.idx] = True
                ln.syms.append(ln.sym)
                ln.sym_full = False
        # phase 1: header FSM, renormalisation, symbol decode
        for ln in lanes:
            if ln.stall:
                continue
            st = ln.state
            if st == IDLE:
                if ln.go:
                    ln.go = False
                    ln.state = HDR0
                    ln.out_rem = ln.target
                    ln.p0 = ln.p1 = 0
            elif st == HDR0:
                if ln.ib_full:
                    b = ln.ib
                    ln.ib_full = False
                    ln.in_rem = 0
                    ln.state = HDR1
                    ln.virtual_zeros = 0
                    ln.q = b & 15
                    ln.hdr3 = bool(b & 0x20)
                    ln.flush = bool(b & 0x10)
                    e = ln.ab - (b >> 6)
                    if e < 0:
                        e &= 15
                    ln.eab = e if e < 10 else 9
                    ln.frags.append([b, None])
                    if ln.eab > 8:
                        raise BCPackError("lane %d: header selects alphabet index %d" % (ln.idx, ln.eab))
            elif st == HDR1:
                if ln.ib_full:
                    ln.ib_full = False
                    ln.model = model(ln.eab, ln.q)
                    if ln.hdr3:
                        ln.in_rem = ln.ib
                        ln.state = HDR2
                    else:
                        ln.in_rem = ln.ib + 1
                        ln.state = PROC
                        ln.frags[-1][1] = ln.in_rem
            elif st == HDR2:
                if ln.ib_full:
                    ln.ib_full = False
                    ln.in_rem = ((ln.ib << 8) | (ln.in_rem & 0xFF)) + 257
                    ln.frags[-1][1] = ln.in_rem
                    ln.state = PROC
            else:  # PROC or DRAIN
                will = st == PROC and ln.p0 < L and ln.in_rem > 0 and ln.ib_full
                x = (((ln.p0 & 0xFFFFFF) << 8) | ln.ib) if will else ln.p0
                # A flushed fragment may omit up to two low zero bytes. Restore
                # them when its physical budget is exhausted, before decoding.
                remaining = ln.in_rem - int(will)
                if ln.flush and remaining == 0:
                    while 0 < x < L and ln.virtual_zeros < 2:
                        x <<= 8
                        ln.virtual_zeros += 1
                nsf = x > L and ln.out_rem > 0
                new_out = ln.out_rem - 1 if nsf else ln.out_rem
                ln.p1 = x
                ln.out_rem = new_out
                if nsf:
                    ln.sym = ln.model.inverse(x & 0xFFFF)
                ln.sym_full = nsf
                if st == PROC:
                    if will:
                        ln.in_rem -= 1
                        ln.ib_full = False
                    if ln.in_rem == 0:
                        if new_out > 0:
                            if x == L:
                                ln.state = HDR0
                                if ln.flush:
                                    ln.p1 = 0
                            else:
                                ln.state = DRAIN
                        else:
                            ln.done = True
                            ln.state = IDLE
                            ln.final = ln.forward_state(x, ln.sym) if nsf else x
                elif x <= L:
                    if new_out > 0:
                        # A completed flushed fragment must return to the
                        # rANS home state. Merely being below L could silently
                        # accept a damaged/short fragment, then discard the
                        # invalid state when the next header resets the lane.
                        if ln.flush and x != L:
                            raise BCPackError(
                                "lane %d: flushed fragment did not return to its home state" % ln.idx)
                        ln.state = HDR0
                        if ln.flush:
                            ln.p0 = ln.p1 = 0
                    else:
                        ln.done = True
                        ln.state = IDLE
                        ln.final = ln.forward_state(x, ln.sym) if nsf else x
        # lockstep symbol vector: released when every still-active lane has a symbol
        active = [i for i in range(n) if not (lanes[i].done and not lanes[i].sym_full and not slots[i])]
        if any(slots) and all(slots[i] for i in active):
            slots = [False] * n
        cycle += 1
        if all(ln.done and not ln.sym_full for ln in lanes):
            bad = [ln.idx for ln in lanes if ln.final not in LEGAL]
            if bad:
                raise BCPackError("lanes %s ended in an illegal state" % bad)
            return dict(syms=[ln.syms for ln in lanes], consumed=pos, cycles=cycle, order=order,
                        lanes=[dict(nbytes=ln.nbytes, final=ln.final, frags=ln.frags) for ln in lanes])
        prog = (pos, sum(len(ln.syms) for ln in lanes), sum(ln.state for ln in lanes))
        if prog != last_prog:
            last_prog, last_change = prog, cycle
        elif cycle - last_change > 64:
            raise BCPackError("no progress (stream truncated or not BCPack BC1) at byte %d" % pos)
    raise BCPackError("cycle limit reached")
