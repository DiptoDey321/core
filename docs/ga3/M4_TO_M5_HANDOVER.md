# GA3 — M4 Implementation and M5 Integration Handover

Repository inspection and test reruns: **29 October 2026**.

This document describes the local implementation at the Git state in section I.
Sections A–F describe existing code. Section G proposes the M5 action contract
and implementation steps; that action does **not** exist yet.

## A. Project overview

The feature finds the cheapest continuous time to run an appliance for a chosen
duration within a chosen search window. For example, it can recommend which
two hours in an evening have the lowest average electricity price. This helps
users plan flexible electricity use. It does not calculate household bills,
predict consumption, control an appliance, or guarantee actual savings.

| Part | Responsibility | Current state |
| --- | --- | --- |
| M4 | Calculate the cheapest period from normalized price intervals | Implemented, with standalone calculation tests |
| Local dashboard | Show sample prices and exercise the real M4 function | Implemented as a separate development tool |
| M5 | Fetch Nord Pool prices and expose the calculation as a Home Assistant action | Still to implement |
| M6 | Verify the full action flow and existing integration behavior | Still to complete |

M5 should reuse M4 directly. There is no need to implement a second optimizer
or move the demo server into Home Assistant.

## B. M4 implementation

### Files and interface

Calculation: `homeassistant/components/nordpool/cheapest_period.py`.
Tests: `tests/components/nordpool/test_cheapest_period.py`.

The exact public function signature is:

```python
def find_cheapest_period(
    intervals: Sequence[PriceInterval],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
) -> CheapestPeriod:
```

Both records are frozen dataclasses:

```python
@dataclass(frozen=True)
class PriceInterval:
    start: datetime
    end: datetime
    price: float

@dataclass(frozen=True)
class CheapestPeriod:
    start: datetime
    end: datetime
    average_price: float
```

Inputs must be actual `PriceInterval` instances in a sequence, such as a list
or tuple. A list of JSON dictionaries is not the calculator's interface.
Timestamps must be timezone-aware `datetime` objects. Prices are already in
the chosen **currency/kWh**. The function accepts finite integers or floats
for price, including zero and negative values; booleans are rejected.
The result contains UTC timestamps and a duration-weighted average price.
Currency itself is not stored or validated by M4, so M5 must keep it consistent.

### How selection works

1. Normalize window timestamps to UTC and require `window_end > window_start`.
2. Require a positive `timedelta` duration no longer than the elapsed window.
3. Validate and normalize every supplied interval, including intervals outside
   the window. Require positive interval lengths and finite numeric prices.
4. Sort a new list by start time and reject overlapping intervals. Duplicate
   intervals count as overlaps. Adjacent intervals are allowed.
5. Keep only intervals fully contained in the search window.
6. Try each eligible interval as a candidate start. Extend through adjacent
   intervals while each next start equals the preceding end. Stop at a gap
   or when adding an interval would exceed the requested duration.
7. Compare candidates only when their combined elapsed duration matches the
   requested duration exactly. Keep the smallest average. Equal computed
   averages retain the earliest start because candidates are visited in order.

**Whole intervals are essential:** M4 does not clip a record to the search
window, split an interval, round the duration, or start inside an interval.
A 90-minute run cannot be built from hourly records. The same duration can fit
six adjacent 15-minute records. Gaps are allowed in the input, but a candidate
cannot cross one; a later complete run can still win.

For candidate duration `D`, interval durations `d_i`, and prices `p_i`:

```text
average_price = sum(p_i × d_i / D)
```

The implementation uses `math.fsum` to sum weighted terms. It uses ordinary
floating-point comparisons, with no approximate tie tolerance. A 15-minute
interval priced at 4 followed by 45 minutes priced at 0 has average
`4 × 15/60 + 0 × 45/60 = 1`, not 2. The average assumes equal energy use per
unit of elapsed time; no appliance load profile is provided.

Inputs are not modified. The candidate search has quadratic worst-case work
in the number of eligible intervals; large search horizons would need review.

### Worked example

The M4 test and dashboard evening sample use 1 January 2026, UTC:

| Interval | Example price, SEK/kWh |
| --- | ---: |
| 17:00–18:00 | 3 |
| 18:00–19:00 | 1 |
| 19:00–20:00 | 1 |
| 20:00–21:00 | 4 |

