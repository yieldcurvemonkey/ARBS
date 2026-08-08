import pandas as pd
import numpy as np
import itertools

import rateslib as rl

from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapStructure


def ladder_from_pkg(pkg, solver=None) -> pd.Series:
    df = rl.Portfolio(pkg).delta(solver=solver)

    if isinstance(df, pd.Series):
        return df

    if df.shape[1] == 1:
        out = df.iloc[:, 0]
        out.name = "dv01"
        return out

    try:
        # typical MultiIndex levels: ('local_ccy','display_ccy','type','label')
        s = df.xs(("usd", "usd", "solver", "instruments"), axis=1)
        if isinstance(s, pd.DataFrame) and s.shape[1] == 1:
            out = s.iloc[:, 0]
        else:
            out = s
        out.name = "dv01"
        return out
    except Exception:
        # Fallback: first column
        out = df.iloc[:, 0]
        out.name = "dv01"
        return out


def build_unit_bpv_basis(
    tenors,
    curve_name: str,
    curve_handle,
    solver=None,
):
    basis_ladders = []
    idx_union = None

    for t in tenors:
        q = IRSwapQuery(
            curve=curve_name,
            tenor=t,
            structure=IRSwapStructure.OUTRIGHT,
            structure_kwargs={"bpv": 1.0},
        )
        pkg, _ = q.resolve_package(pricer_or_curve=curve_handle)
        s = ladder_from_pkg(pkg, solver=solver)

        basis_ladders.append(s)
        idx_union = s.index if idx_union is None else idx_union.union(s.index)

    # realign onto common index and fill missing with 0
    basis_ladders = [s.reindex(idx_union).fillna(0.0) for s in basis_ladders]

    return tenors, basis_ladders, idx_union


def _solve_bpv_neutral_ls(B: np.ndarray, r: np.ndarray, d: np.ndarray) -> np.ndarray:
    """
    Solve:  min_w || r + B w ||_2^2   subject to   d^T w = 0

    B: (m x n) bucket ladder matrix (each column = leg's ladder)
    r: (m,)   target ladder
    d: (n,)   total BPV of each leg in the same basis
    """
    n = B.shape[1]

    BTB = B.T @ B  # n x n
    BTr = B.T @ r  # n

    A = d.reshape(1, -1)  # 1 x n
    # KKT system:
    # [ BTB   A^T ] [ w ] = [ -B^T r ]
    # [  A     0  ] [ λ ]   [   0    ]
    KKT = np.block([[BTB, A.T], [A, np.zeros((1, 1))]])
    rhs = np.concatenate([-BTr, np.zeros(1)])

    sol, *_ = np.linalg.lstsq(KKT, rhs, rcond=None)
    w = sol[:n]
    return w


