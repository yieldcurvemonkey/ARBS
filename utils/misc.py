from decimal import Decimal, ROUND_HALF_UP
import math
import pandas as pd


def human_format(
    n,
    decimals: int = 1,
    system: str | list[str] = "finance",  # "finance" | "si" | "iec" | custom list like ["","k","M","B"]
    signed: bool = False,
    unit: str = "",
    strip_zeros: bool = True,
    rounding: str = "half_up",  # "half_up" or "bankers"
) -> str:
    """
    Examples:
        human_format(100000) -> "100k"
        human_format(1523400, decimals=1) -> "1.5M"
        human_format(-9876, decimals=2) -> "-9.88k"
        human_format(1536, system="iec") -> "1.5Ki"
        human_format(100000, unit="bps") -> "100kbps"
    """
    if n is None or (isinstance(n, float) and (math.isnan(n) or math.isinf(n))):
        return str(n)

    # suffix sets + base
    if isinstance(system, list):
        suffixes, base = system, 1000
    else:
        if system == "finance":
            suffixes, base = ["", "k", "M", "B", "T", "Q"], 1000
        elif system == "si":
            suffixes, base = ["", "k", "M", "G", "T", "P", "E"], 1000
        elif system == "iec":
            suffixes, base = ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei"], 1024
        else:
            raise ValueError("system must be 'finance', 'si', 'iec', or a custom list of suffixes")

    num = float(n)
    neg = num < 0
    num_abs = abs(num)

    # choose magnitude
    mag = 0
    while num_abs >= base and mag < len(suffixes) - 1:
        num_abs /= base
        mag += 1

    scaled = -num_abs if neg else num_abs

    # rounding (avoid banker's rounding by default)
    quant = Decimal(1).scaleb(-decimals)  # 10**(-decimals)
    dec_scaled = Decimal(str(scaled))
    if rounding == "half_up":
        dec_scaled = dec_scaled.quantize(quant, rounding=ROUND_HALF_UP)
    else:  # python default (bankers)
        dec_scaled = Decimal(str(round(float(dec_scaled), decimals)))

    s = f"{dec_scaled:.{decimals}f}" if decimals > 0 else f"{int(dec_scaled)}"
    if strip_zeros and "." in s:
        s = s.rstrip("0").rstrip(".")
    if signed and not s.startswith("-"):
        s = "+" + s

    return f"{s}{suffixes[mag]}{unit}"
