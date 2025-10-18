import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from RVUtils.mean_reversion import simulate_mean_reversion_ou


def make_secondary_axis_plot(*, ylabel_left=None, ylabel_right=None, title=None):
    """
    Returns: plot, fig, ax_left, ax_right, legend

    plot(series, *, label=None, which='auto'|'left'|'right',
         pipeline=None, indicators=None,
         ou=None,
         **kwargs)

    legend(loc='best', valfmt='{:.2f}', show_date=False, sep=' — ', **kwargs)

    ----- Indicators (overlay lines) -----
      indicators = [
        {'kind': 'sma',  'window': 20, 'label': None, 'style': {}, 'hide': False},
        {'kind': 'ema',  'span': 21,   'label': None, 'style': {}, 'hide': False},
        {'kind': 'boll', 'window': 20, 'n': 2, 'center': True, 'style': {}, 'hide': False},
        {'kind': 'rsi',  'window': 14, 'style': {}, 'which': 'right', 'hide': False},
        {'kind': 'macd', 'fast': 12, 'slow': 26, 'signal': 9, 'style': {}, 'hide': False},
        {'kind': 'vol',  'window': 60, 'returns': 'abs'|'log', 'annualize': True, 'style': {}, 'hide': False},
        {'kind': 'z',    'window': 60, 'style': {}, 'hide': False},
        {'kind': 'last', 'label': None, 'style': {'linestyle': ':'}, 'hide': False},
        {'kind': 'simple_avg', 'label': None, 'style': {'linestyle': ':'}, 'hide': False},

        # mean-reversion set
        {'kind': 'hurst',       'max_lag': 100, 'label': None, 'style': {'linestyle': ':'}, 'hide': False},
        {'kind': 'hurst_roll',  'window': 252,  'max_lag': 100, 'label': None, 'style': {}, 'hide': False},
        {'kind': 'half_life',   'demean': True, 'label': None, 'style': {'linestyle': ':'}, 'hide': False},
        {'kind': 'adf_p',       'window': None, 'reg': 'c', 'label': None, 'style': {}, 'hide': False},
        {'kind': 'vr',          'k': 5, 'window': 252, 'returns': 'simple', 'label': None, 'style': {}, 'hide': False},
      ]
    """

    fig, ax_left = plt.subplots()
    fig.subplots_adjust(right=0.75)

    if title:
        ax_left.set_title(title)
    if ylabel_left:
        ax_left.set_ylabel(ylabel_left)

    colors = plt.rcParams.get("axes.prop_cycle", None)
    colors = (colors.by_key().get("color", []) if colors is not None else []) or [f"C{i}" for i in range(10)]

    state = {
        "left_lines": [],
        "right_lines": [],
        "right_axes": [],
        "color_idx": 0,
        "left_color": None,
        "series_meta": [],  # {line, label, last_dt, last_val}
        "indicator_lines": [],
        "ou_meta": [],  # strings for OU info
        "hidden_meta": [],  # [{label, last_dt, last_val}] for hide=True indicators
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

    def _new_right_axis():
        idx = len(state["right_axes"])
        ax = ax_left.twinx()
        ax.set_frame_on(True)
        ax.patch.set_visible(False)
        offset = 1.0 + 0.10 * idx
        ax.spines["right"].set_position(("axes", offset))
        ax.spines["right"].set_zorder(10 + idx)
        state["right_axes"].append(ax)
        return ax

    def _remember_line(line, label, series_like: pd.Series):
        s_valid = series_like.dropna()
        if len(s_valid) > 0:
            last_dt = s_valid.index[-1]
            last_val = s_valid.iloc[-1]
        else:
            last_dt, last_val = None, np.nan
        state["series_meta"].append({"line": line, "label": label, "last_dt": last_dt, "last_val": last_val})

    def _remember_hidden(label, last_val, last_dt):
        state["hidden_meta"].append({"label": label, "last_val": last_val, "last_dt": last_dt})

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

    def _roll_vol(s, window=60, returns="abs", annualize=True):
        if returns == "log":
            r = np.log(s).diff()
        else:
            r = s.diff().abs()
        vol = r.rolling(int(window)).std(ddof=1)
        if annualize:
            vol = vol * np.sqrt(252)
        return vol

    def _z(s, window=60):
        roll = s.rolling(int(window))
        return (s - roll.mean()) / roll.std(ddof=1)

    # === Mean-reversion analytics ===
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

    # ---------- OU overlay ----------
    def _plot_ou(ax, series: pd.Series, ou_cfg: dict):
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

            ax.plot(ou_df.index, ou_df["mean_reversion"].values, color=color_mean, **style_mean, label="OU mean path")
            if "+1_sigma" in ou_df.columns and "-1_sigma" in ou_df.columns:
                ax.plot(ou_df.index, ou_df["+1_sigma"].values, color=color_sigma, **style_1sig, label="OU +1σ")
                ax.plot(ou_df.index, ou_df["-1_sigma"].values, color=color_sigma, **style_1sig, label="OU -1σ")
            if "+2_sigma" in ou_df.columns and "-2_sigma" in ou_df.columns:
                ax.plot(ou_df.index, ou_df["+2_sigma"].values, color=color_sigma, **style_2sig, label="OU +2σ")
                ax.plot(ou_df.index, ou_df["-2_sigma"].values, color=color_sigma, **style_2sig, label="OU -2σ")

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

    # ---------- plot ----------
    def plot(series: pd.Series, *, label=None, which="left", pipeline=None, indicators=None, ou=None, **kwargs):
        if not isinstance(series, pd.Series):
            raise TypeError("plot() expects a pandas Series")
        if label is None:
            label = _stringify_name(series.name)

        s_proc = _apply_pipeline(series, pipeline or {})
        target = ax_left if which == "left" else _new_right_axis()
        if "color" not in kwargs:
            kwargs["color"] = _next_color()

        (line,) = target.plot(s_proc.index, s_proc.values, label=label, **kwargs)
        _remember_line(line, label, s_proc)

        s_valid = s_proc.dropna()
        if len(s_valid) > 0:
            last_dt = s_valid.index[-1]
            last_val = s_valid.iloc[-1]
        else:
            last_dt, last_val = None, np.nan
        state["series_meta"].append({"line": line, "label": label, "last_dt": last_dt, "last_val": last_val})

        if target is ax_left:
            state["left_lines"].append(line)
            if state["left_color"] is None:
                state["left_color"] = line.get_color()
                ax_left.tick_params(axis="y", labelcolor=state["left_color"])
                ax_left.set_ylabel(ylabel_left or label, color=state["left_color"])
        else:
            state["right_lines"].append(line)
            target.tick_params(axis="y", labelcolor=line.get_color())
            target.set_ylabel(ylabel_right or label, color=line.get_color())

        # ---------- indicators ----------
        if indicators:
            for ind in indicators:
                kind = ind.get("kind")
                which_ind = ind.get("which", "left")
                hide = bool(ind.get("hide", False))
                ax_ind = ax_left if which_ind == "left" else (target if which_ind == "right" else ax_left)
                style = dict(ind.get("style", {}))
                color = style.pop("color", None)

                # helpers for hiding series/scalars
                def _handle_series_hide(y, lbl):
                    yv = y.dropna()
                    if len(yv) == 0:
                        return True
                    _remember_hidden(lbl, float(yv.iloc[-1]), yv.index[-1])
                    return True

                def _handle_scalar_hide(val, lbl):
                    _remember_hidden(lbl, float(val) if np.isfinite(val) else np.nan, s_proc.index[-1] if len(s_proc) else None)
                    return True

                if kind == "sma":
                    y = _sma(s_proc, ind.get("window", 20))
                    lbl = ind.get("label", f"SMA({ind.get('window', 20)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or line.get_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

                elif kind == "ema":
                    y = _ema(s_proc, ind.get("span", 21))
                    lbl = ind.get("label", f"EMA({ind.get('span', 21)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or line.get_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

                elif kind == "boll":
                    m, up, lo = _boll(s_proc, ind.get("window", 20), ind.get("n", 2), ind.get("center", True))
                    if m is not None:
                        lblm = ind.get("label", f"Boll mid({ind.get('window',20)})")
                        if hide:
                            _handle_series_hide(m, lblm)
                        else:
                            (hm,) = ax_ind.plot(m.index, m.values, color=color or line.get_color(), linestyle="--", label=lblm, **style)
                            state["indicator_lines"].append(hm)
                            _remember_line(hm, lblm, m)
                    lblu = f"Boll +{ind.get('n',2)}σ"
                    lbll = f"Boll -{ind.get('n',2)}σ"
                    if not hide:
                        (hu,) = ax_ind.plot(up.index, up.values, color=color or line.get_color(), linestyle="-.", label=lblu, **style)
                        (hl,) = ax_ind.plot(lo.index, lo.values, color=color or line.get_color(), linestyle="-.", label=lbll, **style)
                        state["indicator_lines"] += [hu, hl]
                        _remember_line(hu, lblu, up)
                        _remember_line(hl, lbll, lo)
                    else:
                        _handle_series_hide(up, lblu)
                        _handle_series_hide(lo, lbll)

                elif kind == "rsi":
                    y = _rsi(s_proc, ind.get("window", 14))
                    lbl = ind.get("label", f"RSI({ind.get('window', 14)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)
                    ax_ind.axhline(30, color="gray", linestyle=":", linewidth=0.8)
                    ax_ind.axhline(70, color="gray", linestyle=":", linewidth=0.8)

                elif kind == "macd":
                    macd_line, signal_line, hist = _macd(s_proc, ind.get("fast", 12), ind.get("slow", 26), ind.get("signal", 9))
                    if hide:
                        _handle_series_hide(macd_line, "MACD")
                        _handle_series_hide(signal_line, "Signal")
                        continue
                    (hm,) = ax_ind.plot(macd_line.index, macd_line.values, color=color or _next_color(), label="MACD", **style)
                    (hs,) = ax_ind.plot(signal_line.index, signal_line.values, color=color or _next_color(), label="Signal", **style)
                    state["indicator_lines"] += [hm, hs]
                    _remember_line(hm, "MACD", macd_line)
                    _remember_line(hs, "Signal", signal_line)

                elif kind == "vol":
                    y = _roll_vol(s_proc, ind.get("window", 60), ind.get("returns", "abs"), ind.get("annualize", True))
                    lbl = ind.get("label", f"Vol({ind.get('window',60)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

                elif kind == "z":
                    y = _z(s_proc, ind.get("window", 60))
                    lbl = ind.get("label", f"Z({ind.get('window',60)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

                elif kind == "last":
                    s_valid2 = s_proc.dropna()
                    if len(s_valid2) == 0:
                        continue
                    last_dt2 = s_valid2.index[-1]
                    last_val2 = float(s_valid2.iloc[-1])
                    lbl = ind.get("label", f"Last({label})")
                    if hide:
                        _handle_scalar_hide(last_val2, lbl)
                        continue
                    style.setdefault("linestyle", ":")
                    style.setdefault("linewidth", 1.0)
                    h = ax_ind.axhline(y=last_val2, color=color or line.get_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    state["series_meta"].append({"line": h, "label": lbl, "last_dt": last_dt2, "last_val": last_val2})

                elif kind == "simple_avg":
                    s_valid2 = s_proc.dropna()
                    if len(s_valid2) == 0:
                        continue
                    avg_val = float(s_valid2.mean())
                    lbl = ind.get("label", f"Avg({label})")
                    if hide:
                        _handle_scalar_hide(avg_val, lbl)
                        continue
                    style.setdefault("linestyle", ":")
                    style.setdefault("linewidth", 1.0)
                    h = ax_ind.axhline(y=avg_val, color=color or line.get_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, pd.Series([avg_val], index=[s_valid2.index[-1]]))

                elif kind == "hurst":
                    H = _hurst_exponent(s_proc, ind.get("max_lag", 100))
                    if not np.isfinite(H):
                        continue
                    lbl = ind.get("label", "Hurst")
                    if hide:
                        _handle_scalar_hide(H, lbl)
                        continue
                    style.setdefault("linestyle", ":")
                    style.setdefault("linewidth", 1.0)
                    h = ax_ind.axhline(y=H, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, pd.Series([H], index=[s_proc.index[-1]]))

                elif kind == "hurst_roll":
                    y = _hurst_roll(s_proc, ind.get("window", 252), ind.get("max_lag", 100))
                    lbl = ind.get("label", f"H({ind.get('window',252)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

                elif kind == "half_life":
                    hl = _ar1_halflife(s_proc, ind.get("demean", True))
                    if not np.isfinite(hl):
                        continue
                    lbl = ind.get("label", "Half-life (steps)")
                    if hide:
                        _handle_scalar_hide(hl, lbl)
                        continue
                    style.setdefault("linestyle", ":")
                    style.setdefault("linewidth", 1.0)
                    h = ax_ind.axhline(y=hl, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, pd.Series([hl], index=[s_proc.index[-1]]))

                elif kind == "adf_p":
                    w = ind.get("window", None)
                    reg = ind.get("reg", "c")
                    y = _adf_pvalue_series(s_proc, window=w, reg=reg)
                    if isinstance(y, pd.Series):
                        lbl = ind.get("label", f"ADF p({w})" if w else "ADF p")
                        if hide:
                            _handle_series_hide(y, lbl)
                            continue
                        (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line(h, lbl, y)
                    else:
                        p = float(y)
                        if not np.isfinite(p):
                            continue
                        lbl = ind.get("label", "ADF p")
                        if hide:
                            _handle_scalar_hide(p, lbl)
                            continue
                        style.setdefault("linestyle", ":")
                        style.setdefault("linewidth", 1.0)
                        h = ax_ind.axhline(y=p, color=color or _next_color(), label=lbl, **style)
                        state["indicator_lines"].append(h)
                        _remember_line(h, lbl, pd.Series([p], index=[s_proc.index[-1]]))

                elif kind == "vr":
                    y = _variance_ratio(s_proc, k=ind.get("k", 5), window=ind.get("window", 252), returns=ind.get("returns", "simple"))
                    lbl = ind.get("label", f"VR(k={ind.get('k',5)})")
                    if hide:
                        _handle_series_hide(y, lbl)
                        continue
                    (h,) = ax_ind.plot(y.index, y.values, color=color or _next_color(), label=lbl, **style)
                    state["indicator_lines"].append(h)
                    _remember_line(h, lbl, y)

        # OU overlay
        if ou and isinstance(ou, dict) and ou.get("enable", False):
            _plot_ou(target, s_proc, ou)

        return line

    # ---------- legend ----------
    def legend(loc="best", valfmt="{:.2f}", show_date=False, sep=" — ", **kwargs):
        handles = state["left_lines"] + state["right_lines"] + state["indicator_lines"]
        meta_map = {m["line"]: m for m in state["series_meta"]}

        labels = []
        import numpy as np

        for h in handles:
            m = meta_map.get(h, None)
            base = h.get_label()
            if m is None:
                labels.append(base)
                continue
            lv = m["last_val"]
            try:
                lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
            except Exception:
                lv_text = str(lv)
            if show_date and m["last_dt"] is not None:
                lbl = f"{base}{sep}{lv_text} @ {_fmt_dt(m['last_dt'])}"
            else:
                lbl = f"{base}{sep}{lv_text}"
            labels.append(lbl)

        # Hidden info-only entries (from hide=True indicators)
        if state["hidden_meta"]:
            for hm in state["hidden_meta"]:
                lv = hm["last_val"]
                try:
                    lv_text = valfmt.format(float(lv)) if np.isfinite(float(lv)) else "NaN"
                except Exception:
                    lv_text = str(lv)
                if show_date and hm["last_dt"] is not None:
                    labels.append(f"{hm['label']}{sep}{lv_text} @ {_fmt_dt(hm['last_dt'])}")
                else:
                    labels.append(f"{hm['label']}{sep}{lv_text}")
                # dummy handle to align lengths
                handles.append(plt.Line2D([], [], color="none", label=""))

        # OU metrics (info-only)
        if state["ou_meta"]:
            labels.append("; ".join(state["ou_meta"]))
            handles.append(plt.Line2D([], [], color="none", label=""))

        ax_left.legend(handles, labels, loc=loc, **kwargs)

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
    }

    ax_right = None
    return plot, fig, ax_left, ax_right, legend