For window 17:00–21:00 and duration two hours, candidate averages are 2,
1, and 2.5. M4 returns `start=18:00 UTC`, `end=20:00 UTC`,
`average_price=1.0`. These are synthetic prices.

### Errors

`CheapestPeriodError` subclasses `ValueError` and is the intended public
validation/calculation error. Explicit checks cover:

- Naive or non-datetime timestamps.
- Empty or reversed windows; non-`timedelta`, non-positive, or oversized duration.
- Records that are not `PriceInterval` instances.
- Empty or reversed intervals; nonnumeric, boolean, NaN, or infinite prices.
- Any overlapping records, even outside the search window.
- No exact continuous candidate, including empty data, gaps, partial-window
  exclusion, and durations requiring interval splitting.

The unavailable-period message is
`No continuous period of complete intervals matches the requested duration`.
It does not distinguish missing prices from an incompatible duration.
Transport parsing is outside M4: malformed JSON or timestamp strings must be
handled by the caller. The function is not a general sanitizer for arbitrary
Python objects; honor its sequence and record contract.

## C. Electricity price data

### Existing retrieval paths

The integration uses `pynordpool==0.4.0`, pinned in
`homeassistant/components/nordpool/manifest.json`. The installed client points
to Nord Pool's Data Portal API at
`https://dataportal-api.nordpoolgroup.com/api`. This handover inspected local
client code and fixture-backed tests; no live price request was made.

| Location | Existing function or method | Purpose |
| --- | --- | --- |
| `services.py` | `async_setup_services()` | Register existing response-only actions |
| Inside that setup function | `get_service_params()` | Resolve entry, client, date, currency, areas, resolution |
| Inside that setup function | `get_prices_for_date()` | Call `client.async_get_delivery_period(...)` |
| Inside that setup function | `get_price_indices_for_date()` | Call `client.async_get_price_indices(..., resolution=...)` |
| Inside that setup function | `get_prices()` | Catch retrieval errors and serialize per-area records |
| `coordinator.py` | `_async_setup()` | Fetch yesterday/today and attempt tomorrow using `async_get_delivery_periods(...)` |
| `coordinator.py` | `_api_call(days)` | Fetch a delivery date relative to current Nord Pool time |
| `coordinator.py` | `get_data_current_day()`, `get_data_tomorrow()` | Access cached daily data |
| `coordinator.py` | `merge_price_entries()` | Return sorted entries from cached days |

The service helpers above are **nested functions**, not importable public
helpers. M5 can add its handler in the same setup scope or carefully extract
shared retrieval logic while retaining the existing action behavior.
`get_service_params()` currently requires `date`; a new window-based action
cannot use it unchanged.

### Raw JSON, client objects, and action output

`tests/components/nordpool/fixtures/delivery_period_today.json` starts with:

```json
{
  "deliveryDateCET": "2025-10-01",
  "multiAreaEntries": [
    {
      "deliveryStart": "2025-09-30T22:00:00Z",
      "deliveryEnd": "2025-09-30T22:15:00Z",
      "entryPerArea": {"SE3": 556.68, "SE4": 642.22}
    }
  ]
}
```

This is an excerpt, not the complete response. The client converts each entry
to `DeliveryPeriodEntry(start: datetime, end: datetime, entry: dict[str, float])`.
`async_get_delivery_period()` returns `DeliveryPeriodData`, whose `entries`
is a list of those objects, alongside `raw`, `requested_date`, `updated_at`,
`currency`, and other daily metadata. `async_get_price_indices()` returns
`PriceIndicesData` with the same entry structure and a `resolution` field.
Its raw JSON uses `multiIndexEntries`; see `indices_15.json` and
`indices_60.json`.

`async_get_delivery_periods()` returns `DeliveryPeriodsData`, whose `entries`
is a dictionary from `date` to `DeliveryPeriodData`. Do not confuse that
dictionary with the single-day list. The coordinator stores this multi-day
object in `entry.runtime_data.data`.

The existing `get_prices()` action adapter produces a different structure:

```json
{
  "SE3": [
    {
      "start": "2025-09-30T22:00:00+00:00",
      "end": "2025-09-30T22:15:00+00:00",
      "price": 556.68
    }
  ]
}
```

