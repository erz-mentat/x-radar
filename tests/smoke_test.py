import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


def load_module():
    module_path = Path(__file__).resolve().parents[1] / "skill" / "scripts" / "x_search.py"
    spec = importlib.util.spec_from_file_location("x_radar_x_search_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_user_tweets_partial_cache_counts_one_request(self):
        fake_user = {"data": {"id": "u1"}}
        fake_tweets = {
            "data": [
                {
                    "created_at": "2026-01-01T00:00:00Z",
                    "public_metrics": {"like_count": 1, "reply_count": 0, "retweet_count": 0},
                }
            ]
        }

        with patch.object(self.mod, "user_by_username", return_value=(fake_user, True)):
            with patch.object(self.mod, "_get", return_value=(fake_tweets, False)):
                out = self.mod.user_tweets("alice")

        cost = out["x_radar"]["cost"]
        self.assertEqual(cost["requests"], 1)
        self.assertEqual(cost["user_lookups"], 0)
        self.assertEqual(cost["post_reads"], 1)

    def test_invalid_since_returns_structured_error(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.mod.main(["search", "--query", "test", "--since", "abc"])

        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["error"]["code"], "invalid_arguments")
        self.assertIn("--since must be like", payload["error"]["message"])

    def test_missing_token_returns_structured_error(self):
        out = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out):
                code = self.mod.main(["tweet", "--id", "1"])

        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["error"]["code"], "runtime_error")
        self.assertIn("Missing X_BEARER_TOKEN", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()
