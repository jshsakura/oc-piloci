from unittest.mock import patch

from piloci import profiling_baseline


class TestCollectBaseline:
    def test_collect_baseline_calls_with_client(self):
        mock_result = {
            "samples_per_path": 5,
            "paths": ["/healthz"],
            "results": {"/healthz": {"mean_ms": 10.0}},
        }
        with patch.object(
            profiling_baseline, "collect_baseline_with_client", return_value=mock_result
        ) as mock_fn:
            result = profiling_baseline.collect_baseline(
                "http://localhost:8000",
                paths=["/healthz"],
                samples=5,
                timeout=2.0,
                token="tok",
            )
        assert result["samples_per_path"] == 5
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args
        assert call_kwargs[1]["paths"] == ["/healthz"]
        assert call_kwargs[1]["samples"] == 5
        assert call_kwargs[1]["token"] == "tok"