That excerpt is confirmed by `snapshots/test_services.ambr`. Existing price
actions return prices without unit conversion. Prefer the typed client entries
for M5 rather than serializing through an action and then parsing its output.

### Units and conversion

Raw client prices are currency/MWh. M4 expects currency/kWh:

```text
price_per_kWh = price_per_MWh / 1000
556.68 SEK/MWh = 0.55668 SEK/kWh
```

This matches the existing `/ 1000` conversion in `sensor.py`, including
`validate_prices()` and the average-price sensor. Select one area from
`price_entry.entry[area]`, divide once, and build
`PriceInterval(price_entry.start, price_entry.end, price_entry.entry[area] / 1000)`.
Do not divide demo prices again: they already represent SEK/kWh. Unit conversion
does not change currency. Ask the client for the selected currency; do not
combine days or records with inconsistent currencies. Existing test mocks can
return the same fixture for different currency parameters, so test parameter
validation and real unit semantics separately.

### Timestamps and delivery dates

The client parses ISO strings into aware datetimes; fixture `Z` timestamps are
UTC. M4 converts all timestamps to UTC before comparing or subtracting them,
including across a repeated daylight-saving hour.

The coordinator's `NORDPOOL_TIMEZONE` is `Europe/Oslo` and
`get_nordpool_current_time()` uses that timezone. The fixture's delivery day
1 October begins at 22:00 UTC on 30 September. M5 must enumerate the relevant
**delivery dates**, not merely the UTC dates of the boundaries. The installed
client formats the date from the supplied datetime; it does not first convert
that datetime to the Nord Pool timezone.

Define the search window with aware timestamps and treat the end as the end
boundary: an interval ending at `window_end` is allowed. Convert the window to
the delivery timezone when choosing daily requests, then use aware UTC
boundaries for calculation. Cross-midnight windows may need more than one
daily response. Calendar days around DST can have 23 or 25 elapsed hours;
do not generate intervals by assuming 24 fixed hourly prices per day.

## D. Visual dashboard

All files are in `devtools/nordpool_cheapest_period_demo/`:

| File | Responsibility |
| --- | --- |
| `README.md` | Run instructions, features, and limitations |
| `server.py` | Loopback HTTP server, static assets, sample data, and M4 adapter |
| `index.html` | Form, chart container, recommendation cards, and JSON editor |
| `app.js` | Fetch requests, SVG chart, timezone formatting, controls, and error display |
| `style.css` | Page, chart, card, and responsive styling |
| `test_server.py` | Six HTTP adapter tests using the actual calculator |
| `__init__.py` | Package marker/docstring |

The browser requests `GET /api/scenarios`. `sample_scenarios()` supplies
four synthetic scenarios: Simple evening, Full day, 15-minute prices
(including negatives), and Missing prices. They use 1 January 2026, not live
Nord Pool data.

The frontend sends `POST /api/calculate` with `intervals`, `window_start`,
`window_end`, and `duration_minutes`. `server.calculate()` parses ISO datetimes,
constructs real `PriceInterval` records, builds a `timedelta`, and directly
calls `find_cheapest_period()`. It returns `start`, `end`, `average_price`,
and `duration_minutes`. M4 errors become HTTP 400 JSON with `source: "M4"`;
malformed transport data has separate error handling.

The server loads the actual calculator file with `importlib.util` to avoid
starting integration imports. This is a demo convenience; M5 should use a
normal relative Python import. JavaScript does not calculate the cheapest run.

Implemented controls and display behavior:

- One-, two-, and three-hour buttons and custom minutes; automatic recalculation
  on selection/change, plus **Find best time**.
- Elapsed-time bar widths, visible gaps, negative prices, green recommendation
  highlights, and hover/tap/keyboard-focus details with timestamps and offsets.
- UTC, Europe/Stockholm, and browser-local timezone display. Display changes
  preserve the calculation timestamps.
- Graph-only daypart views when supported by the data. Changing **View** does
  not narrow the allowed search window.
- Collapsed **Developer/Test data** JSON editor with an **Apply test data** button.
  Loading another scenario replaces editor contents. Duration comes from the form.
- Pending or invalid requests clear old recommendations; stale responses are ignored.

The dashboard has no live API connection, consumption model, bill calculation,
or savings estimate. HTTP tests do not prove all browser rendering behavior.

## E. How to run M4 and the dashboard

