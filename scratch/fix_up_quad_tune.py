"""Pick (GL order, panel width) for the split quadrature: smallest cost that
still ties out to the independent quad reference across the stress grid."""
import math
import timeit

import numpy as np
from scipy.integrate import quad

SQRT2 = math.sqrt(2.0)
SAT = 40.0
T_TAIL = 9.0


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500.0, 500.0)))


def ref_quad(m, u, tau, s, b=0.0):
    c = u + b
    fr = lambda d: sig((d - c) / tau) * math.exp(-0.5 * ((d - m) / s) ** 2) / (s * math.sqrt(2 * math.pi))
    fl = lambda d: sig((d + c) / tau) * math.exp(-0.5 * ((d - m) / s) ** 2) / (s * math.sqrt(2 * math.pi))
    lo, hi = m - 12 * s, m + 12 * s
    tot = 0.0
    if hi > 0:
        tot += quad(fr, max(lo, 0.0), hi, limit=400, epsabs=1e-14, epsrel=1e-13)[0]
    if lo < 0:
        tot += quad(fl, lo, min(hi, 0.0), limit=400, epsabs=1e-14, epsrel=1e-13)[0]
    return tot


def _normal_mass(a, b):
    if b <= a:
        return 0.0
    if b <= 0.0:
        return 0.5 * (math.erfc(-b / SQRT2) - math.erfc(-a / SQRT2))
    if a >= 0.0:
        return 0.5 * (math.erfc(a / SQRT2) - math.erfc(b / SQRT2))
    return 1.0 - 0.5 * (math.erfc(-a / SQRT2) + math.erfc(b / SQRT2))


def make(order, hmax):
    GL_N, GL_W = np.polynomial.legendre.leggauss(order)

    def seg(lo, hi, beta, a):
        if hi <= lo:
            return 0.0
        half = SAT / beta
        A = min(max(lo, a - half), hi)
        B = max(min(hi, a + half), lo)
        out = _normal_mass(B, hi)
        if B > A:
            h = min(hmax, 1.0 / beta)
            n = max(1, int(math.ceil((B - A) / h)))
            e = np.linspace(A, B, n + 1)
            mid = 0.5 * (e[:-1] + e[1:])[:, None]
            rad = 0.5 * (e[1:] - e[:-1])[:, None]
            t = mid + rad * GL_N[None, :]
            f = sig(beta * (t - a)) * np.exp(-0.5 * t * t) / math.sqrt(2 * math.pi)
            out += float((f * (GL_W[None, :] * rad)).sum())
        return out

    def cand(m, u, tau, s, b=0.0):
        c, beta, t_k = u + b, s / tau, -m / s
        p = 0.0
        if t_k > -T_TAIL:
            p += seg(-T_TAIL, min(t_k, T_TAIL), beta, (-c - m) / s)
        if t_k < T_TAIL:
            p += seg(max(t_k, -T_TAIL), T_TAIL, beta, (c - m) / s)
        return p
    return cand


GRID = [(m, u, tau, s, b)
        for m in (-8.0, -1.0, -0.3, -0.05, -0.004, 0.0, 0.004, 0.05, 0.3, 1.0,
                  8.0, 50.0, -50.0)
        for u in (0.0, 0.2, 2.0, 5.0, 98.0)
        for tau in (0.05, 0.5, 3.8, 11.0)
        for s in (0.02, 0.25, 1.0)
        for b in (0.0, 0.13)]
REF = {g: ref_quad(*g) for g in GRID}

for order in (8, 10, 12, 16):
    for hmax in (0.75, 1.0, 1.5, 2.0, 3.0):
        f = make(order, hmax)
        worst = max(abs(f(*g) - REF[g]) for g in GRID)
        t = timeit.timeit(lambda: f(0.05, 5.0, 3.8, 0.2543), number=1000) / 1000
        print(f"  order={order:3d} hmax={hmax:4.2f}   max err {worst:.2e}"
              f"   {t * 1e6:6.1f} us/call")
