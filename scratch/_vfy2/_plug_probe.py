
import importlib, sys, types
SRC = 'C:/Users/chris/clee/ARBS-dd/SDRUtils/dealer_direction/upfront.py'
OLD = '# --- internals ---'
NEW = '# --- internals ---'
src = open(SRC, encoding="utf-8").read()
if OLD != NEW:
    src = src.replace(OLD, NEW)
pkg = importlib.import_module("SDRUtils.dealer_direction")
mod = types.ModuleType("SDRUtils.dealer_direction.upfront")
mod.__file__ = SRC
mod.__package__ = "SDRUtils.dealer_direction"
sys.modules["SDRUtils.dealer_direction.upfront"] = mod
exec(compile(src, SRC, "exec"), mod.__dict__)
setattr(pkg, "upfront", mod)