Use the repository's Python environment, not an unrelated system interpreter.
For a new checkout/environment, run the required `script/setup` first, following
`AGENTS.md`; it installs development dependencies and configures the environment.
The commands below use the existing local `.venv`.

1. Navigate and activate:

   ```sh
   cd /Users/aveennoor/home-assistant-core
   source .venv/bin/activate
   python3 --version
   ```

2. Run M4 tests:

   ```sh
   uv run --no-sync pytest -q tests/components/nordpool/test_cheapest_period.py
   ```

3. Start the local server in that terminal:

   ```sh
   python3 devtools/nordpool_cheapest_period_demo/server.py
   ```

   Expected startup line: `Nord Pool M4 demo: http://127.0.0.1:8765`.

4. Open `http://127.0.0.1:8765` in a browser. On macOS, from another terminal:

   ```sh
   open http://127.0.0.1:8765
   ```

5. **Simple evening** loads automatically. Use **Sample scenario** to reload
   it or select another example. Keep **Display timezone** at **UTC** for the
   expected times below.
6. Select **2 hours**. Custom minutes recalculate on change; **Find best time**
   also submits. Set 60 minutes to compare the shorter result.
7. Verify the two-hour recommendation is **18:00–20:00 UTC**, average
   **1 SEK/kWh**, with the matching green highlight. For one hour, the earliest
   equal-price result is **18:00–19:00 UTC**. With the 15-minute scenario and
   60 minutes, expect **17:45–18:45 UTC**, average **−0.5 SEK/kWh**.
8. Stop the server with **Ctrl+C** in its terminal.

| Problem | What to do |
| --- | --- |
| `uv` or `pytest` unavailable | Activate `.venv`; for a new environment, run `script/setup` |
| Python syntax error in the demo | Check `python3 --version`; this repository requires Python 3.14 syntax support |
| `uv` warns about Python version | This checkout requests 3.14.5; the inspected environment is 3.14.3. Align the environment before final integration validation |
| Setup cannot download requested Python | `AGENTS.md` directs upgrading outdated uv with `curl -LsSf https://astral.sh/uv/install.sh \| sh`, then rerunning `script/setup` |
| Port already in use | Run `python3 devtools/nordpool_cheapest_period_demo/server.py --port 8766` and open `http://127.0.0.1:8766` |
| Blank chart or failed requests | Start the server and use its HTTP URL; opening `index.html` directly does not provide the API routes |
| No exact uninterrupted period | Try 120 rather than 90 minutes with hourly data, or choose finer intervals; gaps cannot be crossed |
| Displayed times differ | Choose UTC; Stockholm display shifts the same instants by the applicable offset |
| Edited data does not appear | Click **Apply test data**; ensure valid JSON and timestamps with `Z` or explicit offsets |
| Python changes do not appear | Restart the server; the calculator module is loaded at startup |

The server binds only to `127.0.0.1`. No additional packages are needed for
the demo itself, but repository pytest runs require the development environment.

## F. Test results and verification

The request previously reported **34 M4 tests and 6 demo tests**. Both counts
were independently rerun successfully for this handover on 29 October 2026.

| Command, from repository root with `.venv` activated | Observed result |
| --- | --- |
| `uv run --no-sync pytest -q tests/components/nordpool/test_cheapest_period.py` | `34 passed in 0.46s` |
| `python3 -m unittest discover -s devtools/nordpool_cheapest_period_demo -p 'test_*.py'` | `Ran 6 tests`, `OK` |
| `uv run --no-sync pytest -q tests/components/nordpool/test_services.py` | `10 passed in 0.90s`; `6 snapshots passed` |

Durations vary by machine. The uv commands emitted a Python-version warning:
`.python-version` requests 3.14.5, while `.venv/pyvenv.cfg` reports 3.14.3.
These were successful runs using `--no-sync`, not proof of validation in the
requested patch-version environment. No environment rebuild was performed.

M4's 34 collected cases consist of:

- Ten successful parameterized cases: hourly example, earliest tie, mixed-length
  weighted average, quarter-hour prices, negative prices, partial/outside-window
  exclusion, valid run after a gap, unsorted input, and overlapping candidates.
  These also assert that the input sequence is unchanged.
