
import importlib, sys, types
SRC = 'C:\\Users\\chris\\clee\\ARBS-dd\\SDRUtils\\dealer_direction\\upfront.py'
OLD = '    if mid_sigma_bps is not None and not np.isfinite(float(mid_sigma_bps)):'
NEW = '    if False:'
src = open(SRC, encoding="utf-8").read()
if OLD not in src:
    raise SystemExit("MUTATION PATTERN NOT FOUND")
if OLD != NEW:
    assert src.count(OLD) == 1, "pattern is not unique: %d" % src.count(OLD)
src = src.replace(OLD, NEW)
pkg = importlib.import_module("SDRUtils.dealer_direction")
mod = types.ModuleType("SDRUtils.dealer_direction.upfront")
mod.__file__ = SRC
mod.__package__ = "SDRUtils.dealer_direction"
sys.modules["SDRUtils.dealer_direction.upfront"] = mod
exec(compile(src, SRC, "exec"), mod.__dict__)
setattr(pkg, "upfront", mod)
