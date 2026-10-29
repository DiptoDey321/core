# Electricity Price Planner demo

A local dashboard using the existing Nord Pool M4 calculator. Sample prices only:
no live API calls, consumption data, bill calculation, or savings estimates.
No additional packages are needed to run the demo.

From the repository root, with the repository virtual environment activated:

```sh
python3 devtools/nordpool_cheapest_period_demo/server.py
```

Open <http://127.0.0.1:8765>. Use `--port 8766` to choose another port.
The server always binds to `127.0.0.1`. Stop it with Ctrl+C.

- The initial **Simple evening** sample automatically calculates a two-hour run:
  **18:00–20:00 UTC at 1 SEK/kWh**, on January 1, 2026.
- Select 1, 2, or 3 hours to recalculate immediately. Custom minutes recalculate
  when the field changes; **Find best time** also submits the selected duration.
- **Sample scenario** loads backend-provided evening, full-day, quarter-hour
  (including negative prices), and missing-price examples.
- The graph shows actual elapsed interval widths. Green bars and the pale green
  background identify the Python result. Hover, tap, or focus a bar for its exact
  timestamps, UTC offsets, and price. Missing intervals remain gaps.
- **View** zooms the graph only. Morning (06–12), afternoon (12–18), and evening
  (18–24) are offered where the data supports them on a single displayed date.
  Recommendations always use the allowed search period shown below the cards.
  A recommendation outside the current view remains visible in the card.
- Times initially use **UTC** to preserve the predefined example. Choose
  **Europe/Stockholm** or the browser's local timezone in **Display timezone**.
  Formatting uses the selected IANA timezone, including daylight saving offsets;
  changing it never alters the timestamps sent to the calculator. The editor
  always uses explicit ISO timestamps with `Z` or UTC offsets.
- **Developer/Test data** is collapsed initially. Edit the JSON to add/remove
  intervals, change prices, or set an explicit allowed search period, then apply.
  Duration is controlled by the main form. Unapplied edits do not change the graph.
  Loading a scenario replaces the editor's contents.
- Try 90 minutes with the hourly sample for a friendly exact-duration error.
  Try 3 hours with missing prices to check continuity. Invalid or pending requests
  clear the previous recommendation and chart highlight; older responses are ignored.

`GET /api/scenarios` supplies sample intervals and search boundaries from
`server.py`. `POST /api/calculate` constructs existing `PriceInterval` records
and calls the real repository function directly:
`find_cheapest_period(intervals, window_start, window_end, duration)`.
The adapter loads `homeassistant/components/nordpool/cheapest_period.py` with
Python's import machinery to avoid integration startup dependencies. JavaScript
only formats data, plots prices, and sends requests; it does not find cheapest
periods. Restart the server after changing Python code.

M4 uses complete, non-overlapping intervals and an exact continuous duration.
It never splits an interval or crosses a gap. Averages are duration weighted;
ties favor the earliest start. Prices are treated as SEK/kWh without conversion.
Production Nord Pool files are not part of this dashboard redesign.

Run demo HTTP adapter checks:

```sh
python3 -m unittest discover -s devtools/nordpool_cheapest_period_demo -p 'test_*.py'
```

Run existing M4 tests and repository checks:

```sh
uv run --no-sync pytest -q tests/components/nordpool/test_cheapest_period.py
uv run --no-sync prek run --all-files
```