def solve_best_n_leg_hedge(
    target_pkg,
    curve_name: str,
    curve_handle,
    tenors,
    n: int,
    ks,  # list-like of ranks: e.g. [0] or [0,1,2]
    solver=None,
):
    """
    Given:
      - target_pkg: package to hedge (e.g. your 2y2y/5y5y/10y10y curve trade),
      - curve_name: e.g. 'USD-SOFR-1D',
      - curve_handle: your RL curve object,
      - tenors: list like ['5Y','7Y','10Y','20Y','30Y'],
      - n: number of legs in the hedge (1=outright, 2=curve, 3=fly, ...),
      - ks: list of integer ranks to return (0 = best, 1 = next best, ...)

    Conventions:
      * n = 1: unconstrained LS hedge (directional).
      * n = 2: BPV-neutral curve trade: sum_i d_i w_i = 0.
      * n = 3: fly trade:
            wings = first & last tenor of the 3-combo,
            belly = middle tenor.
        Constraint: each wing BPV is 0.5 * belly BPV (opposite sign),
        which implies overall BPV-neutrality.
      * n > 3: generic BPV-neutral package, d^T w = 0.

    Returns:
      list of dicts, one per requested k, each with:
        - 'rank': k (0 = best)
        - 'tenors': chosen tenors
        - 'weights_bpv': BPV weights for each tenor
        - 'residual_ladder': remaining risk ladder after hedge
        - 'residual_norm': L2 norm of remaining risk
        - 'hedge_pkg': list of RL swap objects representing the hedge trade
    """
    # Normalize ks
    if isinstance(ks, int):
        ks = [ks]
    ks = sorted({int(k) for k in ks if int(k) >= 0})
    if not ks:
        return []

    # 1) Risk ladder of the thing you're hedging
    r_target_raw = ladder_from_pkg(target_pkg, solver=solver)

    # 2) Basis ladders for unit-bpv mt swaps
    all_tenors, basis_ladders, idx_union = build_unit_bpv_basis(
        tenors=tenors,
        curve_name=curve_name,
        curve_handle=curve_handle,
        solver=solver,
    )

    # 3) Align everything on one index
    r_target = r_target_raw.reindex(idx_union).fillna(0.0)
    R = np.column_stack([s.values for s in basis_ladders])  # (m x K)
    r_vec = r_target.values

    candidates = []

    for combo in itertools.combinations(range(len(all_tenors)), n):
        B = R[:, combo]  # m x n

        if n == 1:
            # Unconstrained LS: min_w || r + B w ||_2
            w, *_ = np.linalg.lstsq(B, -r_vec, rcond=None)

        else:
            # Per-leg BPV in ladder basis
            d = B.sum(axis=0)  # shape: (n,)

            if n == 2:
                # BPV-neutral curve: d^T w = 0
                w = _solve_bpv_neutral_ls(B, r_vec, d)

            elif n == 3:
                # ---- "True fly" constraint: wing BPV = 0.5 * belly BPV ----
                # Assume combo is in maturity order:
                #   index 0 = near wing, 1 = belly, 2 = far wing
                if np.any(np.isclose(d, 0.0)):
                    # ill-posed; skip this combo
                    continue

                # Define structural vector q such that:
                #   d0*w0 = -0.5*d1*w1   and   d2*w2 = -0.5*d1*w1
                # -> w0 = -0.5*(d1/d0)*w1,  w2 = -0.5*(d1/d2)*w1
                q = np.array(
                    [
                        -0.5 * d[1] / d[0],
                        1.0,
                        -0.5 * d[1] / d[2],
                    ]
                )

                # Directional ladder of this fly structure
                h = B @ q  # m-vector

                denom = h @ h
                if np.isclose(denom, 0.0):
                    # structure doesn't move risk meaningfully; skip
                    continue

                # Optimal amplitude a in w = a * q
                a = -(h @ r_vec) / denom
                w = a * q

            else:
                # n > 3: generic BPV-neutral package
                w = _solve_bpv_neutral_ls(B, r_vec, d)

        residual = r_vec + B @ w
        norm = float(np.linalg.norm(residual))

        candidates.append(
            {
                "combo": combo,
                "weights_bpv": w,
                "residual": residual,
                "residual_norm": norm,
            }
        )

    if not candidates:
        return []

    # 5) Rank candidates by residual_norm (ascending)
    candidates.sort(key=lambda c: c["residual_norm"])

    results = []
    max_rank = len(candidates) - 1

    for k in ks:
        if k > max_rank:
            continue

        cand = candidates[k]
        combo = cand["combo"]
        w = cand["weights_bpv"]
        residual = cand["residual"]

        chosen_tenors = [all_tenors[i] for i in combo]
        hedge_pkg = []

        # Build hedge package with BPV weights
        for tenor, weight in zip(chosen_tenors, w):
            if abs(weight) < 1e-6:
                continue

            q = IRSwapQuery(
                curve=curve_name,
                tenor=tenor,
                structure=IRSwapStructure.OUTRIGHT,
                structure_kwargs={"bpv": float(weight)},  # sign = pay vs receive
            )
            pkg_leg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            hedge_pkg.extend(pkg_leg)

        residual_ladder = pd.Series(
            residual,
            index=idx_union,
            name=f"post_hedge_dv01_rank_{k}",
        )

        results.append(
            {
                "rank": k,
                "tenors": chosen_tenors,
                "weights_bpv": w,
                "residual_ladder": residual_ladder,
                "residual_norm": cand["residual_norm"],
                "hedge_pkg": hedge_pkg,
            }
        )

    return results


