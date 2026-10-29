"""Verify the demo's HTTP adapter against the actual M4 implementation."""

from copy import deepcopy
from http import HTTPStatus
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import unittest
from unittest.mock import patch

import server


def example() -> dict:
    """Return the editable demonstration request."""
    return {
        "intervals": [
            {
                "start": f"2026-01-01T{17 + index}:00:00Z",
                "end": f"2026-01-01T{18 + index}:00:00Z",
                "price": price,
            }
            for index, price in enumerate([3, 1, 1, 4])
        ],
        "window_start": "2026-01-01T17:00:00Z",
        "window_end": "2026-01-01T21:00:00Z",
        "duration_minutes": 120,
    }


class DemoTests(unittest.TestCase):
    """Exercise actual local HTTP requests and M4 error propagation."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start a loopback server on an available port."""
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.DemoHandler)
        cls.thread = Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        """Close the test server."""
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def post(self, payload: dict) -> tuple[int, dict]:
        """Send a JSON calculation request."""
        connection = HTTPConnection(*self.httpd.server_address)
        connection.request(
            "POST",
            "/api/calculate",
            json.dumps(payload),
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        data = json.loads(response.read())
        connection.close()
        return response.status, data

    def test_real_function(self) -> None:
        """The HTTP endpoint calls the repository function with M4 records."""
        assert server.CALCULATOR.find_cheapest_period.__code__.co_filename == str(
            server.CALCULATOR_PATH
        )
        with patch.object(
            server.CALCULATOR,
            "find_cheapest_period",
            wraps=server.CALCULATOR.find_cheapest_period,
        ) as calculator:
            status, result = self.post(example())
        calculator.assert_called_once()
        assert isinstance(
            calculator.call_args.args[0][0], server.CALCULATOR.PriceInterval
        )
        assert status == HTTPStatus.OK
        assert result == {
            "start": "2026-01-01T18:00:00+00:00",
            "end": "2026-01-01T20:00:00+00:00",
            "average_price": 1.0,
            "duration_minutes": 120.0,
        }

    def test_sample_endpoint(self) -> None:
        """Use the backend's default sample in the actual calculator."""
        connection = HTTPConnection(*self.httpd.server_address)
        connection.request("GET", "/api/scenarios")
        response = connection.getresponse()
        assert response.status == HTTPStatus.OK
        samples = json.loads(response.read())
        connection.close()
        assert [sample["id"] for sample in samples] == [
            "evening",
            "day",
            "quarter",
            "gap",
        ]
        status, result = self.post({**samples[0], "duration_minutes": 120})
        assert status == HTTPStatus.OK
        assert result["start"] == "2026-01-01T18:00:00+00:00"
        assert result["end"] == "2026-01-01T20:00:00+00:00"
        assert result["average_price"] == 1

    def test_quarter_hour_sample(self) -> None:
        """Keep quarter-hour sample durations and negative prices intact."""
        sample = server.sample_scenarios()[2]
        status, result = self.post({**sample, "duration_minutes": 60})
        assert status == HTTPStatus.OK
        assert result["start"] == "2026-01-01T17:45:00+00:00"
        assert result["end"] == "2026-01-01T18:45:00+00:00"
        assert result["average_price"] == -0.5

    def test_changed_prices_and_duration(self) -> None:
        """Edits produce fresh real results, including negative prices."""
        changed = example()
        changed["intervals"][0]["price"] = -3
        short = deepcopy(changed)
        short["duration_minutes"] = 60
        cases = [(changed, -1.0), (short, -3.0)]
        for payload, price in cases:
            with self.subTest(duration=payload["duration_minutes"]):
                status, result = self.post(payload)
                assert status == HTTPStatus.OK
                assert result["start"] == "2026-01-01T17:00:00+00:00"
                expected_end = 17 + payload["duration_minutes"] // 60
                assert result["end"] == f"2026-01-01T{expected_end}:00:00+00:00"
                assert result["average_price"] == price

    def test_m4_errors(self) -> None:
        """Preserve calculator messages for gaps, mismatches and invalid inputs."""
        gap = example()
        del gap["intervals"][1]
        del gap["intervals"][1]
        mismatch = example()
        mismatch["duration_minutes"] = 90
        overlap = example()
        overlap["intervals"][1]["start"] = "2026-01-01T17:30:00Z"
        naive = example()
        naive["window_start"] = "2026-01-01T17:00:00"
        for payload, message in [
            (
                gap,
                "No continuous period of complete intervals matches the requested duration",
            ),
            (
                mismatch,
                "No continuous period of complete intervals matches the requested duration",
            ),
            (overlap, "Price intervals must not overlap"),
            (naive, "Timestamps must be timezone-aware datetimes"),
        ]:
            with self.subTest(message=message):
                status, result = self.post(payload)
                assert status == HTTPStatus.BAD_REQUEST
                assert result == {"error": message, "source": "M4"}

    def test_assets_and_malformed_request(self) -> None:
        """Serve demo assets while rejecting malformed transport data."""
        connection = HTTPConnection(*self.httpd.server_address)
        for path in ["/", "/app.js", "/style.css"]:
            with self.subTest(path=path):
                connection.request("GET", path)
                response = connection.getresponse()
                assert response.status == HTTPStatus.OK
                assert response.read()
        connection.request("GET", "/server.py")
        response = connection.getresponse()
        assert response.status == HTTPStatus.NOT_FOUND
        response.read()
        connection.request("POST", "/api/calculate", "{")
        response = connection.getresponse()
        assert response.status == HTTPStatus.BAD_REQUEST
        assert json.loads(response.read())["error"] == "Invalid JSON request"
        connection.close()


if __name__ == "__main__":
    unittest.main()
