import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd

import RVUtils.forex_factory_calendar as calendar_module
from RVUtils.forex_factory_calendar import ForexFactoryCalendarFetcher, ForexFactoryTheme


class _DummyResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class _DummySession:
    def __init__(self, payload_by_url: dict[str, str]) -> None:
        self.payload_by_url = payload_by_url
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, timeout: int):
        self.calls.append(url)
        return _DummyResponse(self.payload_by_url[url])


class _RecordingSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []
        self._attempt = 0

    def get(self, url: str, timeout: int):
        self.calls.append({"url": url, "proxies": dict(self.proxies)})
        self._attempt += 1
        if self._attempt == 1:
            raise RuntimeError("proxy blocked")
        return _DummyResponse(_sample_payloads()[url])


def _dateline(date_value: dt.date, tz_name: str) -> int:
    tzinfo = ZoneInfo(tz_name)
    return int(dt.datetime.combine(date_value, dt.time.min, tzinfo=tzinfo).timestamp())


def _date_cell(date_value: dt.date) -> str:
    return (
        '<td class="calendar__cell calendar__date">'
        f'{date_value.strftime("%a")} <span>{date_value.strftime("%b")} {date_value.day}</span>'
        "</td>"
    )


def _value_cell(css_class: str, value: str = "", span_class: str = "") -> str:
    if not value:
        return f'<td class="calendar__cell {css_class}"></td>'
    if span_class:
        return (
            f'<td class="calendar__cell {css_class}">'
            f'<span class="{span_class}">{value}<span class="icon icon--revised"></span></span>'
            "</td>"
        )
    return f'<td class="calendar__cell {css_class}"><span>{value}</span></td>'


def _event_row(
    *,
    event_id: int,
    date_value: dt.date | None,
    tz_name: str,
    time_label: str,
    currency: str,
    impact_suffix: str,
    title: str,
    actual: str = "",
    actual_class: str = "",
    forecast: str = "",
    previous: str = "",
    previous_class: str = "",
    detail_level: int = 1,
) -> str:
    attrs = [f'data-event-id="{event_id}"', 'class="calendar__row"']
    if date_value is not None:
        attrs.append(f'data-day-dateline="{_dateline(date_value, tz_name)}"')
    cells = []
    if date_value is not None:
        cells.append(_date_cell(date_value))
    cells.extend(
        [
            f'<td class="calendar__cell calendar__time">{time_label}</td>',
            f'<td class="calendar__cell calendar__currency">{currency}</td>',
            (
                '<td class="calendar__cell calendar__impact">'
                f'<span class="icon icon--ff-impact-{impact_suffix}"></span>'
                "</td>"
            ),
            (
                '<td class="calendar__cell calendar__event">'
                '<div class="calendar__event-wrapper">'
                '<span class="calendar__event-title-wrapper">'
                f'<span class="calendar__event-title">{title}</span>'
                "</span></div></td>"
            ),
            '<td class="calendar__cell calendar__sub"></td>',
            (
                '<td class="calendar__cell calendar__detail detail">'
                f'<a class="calendar__detail-link calendar__detail-link--level-{detail_level}"></a>'
                "</td>"
            ),
            _value_cell("calendar__actual", actual, actual_class),
            _value_cell("calendar__forecast", forecast),
            _value_cell("calendar__previous", previous, previous_class),
            '<td class="calendar__cell calendar__graph"></td>',
        ]
    )
    return f"<tr {' '.join(attrs)}>{''.join(cells)}</tr>"


def _week_html(tz_name: str, rows: list[str]) -> str:
    return (
        "<html><head><script>"
        f"window.FF = {{ timezone_name: '{tz_name}', weekstart: '1' }};"
        "</script></head><body><table>"
        f"{''.join(rows)}"
        "</table></body></html>"
    )