- Twenty-three error cases: empty data, gap, no splitting/rounding/clipping,
  overlaps/duplicates (including outside the window), reversed/empty records,
  NaN/infinities/boolean prices, zero/negative/oversized durations,
  empty/reversed windows, and naive window/record timestamps.
- One timezone test covering Stockholm's repeated hour on 25 October 2026,
  elapsed-time arithmetic, and UTC result boundaries.

Demo tests cover the real function being called, sample endpoint data,
quarter-hour negative prices, changed prices and durations, M4 error propagation,
static assets, forbidden file access, and malformed JSON. Several methods use
subtests; the unittest method count remains six.

Existing action tests cover casing, single/multiple areas, configured defaults,
authentication/connection/timeout errors, empty responses, unavailable entries,
and 15-/60-minute price-index responses. They do not test the future M5 action.

Not verified here: live Nord Pool availability, a running Home Assistant UI
calling the future action, browser interaction/rendering, the full Nord Pool
test suite, or M6 end-to-end behavior. Additional M4 guard branches, spring DST,
cross-midnight action retrieval, and multi-day missing-data policies need further
tests as appropriate.

`uv run --no-sync prek run --all-files` was also attempted. Ruff check/format,
codespell, zizmor, JSON validation, branch protection, yamllint, and Prettier
passed. Mypy failed because both `homeassistant/util/event_type.py` and
`homeassistant/util/event_type.pyi` were identified as the same module. The run
was interrupted during the subsequent repository-wide pylint scan; pylint and
later hooks have no completed result. The all-files checks therefore did **not**
pass as a whole. No unrelated fixes were made.

The new handover file was checked separately with
`uv run --no-sync prek run prettier --files docs/ga3/M4_TO_M5_HANDOVER.md`,
which passed. Untracked files are not automatically included in the all-files
tracked-file scan, so that scan is not validation of the untracked M4 code.

## G. M5 integration instructions

### 1. Read the current action conventions first

Start with `homeassistant/components/nordpool/services.py`, especially
`async_setup_services()`, `get_service_params()`, `get_prices()`,
`SERVICE_GET_PRICES_SCHEMA`, `_validate_areas()`, and both `async_register()`
calls. Read `services.yaml` and `strings.json` for field descriptions and error
translations. `__init__.py:async_setup()` already calls `async_setup_services()`;
registering another action there should not require a new setup path.

Read `coordinator.py` for the existing client, cache, delivery timezone, and
missing-tomorrow handling. Prefer reusing these retrieval patterns and typed
client entries. Do not scrape sensor states to reconstruct intervals.

### 2. Define the new action contract

Add **`nordpool.get_cheapest_period`**. The following is a **proposed minimum
contract**, not an implemented or confirmed assignment specification:

| Proposed field | Meaning and validation |
| --- | --- |
| `config_entry` | Required Nord Pool config-entry selector, following existing actions |
| `area` | Required single market area, normalized uppercase and validated against `pynordpool.AREAS` |
| `window_start` | Required aware timestamp for earliest allowed interval start |
| `window_end` | Required aware timestamp for latest allowed interval end |
| `duration_minutes` | Required positive integer, converted to `timedelta(minutes=...)` |
| `currency` | Optional supported currency; default to the selected entry's currency |

Agree the exact field names and single-area versus per-area response with the
team before treating this as final. Existing actions use plural `areas` and
support multiple areas; a single-area first version avoids ambiguity but is a
new contract decision. If area is optional, specify what happens when the
configured entry contains several areas rather than silently choosing one.
Decide whether requested areas must also be configured on the selected entry.

Use a Voluptuous schema and appropriate existing Home Assistant validators.
Check timestamp awareness explicitly; do not silently assume naive input is UTC.
Validate the window ordering and elapsed duration, then let M4 enforce its
calculation rules. A positive duration can still be unavailable when it cannot
be composed of whole returned intervals.

### 3. Select the configured entry

Follow the existing call:

```python
entry = service.async_get_config_entry(hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY])
client = entry.runtime_data.client
```

This helper already provides the existing not-found/not-loaded validation
behavior tested in `test_service_call_config_entry_bad_state()`.
`manifest.json` currently declares `single_config_entry: true`, but use the
explicit selector convention instead of relying on whichever entry is first.

### 4. Retrieve all needed prices

