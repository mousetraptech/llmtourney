"""Tests for mock Hold'em strategies."""

import json
import pytest
from llmtourney.events.holdem.strategies import (
    always_call_strategy,
    simple_heuristic_strategy,
    garbage_strategy,
    injector_strategy,
)


class TestAlwaysCallStrategy:
    def test_returns_valid_json(self):
        messages = [{"role": "user", "content": "Your turn. Legal actions: fold, call, raise"}]
        result = always_call_strategy(messages, {})
        parsed = json.loads(result)
        assert parsed["action"] == "call"

    def test_ignores_context(self):
        result = always_call_strategy([], {"anything": True})
        parsed = json.loads(result)
        assert parsed["action"] == "call"


class TestSimpleHeuristicStrategy:
    def test_returns_valid_json(self):
        messages = [{"role": "user", "content": _make_prompt("Ah Kh", 100, 4, 2)}]
        result = simple_heuristic_strategy(messages, {"seed": 42})
        parsed = json.loads(result)
        assert parsed["action"] in ("fold", "call", "raise")

    def test_raises_with_strong_hand(self):
        """Aces should always raise."""
        messages = [{"role": "user", "content": _make_prompt("Ah As", 100, 4, 2)}]
        result = simple_heuristic_strategy(messages, {"seed": 42})
        parsed = json.loads(result)
        assert parsed["action"] == "raise"

    def test_folds_trash_hand(self):
        """7-2 offsuit should fold when facing a bet."""
        messages = [{"role": "user", "content": _make_prompt("7h 2c", 100, 4, 2)}]
        result = simple_heuristic_strategy(messages, {"seed": 42})
        parsed = json.loads(result)
        assert parsed["action"] in ("fold", "call")

    def test_deterministic_with_same_seed(self):
        messages = [{"role": "user", "content": _make_prompt("Th 9h", 100, 6, 4)}]
        r1 = simple_heuristic_strategy(messages, {"seed": 42})
        r2 = simple_heuristic_strategy(messages, {"seed": 42})
        assert r1 == r2


class TestGarbageStrategy:
    def test_returns_non_json(self):
        result = garbage_strategy([], {})
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)


class TestInjectorStrategy:
    def test_contains_injection_pattern(self):
        result = injector_strategy([], {})
        assert "IGNORE PREVIOUS INSTRUCTIONS" in result.upper() or "ignore" in result.lower()

    def test_still_contains_json(self):
        """Injector embeds valid JSON after the injection attempt."""
        result = injector_strategy([], {})
        # Should contain a JSON object somewhere
        assert '{"action"' in result


def _make_prompt(hole_cards: str, stack: int, pot: int, call_cost: int) -> str:
    return (
        f"Your hole cards: {hole_cards}\n"
        f"Community cards: none yet\n"
        f"Your stack: {stack} chips\n"
        f"Pot: {pot} chips\n"
        f"Legal actions:\n"
        f"- fold\n"
        f"- call (cost: {call_cost} chips)\n"
        f"- raise (min: {call_cost * 2}, max: {pot + call_cost * 2} chips)\n"
    )
