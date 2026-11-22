r"""The form registry. A family module in forms/ registers each instruction form it lowers with @form:

    @form(r"v_foo_f32(?:_e32|_e64)? (v\d+), ([^,]+)")
    def foo(st, i, m):
        ...

The pattern must match the whole instruction text. `when`, if given, is a further condition on the state and the match;
when it fails the search goes on as if the pattern had not matched. A handler lowers the instruction at index i through
st (lowering.Lowering), raises ValueError to refuse it, and returns nothing.

Forms are tried in the order of their modules' names, then in the order a module defines them. Patterns of different
modules must not match the same text (claimants() finds those that do, and the pixel_aot checks assert there is at most
one for every instruction they lower), so the order between modules never decides which form lowers an instruction.
"""
import re

FORMS = []  # (family module, compiled pattern, when, handler)
# Checks lower() runs on every instruction before its form, for state a form leaves for later instructions (the binary16
# rounding mode of forms/sopk.py). A guard raises ValueError to refuse the instruction.
GUARDS = []


def form(pattern, *, when=None):
    def register(handler):
        FORMS.append((handler.__module__.rsplit(".", 1)[-1], re.compile(pattern), when, handler))
        return handler
    return register


def dispatch(st, i, line):
    for _, pattern, when, handler in FORMS:
        if (m := pattern.fullmatch(line)) and (when is None or when(st, m)):
            handler(st, i, m)
            return
    raise ValueError(f"Unsupported instruction {i}: {line}")


def claimants(line):
    """The family modules with a form whose pattern matches the instruction text, ignoring `when`."""
    return sorted({family for family, pattern, _, _ in FORMS if pattern.fullmatch(line)})