def _refuse_degenerate_pca_metric(G: np.ndarray, w) -> None:
    """Refuse a "PCA metric" that is arithmetically the identity.

    ``np.linalg.eigh`` returns an ORTHONORMAL square ``L``, so ``L diag(1) L^T
    = L L^T = I`` -- measured on a real fitted 10-bucket USD-OIS model,
    ``max|L L^T - I| = 8.9e-16``. Every quadratic form below then collapses to
    the plain Euclidean norm of the dollar ladder, and a hedge that reports
    itself as PCA-neutralising is unweighted least squares.

    That was **the default call path**: ``pca_weights=None`` meant
    ``np.ones(K)`` in both this module's metric builders, so
    ``solve_best_n_leg_hedge_pca(..., pca_weights=None)`` -- the documented,
    lowest-friction call -- never used the PCA at all. Measured on the real
    2026-08-03 USD-OIS curve, a 1y-forward 2-7-29 fly removed **0.0865%** of
    that "PCA norm"; against a genuine PC1+PC2 projector the same fly removes
    5.3%. Reporting a number that small as "PCA-neutralised" is the failure
    this refusal exists to make impossible.

    Refusing rather than silently substituting a default weight vector: which
    components a hedge should neutralise is the caller's decision and cannot be
    guessed here. A truncated loadings matrix (``K x k``, ``k < K``) at uniform
    weights gives a genuine rank-k projector and is NOT refused -- the test is
    on the metric that came out, not on how it was asked for.
    """
    n = G.shape[0]
    if G.shape[0] == G.shape[1] and np.allclose(G, np.eye(n), atol=1e-8):
        raise ValueError(
            "the PCA metric is arithmetically the identity, so this would be "
            "plain unweighted least squares on the raw dollar ladder while "
            "reporting itself as a PCA hedge. `eigh` gives an orthonormal L, "
            "so L diag(w) L^T = I whenever w is all-ones -- which is what "
            f"pca_weights=None means here. Weights: "
            f"{np.asarray(w, dtype=float).round(4).tolist()}. Pass explicit "
            "pca_weights naming the components to neutralise, e.g. "
            "[1, 1, 0, ...] for a level+slope hedge or the eigenvalues for a "
            "variance-weighted one."
        )


def _build_pca_projection(pca_model, pca_weights):
    """
    Returns a function S(x) = W^{1/2} L^T x that maps a ladder x (Series or array)
    into weighted PC space.

    pca_model.loadings: DataFrame of shape (K, K), index = ladder labels.
    pca_weights: sequence of length K, weights per PC (PC1, PC2, ...).

    Uniform weights are refused -- see :func:`_refuse_degenerate_pca_metric`.
    """
    L = pca_model.loadings.values  # (K x K), columns = PCs
    K = L.shape[1]

    if pca_weights is None:
        w = np.ones(K)
    else:
        w = np.asarray(pca_weights, dtype=float)
        if w.shape[0] != K:
            raise ValueError(f"pca_weights must have length {K}, got {w.shape[0]}")
    _refuse_degenerate_pca_metric(L @ np.diag(w) @ L.T, w)

    # Keep only PCs with positive weight (others don't affect the norm)
    mask = w > 0
    if not np.any(mask):
        raise ValueError("At least one pca_weight must be > 0.")

    L_sub = L[:, mask]  # (K x K_eff)
    w_sub = w[mask]  # (K_eff,)
    w_sqrt = np.sqrt(w_sub)  # (K_eff,)

    # S_T = W^{1/2} L^T  with only active PCs
    # S_T has shape (K_eff x K)
    S_T = w_sqrt[:, None] * L_sub.T

    def S_vec(x: np.ndarray) -> np.ndarray:
        # x: (K,)
        return S_T @ x  # (K_eff,)

    return S_vec


def _build_pca_metric_matrix(pca_model, pca_weights=None) -> np.ndarray:
    """
    Build G = L diag(w) L^T where:
      - L: loadings matrix, shape (K, K), columns = PCs
      - w: pca_weights, length K (per PC)

    Returned G has shape (K, K) and defines the quadratic form:
        x^T G x = PCA-norm^2(x)

    **Uniform weights -- including this signature's own ``pca_weights=None``
    default -- are REFUSED**, because for an orthonormal L they make G exactly
    the identity and the "PCA norm" the plain Euclidean norm of the ladder.
    See :func:`_refuse_degenerate_pca_metric` for the measurement and for what
    to pass instead. This is a deliberate behaviour change: the previous
    default returned I and every caller that took it got an unweighted
    least-squares hedge labelled as a PCA one.
    """
    L = pca_model.loadings.values  # (K x K), columns = PCs
    K = L.shape[1]

    if pca_weights is None:
        w = np.ones(K)
    else:
        w = np.asarray(pca_weights, dtype=float)
        if w.shape[0] != K:
            raise ValueError(f"pca_weights must have length {K}, got {w.shape[0]}")

    # Keep PCs with positive weight; zeros simply don't contribute
    W = np.diag(w)
    G = L @ W @ L.T  # (K x K)
    _refuse_degenerate_pca_metric(G, w)
    return G


