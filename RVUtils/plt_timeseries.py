# ABOUTME: Time series plotting utilities
# ABOUTME: Matplotlib helpers for visualizing price series and spreads
import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from RVUtils.mean_reversion import simulate_mean_reversion_ou


def make_secondary_axis_plot(*, ylabel_left=None, ylabel_right=None, title=None, engine: str = "matplotlib"):

    if engine not in ("matplotlib", "plotly"):
        raise ValueError("engine must be 'matplotlib' or 'plotly'")

    if engine == "plotly":
        try:
            import plotly.graph_objects as go
        except Exception as e:
            raise ImportError("Plotly is required for engine='plotly' (pip install plotly).") from e

    # --- Figure / axes bootstrap ---
    if engine == "matplotlib":
        fig, ax_left = plt.subplots()
        fig.subplots_adjust(right=0.75)
    else:
        fig = go.Figure()
        ax_left = None  # Plotly doesn't expose Axes objects
        # base y-axis (left)
        fig.update_layout(
            title=title or None,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
            margin=dict(l=60, r=120, t=60, b=40),
        )
        # Give a default yaxis config; color/title set when first left trace is added
        fig.update_yaxes(title_text=ylabel_left or None)

    # Matplotlib cosmetics
    if engine == "matplotlib":
        if title:
            ax_left.set_title(title)
        if ylabel_left:
            ax_left.set_ylabel(ylabel_left)

    colors = plt.rcParams.get("axes.prop_cycle", None)
    colors = (colors.by_key().get("color", []) if colors is not None else []) or [f"C{i}" for i in range(10)]

    state = {
        "left_lines": [],  # (mpl) list of main left line handles
        "right_lines": [],  # (mpl) list of main right line handles
        "right_axes": [],  # (mpl) right axes OR (plotly) axis ids [2,3,...]
        "color_idx": 0,
        "left_color": None,
        "series_meta": [],  # {line/trace_idx, label, last_dt, last_val, ...}
        "indicator_lines": [],  # (mpl) indicator handles OR (plotly) trace idxs
        "ou_meta": [],  # strings for OU info
        "hidden_meta": [],  # [{label, last_dt, last_val, ...}] for hide=True indicators
        "suppress_main_last_labels": set(),
        "engine": engine,
        "plotly_info_traces_added": False,  # guard for legend() ghost items
    }

    # ---------- utils ----------
    def _next_color():
        c = colors[state["color_idx"] % len(colors)]
        state["color_idx"] += 1
        return c

    def _stringify_name(n):
        if n is None:
            return "series"
        if isinstance(n, tuple):
            return " ".join(map(str, n))
        return str(n)

    def _fmt_dt(ts):
        ts = pd.Timestamp(ts)
        return ts.strftime("%Y-%m-%d") if ts.time() == datetime.time(0, 0, 0) else ts.isoformat(sep=" ")

    # Create a new "right" axis
    def _new_right_axis():
        if state["engine"] == "matplotlib":
            idx = len(state["right_axes"])
            ax = ax_left.twinx()
            ax.set_frame_on(True)
            ax.patch.set_visible(False)

            # ---- dynamic spacing between secondary right axes (in points) ----
            GAP_PT = 28  # horizontal gap between adjacent right spines, ~0.39 in at 72 pt/in
            gap_in = GAP_PT / 72.0

            # Convert physical gap to "axes" units for spine positioning
            fig_w_in = fig.get_figwidth()
            ax_bbox = ax_left.get_position()  # in figure-fraction coords
            ax_w_in = ax_bbox.width * fig_w_in
            step_axes_units = gap_in / max(ax_w_in, 1e-6)

            offset = 1.0 + step_axes_units * idx
            ax.spines["right"].set_position(("axes", offset))
            ax.spines["right"].set_zorder(10 + idx)

            # ---- ensure there's enough figure right margin for all added axes ----
            # Reserve space for: (i) all inter-axis gaps, (ii) tick labels & y-label area
            LABEL_AREA_IN = 0.35  # base allowance for ticks/label on the outermost axis
            reserve_in = gap_in * (idx + 1) + LABEL_AREA_IN
            new_right_frac = 1.0 - min(0.45, reserve_in / fig_w_in)  # don't shrink past 55% width
            # only tighten if needed (smaller "right" means larger outer margin)
            cur = fig.subplotpars.right
            if new_right_frac < cur:
                fig.subplots_adjust(right=new_right_frac)

            # Progressive padding so tick labels/ylabel don't collide
            ax.tick_params(axis="y", which="both", pad=2 + 6 * idx)
            ax.yaxis.labelpad = 10 + 6 * idx

            state["right_axes"].append(ax)
            return ax

        else:
            # --- inside _new_right_axis(), Plotly branch ONLY ---
            axis_idx = len(state["right_axes"]) + 2  # y2, y3, ...
            axis_name = f"yaxis{axis_idx}"

            # positions for the stacked right axes
            pos = max(0.80, 0.98 - 0.06 * (axis_idx - 2))

            # Per-axis title padding (standoff) prevents title overlap
            STANDOFF_BASE = 16  # px
            STANDOFF_STEP = 16  # px per extra right axis
            standoff = STANDOFF_BASE + STANDOFF_STEP * (axis_idx - 2)

            fig.update_layout(
                **{
                    axis_name: dict(
                        anchor="x",
                        overlaying="y",
                        side="right",
                        position=pos,
                        showgrid=False,
                        ticks="outside",
                        ticklabelposition="outside",
                        title=dict(standoff=standoff),  # <- key: padding between axis and its title
                    )
                }
            )

            # remember the standoff so we can reuse it when we set the text later
            state.setdefault("plotly_axis_meta", {})[axis_name] = {"standoff": standoff}

            state["right_axes"].append(axis_idx)
            return axis_idx

    def _remember_line_mpl(line, label, series_like: pd.Series, meta: dict | None = None):
        s_valid = series_like.dropna()
        if len(s_valid) > 0:
            last_dt = s_valid.index[-1]
            last_val = s_valid.iloc[-1]
        else:
            last_dt, last_val = None, np.nan
        entry = {"line": line, "label": label, "last_dt": last_dt, "last_val": last_val}
        if meta:
            entry.update(meta)
        state["series_meta"].append(entry)

    def _remember_line_plotly(trace_idx: int, label, series_like: pd.Series, meta: dict | None = None):
        s_valid = series_like.dropna()
        if len(s_valid) > 0:
            last_dt = s_valid.index[-1]
            last_val = s_valid.iloc[-1]
        else:
            last_dt, last_val = None, np.nan
        entry = {"trace_idx": trace_idx, "label": label, "last_dt": last_dt, "last_val": last_val}
        if meta:
            entry.update(meta)
        state["series_meta"].append(entry)

    def _remember_hidden(label, last_val, last_dt, meta: dict | None = None):
        entry = {"label": label, "last_val": last_val, "last_dt": last_dt}
        if meta:
            entry.update(meta)
        state["hidden_meta"].append(entry)

    # ---------- data pipeline ----------
    def _apply_pipeline(series: pd.Series, cfg: dict):
        if cfg is None:
            cfg = {}
        s = series.copy()

        rs = cfg.get("resample")
        if rs and isinstance(rs, dict) and "rule" in rs:
            agg = rs.get("agg", "last")
            if isinstance(agg, str):
                s = getattr(s.resample(rs["rule"]), agg)()
            else:
                s = s.resample(rs["rule"]).apply(agg)

        fl = cfg.get("fill")
        if fl and isinstance(fl, dict):
            method = fl.get("method", None)
            limit = fl.get("limit", None)
            if method in ("ffill", "bfill"):
                s = s.fillna(method=method, limit=limit)

        ip = cfg.get("interpolate")
        if ip and isinstance(ip, dict):
            method = ip.get("method", "time")
            kw = ip.get("kwargs", {})
            try:
                s = s.interpolate(method=method, limit_direction="both", **kw)
            except Exception:
                s = s.interpolate(limit_direction="both")

        if cfg.get("log", False):
            s = s.where(s > 0.0)
            s = np.log(s)

        if "pct_change" in cfg and cfg["pct_change"]:
            s = s.pct_change(int(cfg["pct_change"]))
        if "diff" in cfg and cfg["diff"]:
            s = s.diff(int(cfg["diff"]))

        zc = cfg.get("zscore")
        if isinstance(zc, dict):
            w = zc.get("window", None)
            if w and int(w) > 1:
                roll = s.rolling(int(w))
                s = (s - roll.mean()) / roll.std(ddof=1)
            else:
                sd = s.std(ddof=1)
                s = (s - s.mean()) / (sd if (sd and np.isfinite(sd)) else 1.0)

        sc = cfg.get("scale")
        if isinstance(sc, dict):
            typ = sc.get("type", None)
            with_centering = sc.get("with_centering", True)
            if typ == "standard":
                mu, sd = s.mean(), s.std(ddof=1)
                if sd and np.isfinite(sd):
                    s = (s - mu) / sd if with_centering else s / sd
            elif typ == "minmax":
                lo, hi = sc.get("range", (0.0, 1.0))
                mn, mx = s.min(), s.max()
                rng = mx - mn
                if rng and np.isfinite(rng):
                    s = lo + (s - mn) * (hi - lo) / rng
            elif typ == "robust":
                med = s.median()
                iqr = s.quantile(0.75) - s.quantile(0.25)
                if iqr and np.isfinite(iqr):
                    s = (s - med) / iqr if with_centering else s / iqr

        wz = cfg.get("winsor")
        if isinstance(wz, dict) and "limits" in wz:
            lo, hi = wz["limits"]
            ql, qh = s.quantile(lo), s.quantile(hi)
            s = s.clip(lower=ql, upper=qh)

        cl = cfg.get("clip")
        if isinstance(cl, dict):
            lo, hi = cl.get("lo", None), cl.get("hi", None)
            s = s.clip(lower=lo, upper=hi)

        if cfg.get("dropna", True):
            s = s.dropna()

        return s

    # ---------- technical primitives ----------
    def _sma(s, window):
        return s.rolling(int(window)).mean()

    def _ema(s, span):
        return s.ewm(span=int(span), adjust=False).mean()

    def _rsi(s, window=14):
        delta = s.diff()
        up = delta.clip(lower=0.0)
        down = -delta.clip(upper=0.0)
        roll_up = up.ewm(alpha=1.0 / window, adjust=False).mean()
        roll_down = down.ewm(alpha=1.0 / window, adjust=False).mean()
        rs = roll_up / roll_down
        return 100.0 - (100.0 / (1.0 + rs))

    def _macd(s, fast=12, slow=26, signal=9):
        macd_line = _ema(s, fast) - _ema(s, slow)
        signal_line = _ema(macd_line, signal)
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    def _boll(s, window=20, n=2, center=True):
        m = s.rolling(int(window)).mean()
        sd = s.rolling(int(window)).std(ddof=1)
        upper = m + n * sd
        lower = m - n * sd
        return (m if center else None), upper, lower

    def _roll_vol(s, window=60, returns="normal", annualize=True, trading_days=252, scale_to_bps=False):
        s = s.astype(float)
        if returns == "log":
            r = np.log(s.where(s > 0)).diff()
        elif returns in ("simple", "ret"):
            r = s.pct_change()
        elif returns in ("normal", "bachelier", "level"):
            r = s.diff()
            if scale_to_bps:
                r = r * 100
        elif returns in ("abs",):
            r = s.diff().abs()
        else:
            raise ValueError("returns must be one of {'log','simple','normal','bachelier','level','abs'}")
        vol = r.rolling(int(window)).std(ddof=1)
        if annualize:
            vol = vol * np.sqrt(trading_days)
        if vol.iloc[-1] > 1000:
            vol = vol / 100
        return vol

    def _z(s, window=60):
        roll = s.rolling(int(window))
        return (s - roll.mean()) / roll.std(ddof=1)

    def _hurst_exponent(s, max_lag=100):
        x = s.dropna().values
        if x.size < 20:
            return np.nan
        lags = np.arange(2, min(int(max_lag), x.size // 2))
        if lags.size < 2:
            return np.nan
        tau = np.array([np.std(x[lag:] - x[:-lag]) for lag in lags])
        mask = np.isfinite(tau) & (tau > 0)
        if mask.sum() < 2:
            return np.nan
        lags = lags[mask]
        tau = tau[mask]
        slope, _ = np.polyfit(np.log(lags), np.log(tau), 1)
        return float(2.0 * slope)

    def _hurst_roll(s, window=252, max_lag=100):
        w = int(window)
        vals = []
        idx = []
        for i in range(w, len(s) + 1):
            h = _hurst_exponent(s.iloc[i - w : i], max_lag=max_lag)
            vals.append(h)
            idx.append(s.index[i - 1])
        return pd.Series(vals, index=idx, name=f"H({w})")

    def _ar1_halflife(s, demean=True):
        y = s.dropna()
        if y.size < 5:
            return np.nan
        if demean:
            y = y - y.mean()
        y_lag = y.shift(1).dropna()
        y2 = y.loc[y_lag.index]
        X = np.vstack([np.ones(len(y_lag)), y_lag.values]).T
        try:
            beta = np.linalg.lstsq(X, y2.values, rcond=None)[0]
            b = float(beta[1])
        except Exception:
            return np.nan
        if not (0 < b < 1) or not np.isfinite(b):
            return np.nan
        return float(-np.log(2.0) / np.log(b))

    def _ou_calibrate(s: pd.Series, *, dt: float = 1.0, demean: bool = False):
        y = s.dropna().astype(float)
        if len(y) < 5:
            return {"mu": np.nan, "kappa": np.nan, "sigma": np.nan, "phi": np.nan, "intercept": np.nan, "half_life": np.nan}
        if demean:
            y = y - y.mean()
        y0 = y.shift(1).dropna()
        y1 = y.loc[y0.index]
        X = np.column_stack([np.ones(len(y0)), y0.values])
        a, b = np.linalg.lstsq(X, y1.values, rcond=None)[0]
        if not (0.0 < b < 1.0) or not np.isfinite(b):
            return {"mu": np.nan, "kappa": np.nan, "sigma": np.nan, "phi": float(b), "intercept": float(a), "half_life": np.nan}
        mu = a / (1.0 - b)
        kappa = -np.log(b) / float(dt)
        eps = y1.values - (a + b * y0.values)
        s2_eta = np.var(eps, ddof=1)
        sigma = np.sqrt(max(0.0, s2_eta * (2.0 * kappa) / (1.0 - b**2)))
        half_life = np.log(2.0) / kappa
        return {"mu": float(mu), "kappa": float(kappa), "sigma": float(sigma), "phi": float(b), "intercept": float(a), "half_life": float(half_life)}

    def _adf_pvalue_series(s, window=None, reg="c"):
        try:
            from statsmodels.tsa.stattools import adfuller
        except Exception:
            return np.nan if window is None else pd.Series(index=s.index, dtype=float)
        if window is None:
            y = s.dropna()
            if y.size < 10:
                return np.nan
            try:
                return float(adfuller(y.values, regression=reg, autolag="AIC")[1])
            except Exception:
                return np.nan
        else:
            w = int(window)
            vals, idx = [], []
            for i in range(w, len(s) + 1):
                seg = s.iloc[i - w : i].dropna()
                if seg.size < w * 0.8:
                    vals.append(np.nan)
                    idx.append(s.index[i - 1])
                    continue
                try:
                    p = adfuller(seg.values, regression=reg, autolag="AIC")[1]
                except Exception:
                    p = np.nan
                vals.append(p)
                idx.append(s.index[i - 1])
            return pd.Series(vals, index=idx, name=f"ADF p({w})")

    def _variance_ratio(s, k=5, window=252, returns="simple"):
        k = int(k)
        w = int(window)
        r = np.log(s).diff() if returns == "log" else s.diff()
        out, idx = [], []
        for i in range(w, len(r) + 1):
            seg = r.iloc[i - w : i].dropna()
            if seg.size < w * 0.8:
                out.append(np.nan)
                idx.append(r.index[i - 1])
                continue
            var1 = seg.var(ddof=1)
            rk = seg.rolling(k).sum()
            vark = rk.var(ddof=1)
            vr = (vark / k) / var1 if (var1 and np.isfinite(var1)) else np.nan
            out.append(vr)
            idx.append(r.index[i - 1])
        return pd.Series(out, index=idx, name=f"VR(k={k},w={w})")

    def _guess_bp_scale(s):
        m = s.dropna().abs().median()
        if not np.isfinite(m):
            return 10_000.0
        if m < 1.0:
            return 10_000.0
        elif m < 100.0:
            return 100.0
        return 1.0

    def _realized_vol(s, window=60, typ="bpvol"):
        w = int(window)
        if typ in ("bpvol", "bachelier", "normal"):
            d = s.diff()
            vol = d.rolling(w).std(ddof=1) * np.sqrt(252)
            scale = _guess_bp_scale(s)
            return vol * scale
        elif typ in ("lognormal", "ln"):
            x = s.where(s > 0.0)
            r = np.log(x).diff()
            vol = r.rolling(w).std(ddof=1) * np.sqrt(252)
            return vol
        else:
            raise ValueError("type must be one of {'bpvol','lognormal'}")

    # ---------- OU overlay ----------
    def _plot_ou(ax_or_axis, series: pd.Series, ou_cfg: dict):
        if not (ou_cfg and ou_cfg.get("enable", False)):
            return
        try:
            df_calib = series.dropna().to_frame(name="resid")
            if df_calib.shape[0] < 3:
                return
            ou_df, fpt = simulate_mean_reversion_ou(df_calib, steps=int(ou_cfg.get("steps", 126)))

            style_mean = dict(linestyle="-", linewidth=1.45)
            style_mean.update(ou_cfg.get("style_mean", {}))
            style_1sig = dict(linestyle="--", linewidth=1.20)
            style_1sig.update(ou_cfg.get("style_1sig", {}))
            style_2sig = dict(linestyle="-.", linewidth=1.20)
            style_2sig.update(ou_cfg.get("style_2sig", {}))
            color_mean = ou_cfg.get("color_mean", "tab:blue")
            color_sigma = ou_cfg.get("color_sigma", "tab:red")

            if state["engine"] == "matplotlib":
                ax = ax_or_axis
                ax.plot(
                    ou_df.index,
                    ou_df["mean_reversion"].values,
                    color=color_mean,
                    **{k: v for k, v in style_mean.items() if k != "linestyle"},
                    linestyle=style_mean.get("linestyle", "-"),
                    label="OU mean path",
                )
                if "+1_sigma" in ou_df.columns and "-1_sigma" in ou_df.columns:
                    ax.plot(
                        ou_df.index,
                        ou_df["+1_sigma"].values,
                        color=color_sigma,
                        **{k: v for k, v in style_1sig.items() if k != "linestyle"},
                        linestyle=style_1sig.get("linestyle", "--"),
                        label="OU +1σ",
                    )
                    ax.plot(
                        ou_df.index,
                        ou_df["-1_sigma"].values,
                        color=color_sigma,
                        **{k: v for k, v in style_1sig.items() if k != "linestyle"},
                        linestyle=style_1sig.get("linestyle", "--"),
                        label="OU -1σ",
                    )
                if "+2_sigma" in ou_df.columns and "-2_sigma" in ou_df.columns:
                    ax.plot(
                        ou_df.index,
                        ou_df["+2_sigma"].values,
                        color=color_sigma,
                        **{k: v for k, v in style_2sig.items() if k != "linestyle"},
                        linestyle=style_2sig.get("linestyle", "-."),
                        label="OU +2σ",
                    )
                    ax.plot(
                        ou_df.index,
                        ou_df["-2_sigma"].values,
                        color=color_sigma,
                        **{k: v for k, v in style_2sig.items() if k != "linestyle"},
                        linestyle=style_2sig.get("linestyle", "-."),
                        label="OU -2σ",
                    )
            else:
                axis_name = ax_or_axis  # e.g., 'y', 'y2', ...

                def _add(name, y, dash=None, color=None):
                    fig.add_trace(
                        go.Scatter(
                            x=ou_df.index, y=y, name=name, mode="lines", line=dict(dash=dash or "solid", width=1.4, color=color), yaxis=axis_name, showlegend=True
                        )
                    )

                _add("OU mean path", ou_df["mean_reversion"].values, dash=None, color=color_mean)
                if "+1_sigma" in ou_df.columns and "-1_sigma" in ou_df.columns:
                    _add("OU +1σ", ou_df["+1_sigma"].values, dash="dash", color=color_sigma)
                    _add("OU -1σ", ou_df["-1_sigma"].values, dash="dash", color=color_sigma)
                if "+2_sigma" in ou_df.columns and "-2_sigma" in ou_df.columns:
                    _add("OU +2σ", ou_df["+2_sigma"].values, dash="dashdot", color=color_sigma)
                    _add("OU -2σ", ou_df["-2_sigma"].values, dash="dashdot", color=color_sigma)

            mu_inf = float(ou_df["mean_reversion"].iloc[-1]) if "mean_reversion" in ou_df.columns else np.nan
            sigma_inf = float(ou_df["+1_sigma"].iloc[-1] - ou_df["mean_reversion"].iloc[-1]) if "+1_sigma" in ou_df.columns else np.nan
            if ou_cfg.get("add_metrics_to_legend", True):
                bits = []
                if fpt is not None and np.isfinite(fpt):
                    bits.append(f"OU FPT≈{fpt:.0f} steps")
                if np.isfinite(mu_inf):
                    bits.append(f"μ∞≈{mu_inf:.3f}")
                if np.isfinite(sigma_inf):
                    bits.append(f"σ∞≈{sigma_inf:.3f}")
                    bits.append(f"μ∞±1σ≈[{mu_inf - sigma_inf:.3f}, {mu_inf + sigma_inf:.3f}]")
                    bits.append(f"μ∞±2σ≈[{mu_inf - 2*sigma_inf:.3f}, {mu_inf + 2*sigma_inf:.3f}]")
                if bits:
                    state["ou_meta"].append("; ".join(bits))
        except NameError:
            raise RuntimeError("simulate_mean_reversion_ou is not defined. Please import/define it.")

    def _cum_change_scalar(s: pd.Series, *, n: int | None = None, from_at=None, typ: str = "abs"):
        s = s.dropna()
        if s.empty:
            return np.nan, None, None
        last_dt = s.index[-1]
        last_val = float(s.iloc[-1])
        base_val = None
        base_dt = None
        if from_at is not None:
            try:
                ts = pd.Timestamp(from_at)
                if ts in s.index:
                    base_dt = ts
                    base_val = float(s.loc[ts])
                else:
                    pos = s.index.get_indexer([ts], method="nearest")[0]
                    base_dt = s.index[pos]
                    base_val = float(s.iloc[pos])
            except Exception:
                if from_at in s.index:
                    base_dt = from_at
                    base_val = float(s.loc[from_at])
        elif n is not None:
            k = int(n)
            if k < len(s):
                base_dt = s.index[-1 - k]
                base_val = float(s.iloc[-1 - k])
            else:
                base_dt = s.index[0]
                base_val = float(s.iloc[0])
        else:
            if len(s) >= 2:
                base_dt = s.index[-2]
                base_val = float(s.iloc[-2])
            else:
                return np.nan, last_dt, None
        if base_val is None or not np.isfinite(base_val):
            return np.nan, last_dt, base_dt
        if typ in ("pct_chg", "pct"):
            return ((last_val / base_val) - 1.0) * 100.0, last_dt, base_dt
        elif typ == "bps":
            return (last_val - base_val) * 10_000.0, last_dt, base_dt
        else:
            return (last_val - base_val), last_dt, base_dt

    # ---------- plot ----------
    def plot(series: pd.Series, *, label=None, which="left", pipeline=None, indicators=None, ou=None, guess_units=True, step: bool | str = False, **kwargs):

        if not isinstance(series, pd.Series):
            raise TypeError("plot() expects a pandas Series")
        if label is None:
            label = _stringify_name(series.name)

        s_proc = _apply_pipeline(series, pipeline or {})

        # normalize step param
        _step_mode = None
        if isinstance(step, bool):
            _step_mode = "post" if step else None
        elif isinstance(step, str):
            sm = step.lower().strip()
            if sm not in ("pre", "post", "mid"):
                raise ValueError("step must be one of {False, True, 'pre', 'post', 'mid'}")
            _step_mode = sm

        # Target axis (mpl Axes or plotly axis name)
        if state["engine"] == "matplotlib":
            if which == "left":
                target = ax_left
            else:
                target = _new_right_axis()
        else:
            if which == "left":
                target = "y"  # main y-axis name for traces
            else:
                axis_idx = _new_right_axis()
                target = f"y{axis_idx}"  # e.g. 'y2', 'y3', ...

        color = kwargs.get("color", _next_color())

        # --- main line ---
        if state["engine"] == "matplotlib":
            ax_target = ax_left if which == "left" else target
            plot_fn = ax_target.step if _step_mode else ax_target.plot

            plot_kwargs = {k: v for k, v in kwargs.items() if k != "color"}
            if _step_mode:
                (line,) = plot_fn(s_proc.index, s_proc.values, where=_step_mode, label=label, color=color, **plot_kwargs)
            else:
                (line,) = plot_fn(s_proc.index, s_proc.values, label=label, color=color, **plot_kwargs)

            _remember_line_mpl(line, label, s_proc)
            if which == "left":
                state["left_lines"].append(line)
                if state["left_color"] is None:
                    state["left_color"] = line.get_color()
                    ax_left.tick_params(axis="y", labelcolor=state["left_color"])
                    ax_left.set_ylabel(ylabel_left or label, color=state["left_color"])
            else:
                state["right_lines"].append(line)
                ax_target.tick_params(axis="y", labelcolor=line.get_color())
                ax_target.set_ylabel(ylabel_right or label, color=line.get_color())

        else:
            # plotly trace
            shape_map = {"pre": "vh", "post": "hv", "mid": "hvh"}
            trace = dict(
                x=s_proc.index,
                y=s_proc.values,
                name=label,
                mode="lines",
                line=dict(color=color),
                yaxis=target,
                showlegend=True,
            )
            if _step_mode:
                trace["line_shape"] = shape_map[_step_mode]

            fig.add_trace(go.Scatter(**trace))
            trace_idx = len(fig.data) - 1
            _remember_line_plotly(trace_idx, label, s_proc)

            if which == "left" and state["left_color"] is None:
                state["left_color"] = color
                fig.update_yaxes(
                    title=dict(text=(ylabel_left or label), font=dict(color=color)),
                    tickfont=dict(color=color),
                )
            elif which == "right":
                axis_name = target.replace("y", "yaxis") if target != "y" else "yaxis"
                # keep the standoff we stored when creating the axis
                standoff = state.get("plotly_axis_meta", {}).get(axis_name, {}).get("standoff", 16)
                fig.update_layout(
                    **{
                        axis_name: dict(
                            title=dict(text=(ylabel_right or label), font=dict(color=color), standoff=standoff),
                            tickfont=dict(color=color),
                            ticks="outside",
                            ticklabelposition="outside",
                        )
                    }
                )

        def _handle_series_hide(y, lbl, meta=None):
            yv = y.dropna()
            if len(yv) == 0:
                return True
            _remember_hidden(lbl, float(yv.iloc[-1]), yv.index[-1], meta=meta or {})
            return True

        def _handle_scalar_hide(val, lbl, meta=None):
            last_dt2 = s_proc.index[-1] if len(s_proc) else None
            _remember_hidden(lbl, float(val) if np.isfinite(val) else np.nan, last_dt2, meta=meta or {})
            return True

        # ---------- indicators ----------
        if indicators:
            for ind in indicators:
                kind = ind.get("kind")
                which_ind = ind.get("which", "left")
                hide = bool(ind.get("hide", False))
                style = dict(ind.get("style", {}))
                style_color = style.pop("color", None)

                # Which axis does the indicator draw on?
                if state["engine"] == "matplotlib":
                    ax_ind = ax_left if which_ind == "left" else (ax_left if which == "left" else (ax_left if which_ind == "auto" else _new_right_axis()))
                    if which_ind == "right":
                        ax_ind = ax_left if which == "left" else target
                else:
                    if which_ind == "left":
                        ax_ind = "y"
                    elif which_ind == "right":
                        ax_ind = target  # same as series' axis (right)
                    else:
                        ax_ind = "y"

                # helper: horizontal line
                def _add_hline(val, lbl, axis_for_line, line_style):
                    if state["engine"] == "matplotlib":
                        line_style.setdefault("linestyle", ":")
                        line_style.setdefault("linewidth", 1.0)
                        h = (ax_ind if axis_for_line is None else axis_for_line).axhline(y=val, color=style_color or color, **line_style, label=lbl)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, pd.Series([val], index=[s_proc.index[-1]]))
                    else:
                        x0, x1 = (s_proc.index.min(), s_proc.index.max()) if len(s_proc) else (0, 1)
                        dash_map = {":": "dot", "--": "dash", "-.": "dashdot", "-": "solid"}
                        dash = dash_map.get(line_style.get("linestyle", ":"), "dot")
                        fig.add_trace(
                            go.Scatter(
                                x=[x0, x1],
                                y=[val, val],
                                mode="lines",
                                name=lbl,
                                line=dict(dash=dash, width=line_style.get("linewidth", 1.0), color=style_color or color),
                                yaxis=ax_ind,
                                showlegend=True,
                            )
                        )
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, pd.Series([val], index=[s_proc.index[-1]]))

                if kind == "sma":
                    y = _sma(s_proc, ind.get("window", 20))
                    lbl = ind.get("label", f"SMA({ind.get('window', 20)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or color, label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or color), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "ema":
                    y = _ema(s_proc, ind.get("span", 21))
                    lbl = ind.get("label", f"EMA({ind.get('span', 21)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or color, label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or color), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "boll":
                    m, up, lo = _boll(s_proc, ind.get("window", 20), ind.get("n", 2), ind.get("center", True))
                    if m is not None:
                        lblm = ind.get("label", f"Boll mid({ind.get('window',20)})")
                        if hide:
                            _handle_series_hide(m, lblm)
                        else:
                            if state["engine"] == "matplotlib":
                                (hm,) = ax_ind.plot(m.index, m.values, color=style_color or color, linestyle="--", label=lblm, **style)
                                state["indicator_lines"].append(hm)
                                _remember_line_mpl(hm, lblm, m)
                            else:
                                fig.add_trace(
                                    go.Scatter(x=m.index, y=m.values, name=lblm, mode="lines", line=dict(color=style_color or color, dash="dash"), yaxis=ax_ind)
                                )
                                state["indicator_lines"].append(len(fig.data) - 1)
                                _remember_line_plotly(len(fig.data) - 1, lblm, m)
                    lblu, lbll = f"Boll +{ind.get('n',2)}σ", f"Boll -{ind.get('n',2)}σ"
                    if hide:
                        _handle_series_hide(up, lblu)
                        _handle_series_hide(lo, lbll)
                    else:
                        if state["engine"] == "matplotlib":
                            (hu,) = ax_ind.plot(up.index, up.values, color=style_color or color, linestyle="-.", label=lblu, **style)
                            (hl,) = ax_ind.plot(lo.index, lo.values, color=style_color or color, linestyle="-.", label=lbll, **style)
                            state["indicator_lines"] += [hu, hl]
                            _remember_line_mpl(hu, lblu, up)
                            _remember_line_mpl(hl, lbll, lo)
                        else:
                            fig.add_trace(
                                go.Scatter(x=up.index, y=up.values, name=lblu, mode="lines", line=dict(color=style_color or color, dash="dashdot"), yaxis=ax_ind)
                            )
                            fig.add_trace(
                                go.Scatter(x=lo.index, y=lo.values, name=lbll, mode="lines", line=dict(color=style_color or color, dash="dashdot"), yaxis=ax_ind)
                            )
                            state["indicator_lines"] += [len(fig.data) - 2, len(fig.data) - 1]
                            _remember_line_plotly(len(fig.data) - 2, lblu, up)
                            _remember_line_plotly(len(fig.data) - 1, lbll, lo)

                elif kind == "rsi":
                    y = _rsi(s_proc, ind.get("window", 14))
                    lbl = ind.get("label", f"RSI({ind.get('window', 14)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                        ax_ind.axhline(30, color="gray", linestyle=":", linewidth=0.8)
                        ax_ind.axhline(70, color="gray", linestyle=":", linewidth=0.8)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)
                        # threshold aids
                        fig.add_trace(
                            go.Scatter(
                                x=[y.index.min(), y.index.max()],
                                y=[30, 30],
                                mode="lines",
                                name="RSI 30",
                                line=dict(dash="dot", width=0.8),
                                showlegend=False,
                                yaxis=ax_ind,
                            )
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=[y.index.min(), y.index.max()],
                                y=[70, 70],
                                mode="lines",
                                name="RSI 70",
                                line=dict(dash="dot", width=0.8),
                                showlegend=False,
                                yaxis=ax_ind,
                            )
                        )

                elif kind == "macd":
                    macd_line, signal_line, hist = _macd(s_proc, ind.get("fast", 12), ind.get("slow", 26), ind.get("signal", 9))
                    if hide:
                        _handle_series_hide(macd_line, "MACD")
                        _handle_series_hide(signal_line, "Signal")
                        continue
                    if state["engine"] == "matplotlib":
                        (hm,) = ax_ind.plot(macd_line.index, macd_line.values, color=style_color or _next_color(), label="MACD", **style)
                        (hs,) = ax_ind.plot(signal_line.index, signal_line.values, color=style_color or _next_color(), label="Signal", **style)
                        state["indicator_lines"] += [hm, hs]
                        _remember_line_mpl(hm, "MACD", macd_line)
                        _remember_line_mpl(hs, "Signal", signal_line)
                    else:
                        fig.add_trace(
                            go.Scatter(x=macd_line.index, y=macd_line.values, name="MACD", mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind)
                        )
                        fig.add_trace(
                            go.Scatter(
                                x=signal_line.index, y=signal_line.values, name="Signal", mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind
                            )
                        )
                        state["indicator_lines"] += [len(fig.data) - 2, len(fig.data) - 1]
                        _remember_line_plotly(len(fig.data) - 2, "MACD", macd_line)
                        _remember_line_plotly(len(fig.data) - 1, "Signal", signal_line)

                elif kind == "vol":
                    if guess_units:
                        scale_to_bps = False if ("curve" in str(series.name).lower() or "fly" in str(series.name).lower()) else True
                    else:
                        scale_to_bps = ind.get("scale_to_bps", False)
                    y = _roll_vol(s_proc, ind.get("window", 60), ind.get("returns", "abs"), ind.get("annualize", True), 252, scale_to_bps)
                    lbl = ind.get("label", f"Vol({ind.get('window',60)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "z":
                    y = _z(s_proc, ind.get("window", 60))
                    lbl = ind.get("label", f"Z({ind.get('window',60)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "last":
                    include_date = bool(ind.get("show_date", False))
                    date_only = bool(ind.get("show_date_only", False))
                    meta_flag = {"legend_include_date": include_date, "legend_date_only": date_only}
                    state["suppress_main_last_labels"].add(label)
                    s_valid2 = s_proc.dropna()
                    if len(s_valid2) == 0:
                        continue
                    last_dt2, last_val2 = s_valid2.index[-1], float(s_valid2.iloc[-1])
                    lbl = ind.get("label", f"Last({label})")
                    if hide:
                        _handle_scalar_hide(last_val2, lbl, meta=meta_flag)
                        continue
                    line_style = dict(style)
                    if "linestyle" not in line_style:
                        line_style["linestyle"] = ":"
                    _add_hline(last_val2, lbl, ax_ind if state["engine"] == "matplotlib" else None, line_style)
                    # store meta
                    if state["engine"] == "matplotlib":
                        _remember_line_mpl(state["indicator_lines"][-1], lbl, pd.Series([last_val2], index=[last_dt2]), meta=meta_flag)
                    else:
                        _remember_line_plotly(state["indicator_lines"][-1], lbl, pd.Series([last_val2], index=[last_dt2]), meta=meta_flag)

                elif kind == "simple_avg":
                    s_valid2 = s_proc.dropna()
                    if len(s_valid2) == 0:
                        continue
                    avg_val = float(s_valid2.mean())
                    lbl = ind.get("label", f"Avg({label})")
                    if hide:
                        _handle_scalar_hide(avg_val, lbl)
                        continue
                    line_style = dict(style)
                    if "linestyle" not in line_style:
                        line_style["linestyle"] = ":"
                    _add_hline(avg_val, lbl, ax_ind if state["engine"] == "matplotlib" else None, line_style)

                elif kind == "hurst":
                    H = _hurst_exponent(s_proc, ind.get("max_lag", 100))
                    if not np.isfinite(H):
                        continue
                    lbl = ind.get("label", "Hurst")
                    if hide:
                        _handle_scalar_hide(H, lbl)
                        continue
                    _add_hline(H, lbl, ax_ind if state["engine"] == "matplotlib" else None, {"linestyle": ":"})

                elif kind == "hurst_roll":
                    y = _hurst_roll(s_proc, ind.get("window", 252), ind.get("max_lag", 100))
                    lbl = ind.get("label", f"H({ind.get('window',252)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "half_life":
                    method = ind.get("method", "ar1")
                    dt = float(ind.get("dt", 1.0))
                    demean_flag = bool(ind.get("demean", True))
                    if method == "ou":
                        params = _ou_calibrate(s_proc, dt=dt, demean=demean_flag)
                        hl = params["half_life"]
                    else:
                        hl = _ar1_halflife(s_proc, demean=demean_flag)
                    if not np.isfinite(hl):
                        continue
                    lbl = ind.get("label", "Half-life" + (" (OU)" if method == "ou" else " (steps)"))
                    if hide:
                        _handle_scalar_hide(hl, lbl)
                        continue
                    _add_hline(hl, lbl, ax_ind if state["engine"] == "matplotlib" else None, {"linestyle": ":"})

                elif kind == "adf_p":
                    w = ind.get("window", None)
                    reg = ind.get("reg", "c")
                    y = _adf_pvalue_series(s_proc, window=w, reg=reg)
                    if isinstance(y, pd.Series):
                        lbl = ind.get("label", f"ADF p({w})" if w else "ADF p")
                        if hide:
                            _handle_series_hide(y, lbl)
                            continue
                        if state["engine"] == "matplotlib":
                            (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                            state["indicator_lines"].append(h)
                            _remember_line_mpl(h, lbl, y)
                        else:
                            fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                            state["indicator_lines"].append(len(fig.data) - 1)
                            _remember_line_plotly(len(fig.data) - 1, lbl, y)
                    else:
                        p = float(y)
                        if not np.isfinite(p):
                            continue
                        lbl = ind.get("label", "ADF p")
                        if hide:
                            _handle_scalar_hide(p, lbl)
                            continue
                        _add_hline(p, lbl, ax_ind if state["engine"] == "matplotlib" else None, {"linestyle": ":"})

                elif kind == "vr":
                    y = _variance_ratio(s_proc, k=ind.get("k", 5), window=ind.get("window", 252), returns=ind.get("returns", "simple"))
                    lbl = ind.get("label", f"VR(k={ind.get('k',5)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    if state["engine"] == "matplotlib":
                        (h,) = ax_ind.plot(y.index, y.values, color=style_color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line_mpl(h, lbl, y)
                    else:
                        fig.add_trace(go.Scatter(x=y.index, y=y.values, name=lbl, mode="lines", line=dict(color=style_color or _next_color()), yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        _remember_line_plotly(len(fig.data) - 1, lbl, y)

                elif kind == "cum_change":
                    include_date = bool(ind.get("show_date", False))
                    date_only = bool(ind.get("show_date_only", False))
                    meta_flag = {"legend_include_date": include_date, "legend_date_only": date_only}
                    typ = ind.get("type", "abs")
                    hide_local = ind.get("hide", True)  # default True
                    n = ind.get("n", None)
                    from_at = ind.get("from_at", None)
                    delta, last_dt2, base_dt = _cum_change_scalar(s_proc, n=n, from_at=from_at, typ=typ)
                    if from_at is not None or base_dt is not None:
                        base_txt = _fmt_dt(base_dt) if base_dt is not None else str(from_at)
                        lbl_default = f"Δ since {base_txt}"
                    elif n is not None:
                        lbl_default = f"Δ{int(n)}" + (f" ({typ})" if typ != "abs" else "")
                    else:
                        lbl_default = "Δ1" + (f" ({typ})" if typ != "abs" else "")
                    lbl = ind.get("label", lbl_default)
                    if hide_local:
                        _remember_hidden(lbl, float(delta) if np.isfinite(delta) else np.nan, last_dt2, meta=meta_flag)
                        continue
                    # dummy legend entry
                    if state["engine"] == "matplotlib":
                        dummy = plt.Line2D([], [], color="none", label=lbl, **style)
                        state["indicator_lines"].append(dummy)
                        state["series_meta"].append({"line": dummy, "label": lbl, "last_dt": last_dt2, "last_val": float(delta), "kind": "cum_change", **meta_flag})
                    else:
                        fig.add_trace(go.Scatter(x=[None], y=[None], name=lbl, mode="lines", line=dict(color="rgba(0,0,0,0)"), showlegend=True, yaxis=ax_ind))
                        state["indicator_lines"].append(len(fig.data) - 1)
                        state["series_meta"].append(
                            {"trace_idx": len(fig.data) - 1, "label": lbl, "last_dt": last_dt2, "last_val": float(delta), "kind": "cum_change", **meta_flag}
                        )

        if ou and isinstance(ou, dict) and ou.get("enable", False):
            if state["engine"] == "matplotlib":
                target_for_ou = ax_left if which == "left" else target  # <-- reuse target
            else:
                target_for_ou = "y" if which == "left" else target  # <-- reuse target
            _plot_ou(target_for_ou, s_proc, ou)

        return None  # line handle isn't relied upon by callers in this design

    # ---------- legend ----------
    def legend(loc="best", valfmt="{:.2f}", show_date=False, sep=" — ", **kwargs):
        if state["engine"] == "matplotlib":
            handles = state["left_lines"] + state["right_lines"] + state["indicator_lines"]
            meta_map = {m.get("line"): m for m in state["series_meta"] if "line" in m}
            labels = []
            for h in handles:
                m = meta_map.get(h, None)
                base = h.get_label()
                if m is None:
                    labels.append(base)
                    continue
                is_main_line = (h in state["left_lines"]) or (h in state["right_lines"])
                if is_main_line and (m["label"] in state["suppress_main_last_labels"]):
                    labels.append(base)
                    continue
                date_only = bool(m.get("legend_date_only", False))
                include_date = bool(m.get("legend_include_date", False))
                date_txt = _fmt_dt(m["last_dt"]) if m.get("last_dt") is not None else "—"
                if date_only:
                    labels.append(f"{base}{sep}{date_txt}")
                    continue
                lv = m["last_val"]
                try:
                    lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
                except Exception:
                    lv_text = str(lv)
                if (include_date or show_date) and m.get("last_dt") is not None:
                    lbl = f"{base}{sep}{lv_text} @ {date_txt}"
                else:
                    lbl = f"{base}{sep}{lv_text}"
                labels.append(lbl)

            # Hidden info-only entries
            if state["hidden_meta"]:
                for hm in state["hidden_meta"]:
                    date_only = bool(hm.get("legend_date_only", False))
                    include_date = bool(hm.get("legend_include_date", False))
                    date_txt = _fmt_dt(hm["last_dt"]) if hm.get("last_dt") is not None else "—"
                    if date_only:
                        labels.append(f"{hm['label']}{sep}{date_txt}")
                    else:
                        lv = hm["last_val"]
                        try:
                            lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
                        except Exception:
                            lv_text = str(lv)
                        if (include_date or show_date) and hm.get("last_dt") is not None:
                            labels.append(f"{hm['label']}{sep}{lv_text} @ {date_txt}")
                        else:
                            labels.append(f"{hm['label']}{sep}{lv_text}")
                    handles.append(plt.Line2D([], [], color="none", label=""))

            if state["ou_meta"]:
                labels.append("; ".join(state["ou_meta"]))
                handles.append(plt.Line2D([], [], color="none", label=""))

            ax_left.legend(handles, labels, loc=loc, **kwargs)

        else:

            def _compose(base, m):
                date_only = bool(m.get("legend_date_only", False))
                include_date = bool(m.get("legend_include_date", False))
                date_txt = _fmt_dt(m["last_dt"]) if m.get("last_dt") is not None else "—"
                if date_only:
                    return f"{base}{sep}{date_txt}"
                lv = m["last_val"]
                try:
                    lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
                except Exception:
                    lv_text = str(lv)
                if (include_date or show_date) and m.get("last_dt") is not None:
                    return f"{base}{sep}{lv_text} @ {date_txt}"
                return f"{base}{sep}{lv_text}"

            for m in state["series_meta"]:
                if "trace_idx" not in m:
                    continue
                idx = m["trace_idx"]
                base = fig.data[idx].name
                is_main_line = any((("line" in m2 and m2["line"] is None) and False) for m2 in state["series_meta"])  # no-op guard
                new_name = base if (m["label"] in state["suppress_main_last_labels"]) else _compose(base, m)
                fig.data[idx].name = new_name

            if state["hidden_meta"]:
                for hm in state["hidden_meta"]:
                    txt = _compose(hm["label"], hm)
                    fig.add_trace(go.Scatter(x=[None], y=[None], name=txt, mode="lines", line=dict(color="rgba(0,0,0,0)"), showlegend=True))
            if state["ou_meta"]:
                fig.add_trace(go.Scatter(x=[None], y=[None], name="; ".join(state["ou_meta"]), mode="lines", line=dict(color="rgba(0,0,0,0)"), showlegend=True))

            if "ncol" in kwargs:
                ncol = kwargs.pop("ncol")
                fig.update_layout(legend=dict(orientation="h"), template="plotly_dark")

            _ = kwargs

            fig.update_layout(template="plotly_dark", font=dict(size=11), height=750, newshape=dict(line=dict(color="red")))
            fig.update_xaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikemode="across", showgrid=True)
            fig.update_yaxes(showspikes=True, spikecolor="white", spikesnap="cursor", spikethickness=0.5, showgrid=True)
            fig.show(
                config={
                    "modeBarButtonsToAdd": [
                        "drawline",
                        "drawopenpath",
                        "drawclosedpath",
                        "drawcircle",
                        "drawrect",
                        "eraseshape",
                    ]
                }
            )

    # expose helpers
    plot.state = state
    plot.apply_pipeline = _apply_pipeline
    plot.add_indicator_defs = {
        "sma": _sma,
        "ema": _ema,
        "rsi": _rsi,
        "macd": _macd,
        "boll": _boll,
        "vol": _roll_vol,
        "z": _z,
        "hurst": _hurst_exponent,
        "hurst_roll": _hurst_roll,
        "half_life": _ar1_halflife,
        "adf_p": _adf_pvalue_series,
        "vr": _variance_ratio,
        "realized_vol": _realized_vol,
    }

    ax_right = None  # maintained for signature compatibility
    return plot, fig, ax_left, ax_right, legend
