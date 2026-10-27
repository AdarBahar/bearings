"""Tests for the cost counters and the dashboard Costs section.
Run with:  python3 -m unittest discover tests"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from bearings_sweep import (cost_block, parse_claude_json, prune_runs,  # noqa: E402
                            record_runs)

TODAY = date(2026, 10, 27)


def rec(d, kind="refresh", name="app", model="claude-haiku-5-5",
        cost=1.0, t_in=100, t_cache=0, t_out=10):
    return {"d": d, "kind": kind, "name": name, "model": model,
            "cost": cost, "in": t_in, "cache": t_cache, "out": t_out}


class TestParseModelUsage(unittest.TestCase):
    def test_model_usage_is_extracted(self):
        out = json.dumps({"total_cost_usd": 0.5, "result": "ok",
                          "usage": {"input_tokens": 10, "output_tokens": 2},
                          "modelUsage": {
                              "claude-haiku-5-5": {"inputTokens": 8,
                                                   "cacheReadInputTokens": 100,
                                                   "outputTokens": 2,
                                                   "costUSD": 0.4},
                              "claude-sonnet-5-5": {"inputTokens": 2,
                                                    "outputTokens": 0,
                                                    "costUSD": 0.1}}})
        *_, models = parse_claude_json(out)
        # Cache reads stay separate from fresh input tokens.
        self.assertEqual(models["claude-haiku-5-5"],
                         {"cost": 0.4, "in": 8, "cache": 100, "out": 2})
        self.assertEqual(models["claude-sonnet-5-5"],
                         {"cost": 0.1, "in": 2, "cache": 0, "out": 0})

    def test_missing_model_usage_gives_an_empty_dict(self):
        *_, models = parse_claude_json(json.dumps({"result": "ok"}))
        self.assertEqual(models, {})

    def test_fallback_without_model_usage_keeps_the_cache_split(self):
        out = json.dumps({"total_cost_usd": 0.5, "result": "ok",
                          "usage": {"input_tokens": 10,
                                    "cache_read_input_tokens": 1000,
                                    "output_tokens": 2}})
        *_, models = parse_claude_json(out)
        self.assertEqual(models, {"": {"cost": 0.5, "in": 10,
                                       "cache": 1000, "out": 2}})


class TestRecordsAndPrune(unittest.TestCase):
    def test_record_one_entry_per_model_with_a_shared_call_id(self):
        state = {}
        record_runs(state, TODAY, "refresh", "app",
                    {"a": {"cost": 0.1, "in": 1, "cache": 50, "out": 2},
                     "b": {"cost": 0.2, "in": 3, "out": 4}})
        self.assertEqual(len(state["runs"]), 2)
        self.assertEqual(state["runs"][0]["d"], "2026-10-27")
        self.assertEqual(state["runs"][0]["cache"], 50)
        # A fallback usage dict without "cache" records zero cache reads.
        self.assertEqual(state["runs"][1]["cache"], 0)
        self.assertEqual(state["runs"][1]["model"], "b")
        # One call: the two model records share one id.
        self.assertEqual(state["runs"][0]["id"], state["runs"][1]["id"])

    def test_two_calls_on_the_same_project_count_as_two_runs(self):
        state = {}
        usage = {"a": {"cost": 0.3, "in": 1, "out": 1}}
        record_runs(state, TODAY, "refresh", "app", usage)
        record_runs(state, TODAY, "refresh", "app", usage)
        block = cost_block(state, TODAY)
        self.assertIn("**Today:** 2 runs · $0.60", block)

    def test_prune_drops_old_records_and_caps_the_list(self):
        state = {"runs": [rec("2026-01-01"), rec("2026-10-01")]}
        prune_runs(state, TODAY)
        self.assertEqual([r["d"] for r in state["runs"]], ["2026-10-01"])
        state = {"runs": [rec("2026-10-26") for _ in range(2500)]}
        prune_runs(state, TODAY)
        self.assertEqual(len(state["runs"]), 2000)


class TestCostBlock(unittest.TestCase):
    def test_counters_tables_and_history(self):
        state = {
            "runs": [
                rec("2026-10-27", cost=0.5),
                rec("2026-10-27", kind="canary", name="-", cost=0.1),
                rec("2026-10-25", model="default", cost=2.0),
                rec("2026-09-20", cost=4.0),  # outside the 30-day window
            ],
            "months": {"2026-10": {"runs": 3, "cost": 2.6,
                                   "t_in": 300, "t_out": 30},
                       "2026-09": {"runs": 1, "cost": 4.0,
                                   "t_in": 100, "t_out": 10}},
        }
        block = cost_block(state, TODAY)
        self.assertIn("**Today:** 2 runs · $0.60", block)
        self.assertIn("**Last 7 days:** 3 runs · $2.60", block)
        self.assertIn("**This month:** 3 runs · $2.60", block)
        self.assertIn("| 2026-10-25 | 1 | $2.00 |", block)
        # The tables split fresh input tokens from cache reads. Records
        # from before the split have no "cache" field and count as zero.
        self.assertIn("| Day | Runs | Cost | Fresh in | Cache in | Out |", block)
        self.assertIn("| 2026-10-25 | 1 | $2.00 | 100 | 0 | 10 |", block)
        # Per model, last 30 days: both models, the costlier one first.
        haiku = block.index("| claude-haiku-5-5 | 2 | $0.60 |")
        default = block.index("| default | 1 | $2.00 |")
        self.assertLess(default, haiku)
        # Monthly history, newest first.
        self.assertIn("| 2026-10 | 3 | $2.60 | 300 | 30 |", block)
        self.assertIn("| 2026-09 | 1 | $4.00 | 100 | 10 |", block)

    def test_cache_reads_show_in_their_own_column(self):
        state = {"runs": [rec("2026-10-27", t_in=10, t_cache=1000)]}
        block = cost_block(state, TODAY)
        self.assertIn("| claude-haiku-5-5 | 1 | $1.00 | 10 | 1,000 | 10 |",
                      block)

    def test_empty_state_renders_the_counters_only(self):
        block = cost_block({}, TODAY)
        self.assertIn("**Today:** 0 runs · $0.00", block)
        self.assertNotIn("| Model |", block)


if __name__ == "__main__":
    unittest.main()