Use `client.async_get_delivery_period(target_date, Currency(currency), [area])`
for the delivery-price path already used by `get_prices_for_date()`.
Alternatively, reuse `async_get_price_indices()` if an explicitly selected
resolution is required; existing schemas allow 15, 30, and 60 minutes.
Do not add a resolution argument to `async_get_delivery_period()`—it has none.

Choose delivery dates using the Nord Pool timezone as described in section C.
Fetch each relevant day once, collect its entries, and preserve the actual
start/end timestamps. A cache-based alternative can reuse
`entry.runtime_data.merge_price_entries()`, but must account for its limited
cached days and configured areas/currency. It does not fetch an arbitrary window.
`_api_call(days)` is a relative-day private method, not an arbitrary-date API.

Decide and test the data-completeness policy. The recommended conservative
behavior is to report unavailable prices if a requested delivery day is missing,
including unpublished tomorrow prices. M4 itself will happily select a valid run
from a partially covered window, so M5 must enforce stricter coverage if promised.
Do not silently shorten the requested window or fabricate prices.

Avoid collecting the same day's entries twice: duplicate intervals cause an
M4 overlap error. Do not mix delivery prices and price indices for the same
times. Preserve gaps and let them block continuous candidates.

### 5. Adapt entries and call M4

Import normally from `.cheapest_period`. For one selected area, create one
`PriceInterval` per entry and divide raw prices by 1000 exactly once. The
calculation is synchronous and operates on already fetched in-memory data.

The following **pseudocode** shows the real calculator interface after entry
selection, schema validation, daily retrieval, and coverage checks. Those earlier
steps are deliberately not represented by invented helper APIs. `price_entries`
means the merged list of actual client `DeliveryPeriodEntry` objects;
`window_start`/`window_end` are validated aware datetimes.

```python
from datetime import timedelta

from homeassistant.exceptions import ServiceValidationError

from .cheapest_period import (
    CheapestPeriodError,
    PriceInterval,
    find_cheapest_period,
)

intervals = [
    PriceInterval(item.start, item.end, item.entry[area] / 1000)
    for item in price_entries
]
try:
    result = find_cheapest_period(
        intervals,
        window_start,
        window_end,
        timedelta(minutes=duration_minutes),
    )
except CheapestPeriodError as error:
    raise ServiceValidationError(str(error)) from error

return {
    "area": area,
    "currency": currency,
    "unit": f"{currency}/kWh",
    "start": result.start.isoformat(),
    "end": result.end.isoformat(),
    "average_price": result.average_price,
    "duration_minutes": duration_minutes,
}
```

This is not a complete handler. The response shape is proposed; M4 only returns
the `CheapestPeriod` record. Use the schema-guaranteed keys directly, and treat
unexpected missing area data from the external client as a separate data failure.
Do not skip records with missing prices and pretend the requested dataset is
complete. Serialize datetimes to ISO strings as existing actions do; do not
return the dataclass itself. Keep full calculation precision in the response.

### 6. Map failures and register the action

Keep network error handling around retrieval and `CheapestPeriodError` handling
around the calculation, with small try blocks.

- Preserve existing `NordPoolAuthenticationError` → translated
  `ServiceValidationError` with `authentication_error`.
- Preserve `(NordPoolError, TimeoutError)` → `connection_error`, following
  `get_prices()`. Inspect client behavior before expanding caught types.
- Give empty/missing prices a clear unavailable-data error for the new action.
  Existing price-list actions return `{area: []}` for
  `NordPoolEmptyResponseError`; that is not a cheapest-period result.
- Map `CheapestPeriodError` to a user-facing `ServiceValidationError`, retaining
  enough detail to distinguish invalid inputs from unavailable exact runs.
  The pseudocode uses the plain message; add appropriate translated exception
  keys in `strings.json` for the final integration implementation.

Add a constant such as `SERVICE_GET_CHEAPEST_PERIOD = "get_cheapest_period"`,
the new schema, and a handler in `services.py`. Register with
`hass.services.async_register(..., supports_response=SupportsResponse.ONLY)`
as existing retrieval actions do. The new action only reads prices and returns
a recommendation; no device-control or configuration-write behavior is needed.

Add fields/selectors to `services.yaml` and action names/descriptions and error
messages to `strings.json`. Preserve both existing actions. After changing
`strings.json`, regenerate English translations **before tests**:

```sh
python3 -m script.translations develop --integration nordpool
```