def _sample_payloads() -> dict[str, str]:
    tz_name = "America/New_York"
    week_one = _week_html(
        tz_name,
        [
            _event_row(
                event_id=1001,
                date_value=dt.date(2026, 3, 2),
                tz_name=tz_name,
                time_label="9:00am",
                currency="USD",
                impact_suffix="ora",
                title="FOMC Member Waller Speaks",
            ),
            _event_row(
                event_id=1006,
                date_value=dt.date(2026, 3, 4),
                tz_name=tz_name,
                time_label="8:15am",
                currency="USD",
                impact_suffix="ora",
                title="ADP Non-Farm Employment Change",
                actual="180K",
                forecast="160K",
                previous="155K",
            ),
            _event_row(
                event_id=1005,
                date_value=None,
                tz_name=tz_name,
                time_label="1:00pm",
                currency="USD",
                impact_suffix="yel",
                title="10-y Bond Auction",
                actual="4.30|2.5",
                previous="4.25|2.4",
            ),
            _event_row(
                event_id=1002,
                date_value=dt.date(2026, 3, 6),
                tz_name=tz_name,
                time_label="8:30am",
                currency="USD",
                impact_suffix="red",
                title="Non-Farm Employment Change",
                actual="200K",
                actual_class="better",
                forecast="160K",
                previous="151K",
                previous_class="revised better",
                detail_level=2,
            ),
            _event_row(
                event_id=1003,
                date_value=None,
                tz_name=tz_name,
                time_label="",
                currency="USD",
                impact_suffix="red",
                title="Unemployment Rate",
                actual="4.1%",
                actual_class="worse",
                forecast="4.0%",
                previous="4.0%",
                detail_level=2,
            ),
            _event_row(
                event_id=1004,
                date_value=None,
                tz_name=tz_name,
                time_label="",
                currency="USD",
                impact_suffix="red",
                title="Average Hourly Earnings m/m",
                actual="0.4%",
                actual_class="better",
                forecast="0.3%",
                previous="0.2%",
                detail_level=2,
            ),
        ],
    )
    week_two = _week_html(
        tz_name,
        [
            _event_row(
                event_id=2005,
                date_value=dt.date(2026, 3, 11),
                tz_name=tz_name,
                time_label="9:00am",
                currency="EUR",
                impact_suffix="ora",
                title="ECB President Lagarde Speaks",
            ),
            _event_row(
                event_id=2006,
                date_value=None,
                tz_name=tz_name,
                time_label="10:00am",
                currency="GBP",
                impact_suffix="ora",
                title="MPC Member Greene Speaks",
            ),
            _event_row(
                event_id=2007,
                date_value=None,
                tz_name=tz_name,
                time_label="11:00am",
                currency="CNY",
                impact_suffix="red",
                title="New Loans",
                actual="5200B",
                forecast="5000B",
                previous="900B",
            ),
            _event_row(
                event_id=2001,
                date_value=dt.date(2026, 3, 12),
                tz_name=tz_name,
                time_label="8:30am",
                currency="USD",
                impact_suffix="red",
                title="CPI m/m",
                actual="0.4%",
                actual_class="better",
                forecast="0.3%",
                previous="0.2%",
                detail_level=2,
            ),
            _event_row(
                event_id=2002,
                date_value=None,
                tz_name=tz_name,
                time_label="",
                currency="USD",
                impact_suffix="red",
                title="Core CPI m/m",
                actual="0.3%",
                forecast="0.3%",
                previous="0.2%",
                detail_level=2,
            ),
            _event_row(
                event_id=2003,
                date_value=dt.date(2026, 3, 13),
                tz_name=tz_name,
                time_label="8:30am",
                currency="USD",
                impact_suffix="red",
                title="Core PCE Price Index m/m",
                actual="0.3%",
                forecast="0.2%",
                previous="0.3%",
                detail_level=2,
            ),
            _event_row(
                event_id=2004,
                date_value=None,
                tz_name=tz_name,
                time_label="10:00am",
                currency="EUR",
                impact_suffix="ora",
                title="German CPI m/m",
                actual="0.2%",
                forecast="0.1%",
                previous="0.1%",
            ),
            _event_row(
                event_id=2008,
                date_value=None,
                tz_name=tz_name,
                time_label="11:45am",
                currency="USD",
                impact_suffix="ora",
                title="Flash Manufacturing PMI",
                actual="51.7",
                forecast="51.3",
                previous="50.9",
            ),
            _event_row(
                event_id=2009,
                date_value=None,
                tz_name=tz_name,
                time_label="1:30pm",
                currency="USD",
                impact_suffix="red",
                title="Building Permits m/m",
                actual="1.2%",
                forecast="0.4%",
                previous="-0.8%",
            ),
            _event_row(
                event_id=2010,
                date_value=None,
                tz_name=tz_name,
                time_label="4:30pm",
                currency="USD",
                impact_suffix="red",
                title="Crude Oil Inventories",
                actual="-2.4M",
                forecast="-1.2M",
                previous="-3.0M",
            ),
        ],
    )
    return {
        "https://www.forexfactory.com/calendar?week=mar2.2026": week_one,
        "https://www.forexfactory.com/calendar?week=mar9.2026": week_two,
    }


