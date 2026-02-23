"""Tests for Referee — violation tracking and penalty rulings."""

from llmtourney.core.referee import Referee, ViolationKind, Ruling


class TestReferee:
    def test_first_violation_allows_retry(self):
        ref = Referee()
        ruling = ref.record_violation(
            "player_a", ViolationKind.MALFORMED_JSON, severity=2, details="bad json"
        )
        assert ruling == Ruling.RETRY

    def test_second_violation_same_turn_forfeits(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="bad")
        ruling = ref.record_violation(
            "player_a", ViolationKind.ILLEGAL_MOVE, severity=1, details="bad move"
        )
        assert ruling == Ruling.FORFEIT_TURN

    def test_should_retry_true_on_first(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        assert ref.should_retry("player_a") is True

    def test_should_retry_false_after_retry_used(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        assert ref.should_retry("player_a") is True
        ref.consume_retry("player_a")
        assert ref.should_retry("player_a") is False

    def test_new_turn_resets_retry(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        ref.consume_retry("player_a")
        ref.new_turn()
        ref.record_violation("player_a", ViolationKind.ILLEGAL_MOVE, severity=1, details="y")
        assert ref.should_retry("player_a") is True

    def test_violations_accumulate_across_turns(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        ref.new_turn()
        ref.record_violation("player_a", ViolationKind.ILLEGAL_MOVE, severity=1, details="y")
        report = ref.get_fidelity_report()
        assert report["player_a"]["total_violations"] == 2
        assert report["player_a"]["malformed_json"] == 1
        assert report["player_a"]["illegal_move"] == 1

    def test_injection_logged_at_severity_3(self):
        ref = Referee()
        ruling = ref.record_violation(
            "player_a", ViolationKind.INJECTION_ATTEMPT, severity=3, details="ignore prev"
        )
        report = ref.get_fidelity_report()
        assert report["player_a"]["injection_attempts"] == 1
        assert ruling == Ruling.RETRY

    def test_fidelity_report_separate_players(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        ref.record_violation("player_b", ViolationKind.ILLEGAL_MOVE, severity=1, details="y")
        report = ref.get_fidelity_report()
        assert report["player_a"]["malformed_json"] == 1
        assert report["player_a"]["illegal_move"] == 0
        assert report["player_b"]["malformed_json"] == 0
        assert report["player_b"]["illegal_move"] == 1

    def test_empty_report_for_unknown_player(self):
        ref = Referee()
        report = ref.get_fidelity_report()
        assert report == {}

    def test_severity_accumulates(self):
        ref = Referee()
        ref.record_violation("player_a", ViolationKind.MALFORMED_JSON, severity=2, details="x")
        ref.new_turn()
        ref.record_violation("player_a", ViolationKind.INJECTION_ATTEMPT, severity=3, details="y")
        report = ref.get_fidelity_report()
        assert report["player_a"]["total_severity"] == 5
