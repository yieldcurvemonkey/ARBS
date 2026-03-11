import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "SDRUtils" / "_swappulse_scripts" / "ingest_ustrv.py"
SPEC = spec_from_file_location("ingest_ustrv_test", MODULE_PATH)
assert SPEC and SPEC.loader
ingest_module = module_from_spec(SPEC)
SPEC.loader.exec_module(ingest_module)


def test_parse_args_service_backfill_defaults_to_five_days(monkeypatch):
    monkeypatch.delenv("SWAPPULSE_USTRV_SERVICE_BACKFILL_DAYS", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest_ustrv.py", "--mode", "service"],
    )

    args = ingest_module.parse_args()

    assert args.mode == "service"
    assert args.service_backfill_days == 5


def test_parse_args_service_backfill_days_flag_overrides_default(monkeypatch):
    monkeypatch.delenv("SWAPPULSE_USTRV_SERVICE_BACKFILL_DAYS", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ingest_ustrv.py", "--mode", "service", "--service-backfill-days", "7"],
    )

    args = ingest_module.parse_args()

    assert args.service_backfill_days == 7
