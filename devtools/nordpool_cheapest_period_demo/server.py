"""Serve a local-only visual harness for the existing Nord Pool M4 calculator."""

import argparse
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys

DIRECTORY = Path(__file__).resolve().parent
CALCULATOR_PATH = (
    DIRECTORY.parents[1] / "homeassistant/components/nordpool/cheapest_period.py"
)
# Load the standalone calculator without starting the integration's package imports.
SPEC = importlib.util.spec_from_file_location(
    "nordpool_m4_demo_calculator", CALCULATOR_PATH
)
assert SPEC is not None and SPEC.loader is not None
CALCULATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CALCULATOR
SPEC.loader.exec_module(CALCULATOR)

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def sample_scenarios() -> list[dict]:
    """Supply example data locally without fetching electricity prices."""
    scenarios = []
    for key, label, hour, minutes, prices in [
        ("evening", "Simple evening", 17, 60, [3, 1, 1, 4]),
        (
            "day",
            "Full day",
            0,
            60,
            [
                1.2,
                1,
                0.8,
                0.6,
                0.5,
                0.8,
                1.7,
                2.8,
                3.2,
                2.5,
                1.8,
                1.3,
                1,
                0.7,
                0.6,
                0.9,
                1.5,
                2.4,
                3.5,
                3,
                2.2,
                1.6,
                1.3,
                1.1,
            ],
        ),
        ("quarter", "15-minute prices", 17, 15, [3, 2, 1, 0, -1, -1, 0, 1, 2, 3, 4, 3]),
        ("gap", "Missing prices", 17, 60, [3, None, 1, 4]),
    ]:
        start = datetime(2026, 1, 1, hour, tzinfo=UTC)
        intervals = [
            {
                "start": (start + timedelta(minutes=index * minutes)).isoformat(),
                "end": (start + timedelta(minutes=(index + 1) * minutes)).isoformat(),
                "price": price,
            }
            for index, price in enumerate(prices)
            if price is not None
        ]
        scenarios.append(
            {
                "id": key,
                "label": label,
                "intervals": intervals,
                "window_start": start.isoformat(),
                "window_end": (
                    start + timedelta(minutes=len(prices) * minutes)
                ).isoformat(),
            }
        )
    return scenarios


def calculate(payload: dict) -> dict:
    """Convert transport values, call M4 directly, and serialize its result."""
    intervals = [
        CALCULATOR.PriceInterval(
            datetime.fromisoformat(record["start"]),
            datetime.fromisoformat(record["end"]),
            record["price"],
        )
        for record in payload["intervals"]
    ]
    duration = timedelta(minutes=payload["duration_minutes"])
    result = CALCULATOR.find_cheapest_period(
        intervals,
        datetime.fromisoformat(payload["window_start"]),
        datetime.fromisoformat(payload["window_end"]),
        duration,
    )
    return {
        "start": result.start.isoformat(),
        "end": result.end.isoformat(),
        "average_price": result.average_price,
        "duration_minutes": duration.total_seconds() / 60,
    }


class DemoHandler(BaseHTTPRequestHandler):
    """Serve only explicit demo assets and the calculation endpoint."""

    def respond(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        """Send an uncached response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        """Return a static asset without exposing repository files."""
        if self.path == "/api/scenarios":
            self.respond_json(HTTPStatus.OK, sample_scenarios())
            return
        if self.path not in ASSETS:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = ASSETS[self.path]
        self.respond(HTTPStatus.OK, (DIRECTORY / filename).read_bytes(), content_type)

    def do_POST(self) -> None:
        """Return M4 results or its original validation message."""
        if self.path != "/api/calculate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        if not 0 < length <= 1_000_000:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except ValueError, UnicodeError:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON request"})
            return
        try:
            result = calculate(payload)
        except CALCULATOR.CheapestPeriodError as err:
            self.respond_json(
                HTTPStatus.BAD_REQUEST, {"error": str(err), "source": "M4"}
            )
            return
        except KeyError, TypeError, ValueError, OverflowError:
            self.respond_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "error": "Supply valid timestamps, numeric prices and a duration in minutes"
                },
            )
            return
        self.respond_json(HTTPStatus.OK, result)

    def respond_json(self, status: HTTPStatus, payload: dict | list[dict]) -> None:
        """Send a JSON response."""
        self.respond(status, json.dumps(payload).encode(), "application/json")


def main() -> None:
    """Start the development server on loopback only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler) as server:
        print(f"Nord Pool M4 demo: http://127.0.0.1:{server.server_port}", flush=True)  # noqa: T201
        with suppress(KeyboardInterrupt):
            server.serve_forever()


if __name__ == "__main__":
    main()