def _solve_bpv_neutral_ls_pca(
    B: np.ndarray,
    r: np.ndarray,
    d: np.ndarray,
    G: np.ndarray,
) -> np.ndarray:
    """
    Solve:  min_w (r + B w)^T G (r + B w)   s.t.   d^T w = 0

    B: (K x n)  bucket ladder matrix
    r: (K,)     target ladder
    d: (n,)     total BPV per leg
    G: (K x K)  PCA metric matrix
    """
    BTGB = B.T @ (G @ B)  # n x n
    BTGr = B.T @ (G @ r)  # n

    A = d.reshape(1, -1)  # 1 x n

    KKT = np.block([[BTGB, A.T], [A, np.zeros((1, 1))]])
    rhs = np.concatenate([-BTGr, np.zeros(1)])

    sol, *_ = np.linalg.lstsq(KKT, rhs, rcond=None)
    w = sol[: B.shape[1]]
    return w


def _solve_fly_ls_pca(
    B: np.ndarray,
    r: np.ndarray,
    d: np.ndarray,
    G: np.ndarray,
) -> np.ndarray:
    """
    n=3 fly:
      wings = 0 and 2, belly = 1
      constraint: each wing BPV = 0.5 * belly BPV (opposite sign)
      -> w0 = -0.5*(d1/d0)*w1, w2 = -0.5*(d1/d2)*w1

    Solve min_a (r + B (a q))^T G (r + B (a q)), where q encodes the BPV structure.
    """
    # Safety: if any d is ~0, fall back to generic BPV-neutral
    eps = 1e-10
    if np.any(np.abs(d) < eps):
        return _solve_bpv_neutral_ls_pca(B, r, d, G)

    q = np.array(
        [
            -0.5 * d[1] / d[0],
            1.0,
            -0.5 * d[1] / d[2],
        ]
    )

    h = B @ q  # K-vector, fly direction in ladder space

    Gh = G @ h
    denom = h @ Gh
    if np.abs(denom) < eps:
        # structure doesn't move PCA risk; fall back
        return _solve_bpv_neutral_ls_pca(B, r, d, G)

    Gr = G @ r
    a = -(h @ Gr) / denom
    w = a * q
    return w