def test_fetch_week_parses_required_fields_and_metadata(tmp_path):
    session = _DummySession(_sample_payloads())
    fetcher = ForexFactoryCalendarFetcher(session=session, cache_dir=tmp_path / "html", core_base_dir=tmp_path / "core")

    frame = fetcher.fetch_week(dt.date(2026, 3, 2), use_cache=False, use_core=False, show_tqdm=False)

    assert {"Actual", "Forecast", "Previous", "TimestampNYC"}.issubset(frame.columns)
    assert list(frame["EventId"]) == [1001, 1006, 1005, 1002, 1003, 1004]

    nfp_row = frame.loc[frame["EventId"] == 1002].iloc[0]
    assert nfp_row["Actual"] == "200K"
    assert nfp_row["Forecast"] == "160K"
    assert nfp_row["Previous"] == "151K"
    assert nfp_row["ActualOutcome"] == "better"
    assert bool(nfp_row["PreviousRevised"]) is True
    assert nfp_row["PreviousRevisionDirection"] == "better"
    assert nfp_row["Impact"] == "high"
    assert nfp_row["DetailLevel"] == 2
    assert nfp_row["CalendarTimeZone"] == "America/New_York"
    assert nfp_row["Timestamp"] == pd.Timestamp("2026-03-06 13:30:00+00:00")
    assert nfp_row["TimestampNYC"] == pd.Timestamp("2026-03-06 08:30:00-0500", tz="America/New_York")

    speaker_row = frame.loc[frame["EventId"] == 1001].iloc[0]
    assert speaker_row["Actual"] == ""
    assert speaker_row["Forecast"] == ""
    assert speaker_row["Previous"] == ""

    unemployment_row = frame.loc[frame["EventId"] == 1003].iloc[0]
    assert unemployment_row["TimeLabel"] == "8:30am"
    assert unemployment_row["Timestamp"] == pd.Timestamp("2026-03-06 13:30:00+00:00")