### 7. Add action-level tests

Extend `tests/components/nordpool/test_services.py` or add a focused action test
module alongside it. Reuse `conftest.py:load_int`, `get_client`, and
`aioclient_mock`, plus `tests/components/nordpool/__init__.py:ENTRY_CONFIG`.
The existing fixtures cover yesterday/today/tomorrow, 15-/60-minute indices,
and a separate NL delivery dataset. Add dedicated fixtures where necessary.

Call the real registered action through
`await hass.services.async_call(DOMAIN, "get_cheapest_period", data,
blocking=True, return_response=True)`. Cover at least:

- A known cheapest result using the real M4 function and correct currency/kWh
  conversion, UTC ISO boundaries, selected area, and response metadata.
- Correct entry/client selection, configured currency default, and explicit
  currency if supported; missing/unloaded entry failures.
- Schema rejection of invalid area, naive/reversed window, and non-positive
  duration; an exact-duration mismatch from otherwise valid inputs.
- Empty/unpublished tomorrow data, a gap, cross-midnight retrieval, and
  network/authentication/timeout failures.
- Negative prices, earliest ties, and appropriate 15-/60-minute behavior.
- Continued behavior of both existing price actions and their snapshots.

Annotate new test parameters with concrete types. Use parametrization with
named cases, `usefixtures` for unused fixtures, and Syrupy snapshots for large
responses, following `AGENTS.md`. Avoid duplicating all M4 unit tests: test the
adapter, action contract, retrieval boundaries, and error mapping.

## H. Remaining work and dependencies

### M4 completed work

- [x] Standalone calculator, frozen input/output records, and explicit error type.
- [x] Whole-interval exact-duration selection, weighted averages, earliest ties,
  negative prices, UTC normalization, and overlap/gap handling.
- [x] 34 calculation test cases, successfully rerun.
- [x] Separate local dashboard and six successfully rerun HTTP adapter tests.

### M4 limitations and optional improvements

- [ ] Document whole-interval restrictions in the eventual action UI.
- [ ] Add focused tests for remaining explicit guards, such as wrong record
  types, string prices, non-datetime timestamps, and non-`timedelta` duration.
- [ ] Add spring-forward, cross-midnight, and broader mixed-offset cases.
- [ ] Review numerical extremes and search performance if horizons grow.
- [ ] Consider partial-interval support only if the agreed requirements call
  for it; it is outside the current M4 contract and would require deliberate
  algorithm/test changes.

### M5 required implementation

- [ ] Agree the action inputs, response shape, area/default rules, supported
  horizon, retrieval source/resolution, and coverage policy.
- [ ] Implement `nordpool.get_cheapest_period` in `services.py` using M4.
- [ ] Resolve the entry and retrieve all relevant delivery dates.
- [ ] Convert one area's raw currency/MWh prices to currency/kWh.
- [ ] Handle missing tomorrow prices, multi-day gaps, and cross-midnight windows.
- [ ] Add schema, selectors, descriptions, translated errors, and English
  translation generation.
- [ ] Add action tests and run the existing action regressions.

### M6 end-to-end and regression testing

- [ ] Exercise the action in Home Assistant with response data available to an
  automation or script and verify expected start/end/average values.
- [ ] Test unpublished tomorrow data and retrieval failures without stale success.
- [ ] Test cross-midnight windows and both DST transitions with real elapsed
  durations, repeated local hours, and missing local hours.
- [ ] Run the full Nord Pool suite, including coordinator, sensors, setup, and
  existing actions; check snapshots and translations.
- [ ] Align Python with the checkout requirement and complete repository checks.

### GA4 deferred requirements

No authoritative GA4 requirement document was identified in the inspected
sources. The following are **candidates to confirm with the assignment brief**,
not claims about the agreed GA4 scope:

- [ ] Confirm whether consumption-aware cost/savings calculations are required.
- [ ] Confirm whether appliance scheduling/control or a production frontend is required.
- [ ] Confirm whether partial intervals, broader date horizons, or additional
  optimization behavior should be deferred to GA4.

Basic action error handling, unit conversion, and an honest missing-data policy
are M5 responsibilities; they should not be deferred simply because broader
edge-case testing continues in M6.

## I. Git and collaboration

Inspection found:

