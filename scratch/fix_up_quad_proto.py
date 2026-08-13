"""Prototype + validation of the split-at-the-kink quadrature for p_marginalised.

Reference is scipy.integrate.quad run SEPARATELY on each smooth piece (so the
reference itself never sees the kink), tolerance 1e-13. The reference is first
validated on the u = 0 case, where the integrand is smooth on the whole line
and the existing 40-node Gauss-Hermite is known to be right -- if the reference
disagrees there, the reference is what is broken.
"""
import math

import numpy as np
from scipy.integrate import quad

SQRT2 = math.sqrt(2.0)
GL_N, GL_W = np.polynomial.legendre.leggauss(16)
GH_N, GH_W = np.polynomial.hermite.hermgauss(40)
SQRT_PI = math.sqrt(math.pi)
T_TAIL = 9.0
SAT = 40.0          # |sigma(x)| within 4.2e-18 of {0, 1} beyond this


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500.0, 500.0)))


# ---------------------------------------------------------------- reference
def ref_quad(m, u, tau, s, b=0.0):
    c = u + b

    def f_right(d):
        return sig((d - c) / tau) * math.exp(-0.5 * ((d - m) / s) ** 2) / (
            s * math.sqrt(2 * math.pi))

    def f_left(d):
        return sig((d + c) / tau) * math.exp(-0.5 * ((d - m) / s) ** 2) / (
            s * math.sqrt(2 * math.pi))

    lo, hi = m - 12 * s, m + 12 * s
    tot = 0.0
    if hi > 0:
        tot += quad(f_right, max(lo, 0.0), hi, limit=400,
                    epsabs=1e-14, epsrel=1e-13)[0]
    if lo < 0:
        tot += quad(f_left, lo, min(hi, 0.0), limit=400,
                    epsabs=1e-14, epsrel=1e-13)[0]
    return tot


def gh40(m, u, tau, s, b=0.0):
    d = m + SQRT2 * s * GH_N
    e = np.where(d >= 0, d - (u + b), d + (u + b))
    return float(np.dot(GH_W, sig(e / tau)) / SQRT_PI)


# ---------------------------------------------------------------- candidate
def _normal_mass(a, b):
    if b <= a:
        return 0.0
    if b <= 0.0:
        return 0.5 * (math.erfc(-b / SQRT2) - math.erfc(-a / SQRT2))
    if a >= 0.0:
        return 0.5 * (math.erfc(a / SQRT2) - math.erfc(b / SQRT2))
    return 1.0 - 0.5 * (math.erfc(-a / SQRT2) + math.erfc(b / SQRT2))


def _segment(lo, hi, beta, a, hmax):
    """int_lo^hi sigma(beta*(t - a)) phi(t) dt, t in standard-normal units."""
    if hi <= lo:
        return 0.0
    half = SAT / beta
    A = min(max(lo, a - half), hi)
    B = max(min(hi, a + half), lo)
    out = _normal_mass(B, hi)                      # sigma == 1 to 4e-18
    if B > A:
        h = min(hmax, 1.0 / beta)
        n = max(1, int(math.ceil((B - A) / h)))
        edges = np.linspace(A, B, n + 1)
        mid = 0.5 * (edges[:-1] + edges[1:])[:, None]
        rad = 0.5 * (edges[1:] - edges[:-1])[:, None]
        t = mid + rad * GL_N[None, :]
        f = sig(beta * (t - a)) * np.exp(-0.5 * t * t) / math.sqrt(2 * math.pi)
        out += float((f * (GL_W[None, :] * rad)).sum())
    return out


def cand(m, u, tau, s, b=0.0, hmax=1.0):
    c = u + b
    beta = s / tau
    t_k = -m / s
    p = 0.0
    if t_k > -T_TAIL:                              # left branch, d < 0
        p += _segment(-T_TAIL, min(t_k, T_TAIL), beta, (-c - m) / s, hmax)
    if t_k < T_TAIL:                               # right branch, d >= 0
        p += _segment(max(t_k, -T_TAIL), T_TAIL, beta, (c - m) / s, hmax)
    return p


# ---------------------------------------------------------------- checks
print("== reference validated on the SMOOTH case (u = 0): quad vs GH-40 ==")
worst = 0.0
for m in (-3.0, -0.3, 0.0, 0.05, 1.0, 8.0):
    for tau in (0.5, 3.8):
        for s in (0.05, 0.25, 1.0):
            r, g = ref_quad(m, 0.0, tau, s), gh40(m, 0.0, tau, s)
            worst = max(worst, abs(r - g))
print(f"   max |quad - GH40| on the smooth case = {worst:.3e}  (must be ~1e-12)")

print("\n== candidate vs reference on a stress grid ==")
for hmax in (1.0, 2.0, 3.0):
    worst, arg, ncalls = 0.0, None, 0
    for m in (-8.0, -1.0, -0.3, -0.05, -0.004, 0.0, 0.004, 0.05, 0.3, 1.0, 8.0,
              50.0, -50.0):
        for u in (0.0, 0.2, 2.0, 5.0, 98.0):
            for tau in (0.05, 0.5, 3.8, 11.0):
                for s in (0.02, 0.25, 1.0):
                    for b in (0.0, 0.13):
                        r = ref_quad(m, u, tau, s, b)
                        v = cand(m, u, tau, s, b, hmax=hmax)
                        ncalls += 1
                        if abs(v - r) > worst:
                            worst, arg = abs(v - r), (m, u, tau, s, b)
    print(f"   hmax={hmax}: max |cand - ref| = {worst:.3e} over {ncalls} points"
          f"   worst at (m,u,tau,s,b)={arg}")

print("\n== same grid, the CURRENT GH-40 ==")
worst, arg = 0.0, None
for m in (-8.0, -1.0, -0.3, -0.05, -0.004, 0.0, 0.004, 0.05, 0.3, 1.0, 8.0,
          50.0, -50.0):
    for u in (0.0, 0.2, 2.0, 5.0, 98.0):
        for tau in (0.05, 0.5, 3.8, 11.0):
            for s in (0.02, 0.25, 1.0):
                for b in (0.0, 0.13):
                    r = ref_quad(m, u, tau, s, b)
                    v = gh40(m, u, tau, s, b)
                    if abs(v - r) > worst:
                        worst, arg = abs(v - r), (m, u, tau, s, b)
print(f"   max |GH40 - ref| = {worst:.3e}   worst at (m,u,tau,s,b)={arg}")

print("\n== extreme tau/s ratios (robustness, not the live regime) ==")
for (m, u, tau, s) in ((0.05, 5.0, 1e-4, 1.0), (0.0, 0.001, 1e-3, 1.0),
                       (2.0, 2.0, 1e-6, 0.5), (0.1, 3.0, 1e3, 0.01),
                       (0.0, 0.0, 1e-6, 1.0), (1e-9, 5.0, 3.8, 1e-9)):
    r, v = ref_quad(m, u, tau, s), cand(m, u, tau, s)
    print(f"   m={m:<8g} u={u:<7g} tau={tau:<8g} s={s:<8g}  cand={v:.12f}"
          f"  ref={r:.12f}  err={v - r:+.2e}")

print("\n== timing ==")
import timeit
t = timeit.timeit(lambda: cand(0.05, 5.0, 3.8, 0.2543), number=2000) / 2000
print(f"   candidate  {t * 1e6:8.1f} us/call")
t = timeit.timeit(lambda: gh40(0.05, 5.0, 3.8, 0.2543), number=2000) / 2000
print(f"   GH-40      {t * 1e6:8.1f} us/call")