def test_prepackaged_theme_filters_select_expected_rows(tmp_path):
    session = _DummySession(_sample_payloads())
    fetcher = ForexFactoryCalendarFetcher(session=session, cache_dir=tmp_path / "html", core_base_dir=tmp_path / "core")

    all_rows = fetcher.fetch_range("2026-03-02", "2026-03-15", use_cache=False, use_core=False, show_tqdm=False)
    global_macro = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.GLOBAL_MACRO,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert global_macro.equals(all_rows)

    fed = fetcher.fetch_range("2026-03-02", "2026-03-15", themes=ForexFactoryTheme.FED_SPEAKERS, use_cache=False, use_core=False, show_tqdm=False)
    assert fed["Title"].tolist() == ["FOMC Member Waller Speaks"]

    nfp = fetcher.fetch_range("2026-03-02", "2026-03-15", themes=ForexFactoryTheme.US_NFP, use_cache=False, use_core=False, show_tqdm=False)
    assert set(nfp["Title"]) == {
        "Non-Farm Employment Change",
        "Unemployment Rate",
        "Average Hourly Earnings m/m",
    }

    inflation = fetcher.fetch_range("2026-03-02", "2026-03-15", themes=ForexFactoryTheme.US_INFLATION, use_cache=False, use_core=False, show_tqdm=False)
    assert set(inflation["Title"]) == {"CPI m/m", "Core CPI m/m", "Core PCE Price Index m/m"}

    rates = fetcher.fetch_range("2026-03-02", "2026-03-15", themes=ForexFactoryTheme.US_RATES, use_cache=False, use_core=False, show_tqdm=False)
    assert set(rates["Title"]) == {"FOMC Member Waller Speaks", "10-y Bond Auction"}

    global_cb = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.GLOBAL_CENTRAL_BANK_SPEAKERS,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert set(global_cb["Title"]) == {
        "FOMC Member Waller Speaks",
        "ECB President Lagarde Speaks",
        "MPC Member Greene Speaks",
    }

    euro_inflation = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.EUROZONE_INFLATION,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert set(euro_inflation["Title"]) == {"German CPI m/m"}

    china_credit = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.CHINA_CREDIT,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert set(china_credit["Title"]) == {"New Loans"}

    housing = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.US_HOUSING,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert set(housing["Title"]) == {"Building Permits m/m"}

    energy = fetcher.fetch_range(
        "2026-03-02",
        "2026-03-15",
        themes=ForexFactoryTheme.ENERGY,
        use_cache=False,
        use_core=False,
        show_tqdm=False,
    )
    assert set(energy["Title"]) == {"Crude Oil Inventories"}


def test_fetch_range_clips_dates_and_reuses_cache(tmp_path):
    session = _DummySession(_sample_payloads())
    core_dir = tmp_path / "core"
    fetcher = ForexFactoryCalendarFetcher(session=session, cache_dir=tmp_path / "html", core_base_dir=core_dir)

    frame = fetcher.fetch_range("2026-03-06", "2026-03-12")
    assert set(frame["Date"]) == {dt.date(2026, 3, 6), dt.date(2026, 3, 11), dt.date(2026, 3, 12)}
    assert "Core PCE Price Index m/m" not in set(frame["Title"])
    assert len(session.calls) == 2
    assert list((core_dir / "date=2026-03-06").glob("*.parquet"))
    assert list((core_dir / "date=2026-03-12").glob("*.parquet"))

    cached = fetcher.fetch_range("2026-03-06", "2026-03-12")
    assert cached.equals(frame)
    assert len(session.calls) == 2


def test_fetch_range_uses_tqdm_when_enabled(monkeypatch, tmp_path):
    session = _DummySession(_sample_payloads())
    fetcher = ForexFactoryCalendarFetcher(session=session, cache_dir=tmp_path / "html", core_base_dir=tmp_path / "core")
    captured = {}

    def _fake_tqdm(items, total=None, desc=None, dynamic_ncols=None):
        captured["total"] = total
        captured["desc"] = desc
        captured["dynamic_ncols"] = dynamic_ncols
        return items

    monkeypatch.setattr(calendar_module, "tqdm", _fake_tqdm)

    frame = fetcher.fetch_range("2026-03-02", "2026-03-15", use_core=False, use_cache=False, show_tqdm=True)

    assert not frame.empty
    assert captured == {
        "total": 2,
        "desc": "Fetching Forex Factory weeks",
        "dynamic_ncols": True,
    }