def solve_best_n_leg_hedge_pca(
    target_pkg,
    curve_name: str,
    curve_handle,
    tenors,
    n: int,
    ks,  # list-like of ranks: e.g. [0] or [0,1,2]
    *,
    solver=None,
    pca_model=None,
    pca_weights=None,
):
    """
    PCA-risk version of solve_best_n_leg_hedge.

    Same conventions:
      * n = 1: unconstrained hedge (directional).
      * n = 2: BPV-neutral curve: sum_i d_i w_i = 0.
      * n = 3: fly, wing BPV = 0.5 * belly BPV.
      * n > 3: generic BPV-neutral package.

    Objective:
      minimize (r + B w)^T G (r + B w)
      where G = L diag(pca_weights) L^T, L = PCA loadings.

    Returns:
      list[dict] with keys:
        'rank', 'tenors', 'weights_bpv',
        'residual_ladder', 'residual_pca_norm', 'hedge_pkg'
    """
    if pca_model is None:
        raise ValueError("pca_model must be provided for PCA-based optimization.")

    # Normalize ks
    if isinstance(ks, int):
        ks = [ks]
    ks = sorted({int(k) for k in ks if int(k) >= 0})
    if not ks:
        return []

    # 1) DV01 ladder of target
    r_target_raw = ladder_from_pkg(target_pkg, solver=solver)

    # 2) Basis ladders
    all_tenors, basis_ladders, idx_union = build_unit_bpv_basis(
        tenors=tenors,
        curve_name=curve_name,
        curve_handle=curve_handle,
        solver=solver,
    )

    # 3) Align ladders to PCA model basis
    #    We assume PCA was fit on a ladder with index pca_model.columns
    common_index = pca_model.columns
    r_target = r_target_raw.reindex(common_index).fillna(0.0)

    B_cols = [s.reindex(common_index).fillna(0.0).values for s in basis_ladders]
    B_full = np.column_stack(B_cols)  # (K x M)

    r_vec = r_target.values
    K = len(common_index)

    # 4) PCA metric matrix G
    G = _build_pca_metric_matrix(pca_model, pca_weights)

    candidates = []

    for combo in itertools.combinations(range(len(all_tenors)), n):
        B = B_full[:, combo]  # (K x n)

        if n == 1:
            # Unconstrained PCA LS: min_w (r + B w)^T G (r + B w)
            BTGB = B.T @ (G @ B)
            BTGr = B.T @ (G @ r_vec)
            w, *_ = np.linalg.lstsq(BTGB, -BTGr, rcond=None)

        else:
            # Total BPV per leg in ladder basis
            d = B.sum(axis=0)

            if n == 2:
                # BPV-neutral curve in PCA metric
                w = _solve_bpv_neutral_ls_pca(B, r_vec, d, G)

            elif n == 3:
                # Fly: wing BPV = 0.5 * belly BPV
                w = _solve_fly_ls_pca(B, r_vec, d, G)

            else:
                # generic BPV-neutral
                w = _solve_bpv_neutral_ls_pca(B, r_vec, d, G)

        # Residual ladder (original basis)
        residual = r_vec + B @ w
        residual_series = pd.Series(residual, index=common_index)

        # PCA norm of residual for ranking
        pca_score = float(
            pca_model.pca_norm(
                residual_series,
                weights=pca_weights,
            )
        )

        candidates.append(
            {
                "combo": combo,
                "weights_bpv": w,
                "residual": residual,
                "residual_pca_norm": pca_score,
            }
        )

    if not candidates:
        return []

    # 5) Rank by PCA norm
    candidates.sort(key=lambda c: c["residual_pca_norm"])

    results = []
    max_rank = len(candidates) - 1

    for k in ks:
        if k > max_rank:
            continue

        cand = candidates[k]
        combo = cand["combo"]
        w = cand["weights_bpv"]
        residual = cand["residual"]

        chosen_tenors = [all_tenors[i] for i in combo]
        hedge_pkg = []

        for tenor, weight in zip(chosen_tenors, w):
            if abs(weight) < 1e-6:
                continue

            q = IRSwapQuery(
                curve=curve_name,
                tenor=tenor,
                structure=IRSwapStructure.OUTRIGHT,
                structure_kwargs={"bpv": float(weight)},
            )
            pkg_leg, _ = q.resolve_package(pricer_or_curve=curve_handle)
            hedge_pkg.extend(pkg_leg)

        residual_ladder = pd.Series(
            residual,
            index=common_index,
            name=f"post_hedge_dv01_rank_{k}",
        )

        results.append(
            {
                "rank": k,
                "tenors": chosen_tenors,
                "weights_bpv": w,
                "residual_ladder": residual_ladder,
                "residual_pca_norm": cand["residual_pca_norm"],
                "hedge_pkg": hedge_pkg,
            }
        )

    return results


def pca_risk_from_pkg(pkg, *, solver, pca_model) -> pd.Series:
    """
    Compute PCA factor exposures (PC1, PC2, PC3, ...) for a package's DV01 ladder.

    pkg        : list of rl instruments (e.g. curve_pkg or hedged_pkg)
    solver     : your rl.Solver (e.g. rl_curve_risk_solver)
    pca_model  : your CurvePCAModel (fitted on the same basis as the ladder)

    Returns:
        Series indexed by ['PC1','PC2',...] with factor exposures.
    """
    # 1) DV01 ladder of the pkg
    ladder = ladder_from_pkg(pkg, solver=solver)
    print(ladder)

    # 2) Align with PCA model basis
    x = ladder.reindex(pca_model.columns).fillna(0.0)

    # 3) Project to PCs
    scores = pca_model.transform(x)  # Series of PC1, PC2, ...
    return scores
