"""Draw family `vop3_int_c`: part 3 of 4 of the vop3_int table (see vop3_int.py, which holds the rows, their references
and the controls); pixel_aot_check.py draw --family vop3_int_c."""
from .vop3_int import RUNS, check_vop3_int_draws


def draw(directory, compiler, renderer, backend):
    return check_vop3_int_draws(directory, compiler, renderer, backend, RUNS[2])