def test_fetcher_rotates_nord_proxy_on_retry(monkeypatch, tmp_path):
    session = _RecordingSession()
    fetcher = ForexFactoryCalendarFetcher(
        session=session,
        cache_dir=tmp_path / "html",
        core_base_dir=tmp_path / "core",
        proxy_rotation_enabled=True,
    )

    state = {
        "lock": calendar_module.threading.RLock(),
        "initialized": True,
        "hosts": ["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"],
        "cycler": calendar_module.itertools.cycle(["atlanta.us.socks.nordhold.net", "chicago.us.socks.nordhold.net"]),
        "socks_enabled": True,
        "ttl": 0,
        "proxies": None,
        "host": None,
        "chosen_at": 0.0,
    }
    monkeypatch.setattr(calendar_module, "_init_proxy_state", lambda: state)
    monkeypatch.setattr(
        calendar_module,
        "_build_socks5h",
        lambda host: {
            "http": f"socks5h://user:pass@{host}:1080",
            "https": f"socks5h://user:pass@{host}:1080",
        },
    )
    monkeypatch.setattr(calendar_module, "_preflight_proxy", lambda proxies, timeout=6: True)

    frame = fetcher.fetch_week("2026-03-02", use_cache=False, use_core=False)

    assert not frame.empty
    assert len(session.calls) == 2
    assert session.calls[0]["proxies"]["http"].endswith("@atlanta.us.socks.nordhold.net:1080")
    assert session.calls[1]["proxies"]["http"].endswith("@chicago.us.socks.nordhold.net:1080")


def test_fetch_year_and_fetch_years_delegate_range(monkeypatch, tmp_path):
    fetcher = ForexFactoryCalendarFetcher(cache_dir=tmp_path / "html", core_base_dir=tmp_path / "core", proxy_rotation_enabled=False)
    captured: list[tuple[dt.date, dt.date, int]] = []

    def _fake_fetch_range(start_date, end_date, **kwargs):
        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        captured.append((start, end, kwargs["bulk_chunk_weeks"]))
        return pd.DataFrame(
            [
                {
                    "EventId": len(captured),
                    "WeekAnchor": start - dt.timedelta(days=start.weekday()),
                    "Date": start,
                    "TimeLabel": "",
                    "Timestamp": pd.NaT,
                    "CalendarTimeZone": "UTC",
                    "Currency": "USD",
                    "Impact": "high",
                    "ImpactRank": 3,
                    "Title": f"Year {start.year}",
                    "DetailLevel": pd.NA,
                    "Actual": "",
                    "Forecast": "",
                    "Previous": "",
                    "ActualOutcome": None,
                    "PreviousRevised": False,
                    "PreviousRevisionDirection": None,
                    "SourceURL": "local",
                }
            ]
        )

    monkeypatch.setattr(fetcher, "fetch_range", _fake_fetch_range)

    single = fetcher.fetch_year(2026, bulk_chunk_weeks=26)
    combined = fetcher.fetch_years([2025, 2026], bulk_chunk_weeks=10)
    per_year = fetcher.fetch_years([2025, 2026], combine=False, bulk_chunk_weeks=8)

    assert captured[0] == (dt.date(2026, 1, 1), dt.date(2026, 12, 31), 26)
    assert captured[1] == (dt.date(2025, 1, 1), dt.date(2025, 12, 31), 10)
    assert captured[2] == (dt.date(2026, 1, 1), dt.date(2026, 12, 31), 10)
    assert captured[3] == (dt.date(2025, 1, 1), dt.date(2025, 12, 31), 8)
    assert captured[4] == (dt.date(2026, 1, 1), dt.date(2026, 12, 31), 8)
    assert single["Title"].tolist() == ["Year 2026"]
    assert set(combined["Title"]) == {"Year 2025", "Year 2026"}
    assert set(per_year) == {2025, 2026}


def test_parse_timestamp_handles_dst_fall_back_ambiguity(tmp_path):
    fetcher = ForexFactoryCalendarFetcher(cache_dir=tmp_path / "html", core_base_dir=tmp_path / "core")

    parsed = fetcher._parse_timestamp(
        event_date=dt.date(2022, 11, 6),
        time_label="1:00am",
        calendar_timezone="America/New_York",
    )

    assert parsed == pd.Timestamp("2022-11-06 06:00:00+00:00")