| Item | State |
| --- | --- |
| Branch | `groupassignment-2` |
| HEAD | `dc3a0064435d08c795dec956ce0cbf98954b14b4` |
| Commit subject | `Reduced cyclomatic complexity in _async_update_data method` |
| Commit timestamp | `2026-10-20 10:56:24 +0200` |
| Tracked implementation/test modifications at initial inspection | None |
| M4 calculator and tests | Untracked, not committed |
| Demo directory | Seven untracked files, not committed |
| This handover | New untracked `docs/ga3/M4_TO_M5_HANDOVER.md` |

The pre-existing untracked files are:

```text
homeassistant/components/nordpool/cheapest_period.py
tests/components/nordpool/test_cheapest_period.py
devtools/nordpool_cheapest_period_demo/README.md
devtools/nordpool_cheapest_period_demo/__init__.py
devtools/nordpool_cheapest_period_demo/app.js
devtools/nordpool_cheapest_period_demo/index.html
devtools/nordpool_cheapest_period_demo/server.py
devtools/nordpool_cheapest_period_demo/style.css
devtools/nordpool_cheapest_period_demo/test_server.py
```

These files belong to the M4 calculation/demo handover. M5 should build around
them and avoid replacing the calculator, rewriting its interface, or overwriting
the demo. Expected M5 edits are primarily `services.py`, `services.yaml`,
`strings.json`, action tests, and any required fixtures/snapshots. Change shared
retrieval logic only with regression coverage.

**Checking out HEAD or cloning this branch alone will not include the untracked
M4 files.** Have the human author review and preserve them through the team's
normal commit or file-transfer workflow before another developer depends on
them. `git diff` alone also omits these files; use
`git status --short --untracked-files=all` to inventory them. Avoid `git clean`
or overwriting this workspace during transfer.

No commit or push was created for this documentation task. Before later commits,
follow `AGENTS.md`, including `script/setup` in a new environment and final
checks. Do not amend, squash, or rebase commits already pushed to an opened PR.
Under `AI_POLICY.md`, a human must review, understand, and be able to explain
the work before submission; do not open issues/PRs or post unreviewed comments
autonomously.

## J. M5 Developer — Start Here

1. Read `homeassistant/components/nordpool/cheapest_period.py`, then
   `tests/components/nordpool/test_cheapest_period.py`. Next read `services.py`,
   `services.yaml`, `strings.json`, `coordinator.py`, and
   `tests/components/nordpool/test_services.py` plus `conftest.py`.
2. Obtain the untracked M4 files as well as the branch. In the repository,
   activate `.venv` (run `script/setup` first for a new environment), then run:

   ```sh
   uv run --no-sync pytest -q tests/components/nordpool/test_cheapest_period.py
   python3 -m unittest discover -s devtools/nordpool_cheapest_period_demo -p 'test_*.py'
   python3 devtools/nordpool_cheapest_period_demo/server.py
   ```

   Open `http://127.0.0.1:8765`, verify the two-hour evening result, then Ctrl+C.
3. Reuse
   `find_cheapest_period(list_of_PriceInterval, aware_start, aware_end, timedelta)`.
   Convert client `entry[area] / 1000` before calling it. Return the result's
   UTC `start`, `end`, and `average_price` through the action response.
4. **First implementation step:** agree the proposed contract in section G,
   then add its schema and response-only registration in `services.py`, with
   one fixture-backed action test proving retrieval → conversion → M4 → response.
5. **Proposed minimum GA3 result:** a callable
   `nordpool.get_cheapest_period` action for one selected area, an aware search
   window, and a positive running duration, returning correct UTC boundaries
   and average currency/kWh or a clear validation error. Include action metadata
   and automated tests. Confirm this minimum against the team's assignment brief.
6. Before M5 handover, regenerate translations if changed and run:

   ```sh
   python3 -m script.translations develop --integration nordpool
   uv run --no-sync pytest -q tests/components/nordpool
   python3 -m unittest discover -s devtools/nordpool_cheapest_period_demo -p 'test_*.py'
   uv run --no-sync prek run --all-files
   git status --short --untracked-files=all
   ```

   Include any new test module if stored outside that Nord Pool test directory.
   Report actual results and remaining limitations to M6. M5 has the calculator,
   examples, retrieval conventions, and passing local baseline needed to begin;
   the action contract and missing-data policy still need team agreement.
