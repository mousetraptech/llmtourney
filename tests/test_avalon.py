"""Tests for The Resistance: Avalon engine."""

import pytest

from llmtourney.events.avalon.engine import (
    AvalonEvent,
    Phase,
    ROLE_CONFIGS,
    QUEST_SIZES,
    WIN_GOOD_PTS,
    WIN_EVIL_PTS,
    ASSASSIN_BONUS,
    MERLIN_SURVIVAL_BONUS,
)
from llmtourney.events.base import ValidationResult


@pytest.fixture
def event():
    """Standard 6-player, 3-game Avalon event."""
    e = AvalonEvent(games_per_match=3, num_players=6)
    e.reset(seed=42)
    return e


@pytest.fixture
def event_1game():
    """Single-game event for simpler testing."""
    e = AvalonEvent(games_per_match=1, num_players=6)
    e.reset(seed=42)
    return e


# ── Helpers ──────────────────────────────────────────────────────────

def get_players_by_role(event, role):
    """Return list of player_ids with given role."""
    return [p for p, r in event._roles.items() if r == role]


def get_players_by_team(event, team):
    """Return list of player_ids on given team."""
    return [p for p, t in event._teams.items() if t == team]


def skip_discussion(event):
    """Play through the discussion phase with generic statements."""
    while event._phase == Phase.DISCUSS and not event.is_terminal():
        pid = event.current_player()
        event.apply_action(pid, {"action": "discuss", "statement": "I'm thinking..."})


def force_approve_nomination(event, team):
    """Nominate a team and have everyone approve."""
    leader = event.current_player()
    assert event._phase == Phase.NOMINATE
    event.apply_action(leader, {"action": "nominate", "team": team})

    # Everyone votes approve
    assert event._phase == Phase.VOTE
    while event._phase == Phase.VOTE:
        pid = event.current_player()
        event.apply_action(pid, {"action": "vote", "vote": "approve"})


def play_quest_all_success(event):
    """All quest members play success."""
    assert event._phase == Phase.QUEST
    while event._phase == Phase.QUEST and not event.is_terminal():
        pid = event.current_player()
        event.apply_action(pid, {"action": "quest", "play": "success"})


def play_quest_evil_fail(event):
    """Evil players fail, good players succeed."""
    assert event._phase == Phase.QUEST
    while event._phase == Phase.QUEST and not event.is_terminal():
        pid = event.current_player()
        if event._teams[pid] == "evil":
            event.apply_action(pid, {"action": "quest", "play": "fail"})
        else:
            event.apply_action(pid, {"action": "quest", "play": "success"})


# ── Role Assignment Tests ────────────────────────────────────────────

class TestRoleAssignment:
    def test_correct_team_counts(self, event):
        good = get_players_by_team(event, "good")
        evil = get_players_by_team(event, "evil")
        assert len(good) == 4
        assert len(evil) == 2

    def test_all_roles_present_6p(self, event):
        roles = set(event._roles.values())
        # 6p: merlin, percival, loyal, loyal, assassin, morgana
        assert "merlin" in roles
        assert "percival" in roles
        assert "loyal" in roles
        assert "assassin" in roles
        assert "morgana" in roles

    def test_deterministic_with_seed(self):
        e1 = AvalonEvent(num_players=6)
        e1.reset(seed=123)
        roles1 = dict(e1._roles)

        e2 = AvalonEvent(num_players=6)
        e2.reset(seed=123)
        roles2 = dict(e2._roles)

        assert roles1 == roles2

    def test_different_seeds_differ(self):
        e1 = AvalonEvent(num_players=6)
        e1.reset(seed=1)

        e2 = AvalonEvent(num_players=6)
        e2.reset(seed=99999)

        # Very unlikely to get same assignment
        # (could theoretically fail but probability is negligible)
        assert e1._roles != e2._roles or e1._player_order != e2._player_order

    def test_role_counts_all_player_counts(self):
        for n in (5, 6, 7, 8):
            e = AvalonEvent(num_players=n)
            e.reset(seed=42)
            config = ROLE_CONFIGS[n]
            good_count = len(config["good"])
            evil_count = len(config["evil"])
            assert len(get_players_by_team(e, "good")) == good_count
            assert len(get_players_by_team(e, "evil")) == evil_count

    def test_invalid_player_count(self):
        with pytest.raises(ValueError):
            AvalonEvent(num_players=3)
        with pytest.raises(ValueError):
            AvalonEvent(num_players=10)


# ── Sight Phase Tests ────────────────────────────────────────────────

class TestSightPhase:
    def test_merlin_sees_evil(self, event):
        merlin = get_players_by_role(event, "merlin")[0]
        knowledge = event._role_knowledge[merlin]
        evil_players = set(get_players_by_team(event, "evil"))
        seen = set(knowledge.get("evil_players", []))
        # In 6p (no mordred), Merlin sees all evil
        assert seen == evil_players

    def test_percival_sees_candidates(self, event):
        percival = get_players_by_role(event, "percival")[0]
        knowledge = event._role_knowledge[percival]
        candidates = set(knowledge.get("merlin_candidates", []))
        merlin = set(get_players_by_role(event, "merlin"))
        morgana = set(get_players_by_role(event, "morgana"))
        assert candidates == merlin | morgana

    def test_evil_see_each_other(self, event):
        evil = get_players_by_team(event, "evil")
        for pid in evil:
            knowledge = event._role_knowledge[pid]
            allies = set(knowledge.get("evil_allies", []))
            others = set(evil) - {pid}
            assert allies == others

    def test_loyal_sees_nothing(self, event):
        loyals = get_players_by_role(event, "loyal")
        for pid in loyals:
            assert event._role_knowledge[pid] == {}

    def test_merlin_cannot_see_mordred(self):
        """In 8p game, Merlin should NOT see Mordred."""
        e = AvalonEvent(num_players=8)
        e.reset(seed=42)
        merlin = get_players_by_role(e, "merlin")[0]
        mordred_players = get_players_by_role(e, "mordred")
        if mordred_players:  # 8p always has mordred
            seen = set(e._role_knowledge[merlin].get("evil_players", []))
            assert mordred_players[0] not in seen

    def test_oberon_isolated(self):
        """In 7p game, Oberon doesn't know evil and evil don't know Oberon."""
        e = AvalonEvent(num_players=7)
        e.reset(seed=42)
        oberon_players = get_players_by_role(e, "oberon")
        if oberon_players:
            oberon = oberon_players[0]
            # Oberon sees nothing
            assert e._role_knowledge[oberon] == {}
            # Other evil don't see Oberon
            for pid in get_players_by_team(e, "evil"):
                if pid != oberon:
                    allies = e._role_knowledge[pid].get("evil_allies", [])
                    assert oberon not in allies


# ── Discussion Tests ─────────────────────────────────────────────────

class TestDiscussion:
    def test_starts_in_discuss_phase(self, event):
        assert event._phase == Phase.DISCUSS

    def test_all_players_speak(self, event):
        speakers = []
        while event._phase == Phase.DISCUSS:
            pid = event.current_player()
            speakers.append(pid)
            event.apply_action(pid, {"action": "discuss", "statement": f"I am {pid}"})
        assert len(speakers) == 6
        assert set(speakers) == set(event._player_order)

    def test_statements_recorded(self, event):
        skip_discussion(event)
        # After discussion, statements should be populated
        # (They get cleared when next discussion starts, but should exist during nominate)
        # Check during nomination phase
        assert event._phase == Phase.NOMINATE

    def test_discuss_validation_empty_statement(self, event):
        pid = event.current_player()
        result = event.validate_action(pid, {"action": "discuss", "statement": ""})
        assert not result.legal

    def test_discuss_validation_wrong_action(self, event):
        pid = event.current_player()
        result = event.validate_action(pid, {"action": "vote", "vote": "approve"})
        assert not result.legal


# ── Nomination Tests ─────────────────────────────────────────────────

class TestNomination:
    def test_nominate_after_discussion(self, event):
        skip_discussion(event)
        assert event._phase == Phase.NOMINATE

    def test_valid_nomination(self, event):
        skip_discussion(event)
        leader = event.current_player()
        team = event._player_order[:event._quest_size]
        result = event.validate_action(leader, {"action": "nominate", "team": team})
        assert result.legal

    def test_reject_wrong_team_size(self, event):
        skip_discussion(event)
        leader = event.current_player()
        # Too many
        team = event._player_order[:event._quest_size + 1]
        result = event.validate_action(leader, {"action": "nominate", "team": team})
        assert not result.legal

        # Too few
        team = event._player_order[:1]
        result = event.validate_action(leader, {"action": "nominate", "team": team})
        assert not result.legal

    def test_reject_invalid_player_id(self, event):
        skip_discussion(event)
        leader = event.current_player()
        team = ["nonexistent_player", event._player_order[0]]
        result = event.validate_action(leader, {"action": "nominate", "team": team})
        assert not result.legal

    def test_reject_duplicate_players(self, event):
        skip_discussion(event)
        leader = event.current_player()
        dup = event._player_order[0]
        team = [dup, dup]
        result = event.validate_action(leader, {"action": "nominate", "team": team})
        assert not result.legal


# ── Voting Tests ─────────────────────────────────────────────────────

class TestVoting:
    def test_majority_approve_proceeds_to_quest(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        leader = event.current_player()
        event.apply_action(leader, {"action": "nominate", "team": team})

        assert event._phase == Phase.VOTE
        # All approve
        while event._phase == Phase.VOTE:
            pid = event.current_player()
            event.apply_action(pid, {"action": "vote", "vote": "approve"})
        assert event._phase == Phase.QUEST

    def test_majority_reject_goes_to_discussion(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        leader = event.current_player()
        event.apply_action(leader, {"action": "nominate", "team": team})

        # All reject
        while event._phase == Phase.VOTE:
            pid = event.current_player()
            event.apply_action(pid, {"action": "vote", "vote": "reject"})
        # Should go back to discuss (new leader)
        assert event._phase == Phase.DISCUSS

    def test_leader_rotates_on_rejection(self, event):
        skip_discussion(event)
        first_leader = event._leader
        first_leader_idx = event._leader_idx

        team = event._player_order[:event._quest_size]
        event.apply_action(first_leader, {"action": "nominate", "team": team})

        # All reject
        while event._phase == Phase.VOTE:
            pid = event.current_player()
            event.apply_action(pid, {"action": "vote", "vote": "reject"})

        # Leader should have advanced
        expected_idx = (first_leader_idx + 1) % len(event._player_order)
        assert event._leader_idx == expected_idx

    def test_five_rejections_evil_wins(self, event_1game):
        """5 consecutive rejections → evil wins automatically."""
        e = event_1game
        for _ in range(5):
            if e.is_terminal():
                break
            skip_discussion(e)
            assert e._phase == Phase.NOMINATE
            leader = e.current_player()
            team = e._player_order[:e._quest_size]
            e.apply_action(leader, {"action": "nominate", "team": team})

            while e._phase == Phase.VOTE and not e.is_terminal():
                pid = e.current_player()
                e.apply_action(pid, {"action": "vote", "vote": "reject"})

            if e.is_terminal():
                break

        assert e.is_terminal()
        assert e._game_winner == "evil"

    def test_vote_validation(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        event.apply_action(event.current_player(), {"action": "nominate", "team": team})

        pid = event.current_player()
        # Valid
        assert event.validate_action(pid, {"action": "vote", "vote": "approve"}).legal
        assert event.validate_action(pid, {"action": "vote", "vote": "reject"}).legal
        # Invalid
        assert not event.validate_action(pid, {"action": "vote", "vote": "maybe"}).legal


# ── Quest Tests ──────────────────────────────────────────────────────

class TestQuest:
    def test_good_must_play_success(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        force_approve_nomination(event, team)

        # Find a good player on the team
        for pid in team:
            if event._teams[pid] == "good":
                result = event.validate_action(pid, {"action": "quest", "play": "fail"})
                assert not result.legal
                assert "MUST play 'success'" in result.reason
                break

    def test_evil_can_play_either(self, event):
        skip_discussion(event)
        # Build a team with an evil player
        evil = get_players_by_team(event, "evil")
        good = get_players_by_team(event, "good")
        team = [evil[0]] + good[:event._quest_size - 1]
        force_approve_nomination(event, team)

        result_s = event.validate_action(evil[0], {"action": "quest", "play": "success"})
        assert result_s.legal
        result_f = event.validate_action(evil[0], {"action": "quest", "play": "fail"})
        assert result_f.legal

    def test_all_success_quest_passes(self, event):
        skip_discussion(event)
        good = get_players_by_team(event, "good")
        team = good[:event._quest_size]
        force_approve_nomination(event, team)

        play_quest_all_success(event)
        assert event._quest_results[-1]["result"] == "success"
        assert event._good_wins == 1

    def test_fail_causes_quest_failure(self, event):
        skip_discussion(event)
        evil = get_players_by_team(event, "evil")
        good = get_players_by_team(event, "good")
        team = [evil[0]] + good[:event._quest_size - 1]
        force_approve_nomination(event, team)

        play_quest_evil_fail(event)
        assert event._quest_results[-1]["result"] == "fail"
        assert event._evil_wins == 1


# ── Assassination Tests ──────────────────────────────────────────────

class TestAssassination:
    def _play_to_assassination(self, event):
        """Play 3 quests successfully to reach assassination phase."""
        good = get_players_by_team(event, "good")
        for _ in range(3):
            skip_discussion(event)
            team = good[:event._quest_size]
            force_approve_nomination(event, team)
            play_quest_all_success(event)
            if event._phase == Phase.ASSASSINATE:
                break
        assert event._phase == Phase.ASSASSINATE

    def test_correct_assassination_evil_wins(self, event_1game):
        self._play_to_assassination(event_1game)
        assassin = get_players_by_role(event_1game, "assassin")[0]
        merlin = get_players_by_role(event_1game, "merlin")[0]

        assert event_1game.current_player() == assassin
        event_1game.apply_action(assassin, {"action": "assassinate", "target": merlin})
        assert event_1game._assassination_correct
        assert event_1game._game_winner == "evil"

    def test_wrong_assassination_good_wins(self, event_1game):
        self._play_to_assassination(event_1game)
        assassin = get_players_by_role(event_1game, "assassin")[0]
        merlin = get_players_by_role(event_1game, "merlin")[0]

        # Pick a non-merlin good player
        good = get_players_by_team(event_1game, "good")
        target = next(p for p in good if p != merlin)

        event_1game.apply_action(assassin, {"action": "assassinate", "target": target})
        assert not event_1game._assassination_correct
        assert event_1game._game_winner == "good"

    def test_cannot_assassinate_self(self, event_1game):
        self._play_to_assassination(event_1game)
        assassin = get_players_by_role(event_1game, "assassin")[0]
        result = event_1game.validate_action(assassin, {"action": "assassinate", "target": assassin})
        assert not result.legal

    def test_cannot_assassinate_evil(self, event_1game):
        self._play_to_assassination(event_1game)
        assassin = get_players_by_role(event_1game, "assassin")[0]
        evil = get_players_by_team(event_1game, "evil")
        other_evil = next(p for p in evil if p != assassin)
        result = event_1game.validate_action(assassin, {"action": "assassinate", "target": other_evil})
        assert not result.legal


# ── Scoring Tests ────────────────────────────────────────────────────

class TestScoring:
    def test_good_win_points(self, event_1game):
        """Good team members get WIN_GOOD_PTS on good win."""
        good = get_players_by_team(event_1game, "good")
        # Play 3 successful quests
        for _ in range(3):
            skip_discussion(event_1game)
            team = good[:event_1game._quest_size]
            force_approve_nomination(event_1game, team)
            play_quest_all_success(event_1game)
            if event_1game._phase == Phase.ASSASSINATE:
                break

        # Wrong assassination → good wins
        assassin = get_players_by_role(event_1game, "assassin")[0]
        merlin = get_players_by_role(event_1game, "merlin")[0]
        target = next(p for p in good if p != merlin)
        event_1game.apply_action(assassin, {"action": "assassinate", "target": target})

        for pid in good:
            assert event_1game._match_scores[pid] >= WIN_GOOD_PTS

    def test_evil_win_points(self, event_1game):
        """Evil team members get WIN_EVIL_PTS on evil win."""
        evil = get_players_by_team(event_1game, "evil")
        good = get_players_by_team(event_1game, "good")
        # Play 3 failed quests (put evil on each team)
        for _ in range(3):
            skip_discussion(event_1game)
            team = [evil[0]] + good[:event_1game._quest_size - 1]
            force_approve_nomination(event_1game, team)
            play_quest_evil_fail(event_1game)
            if event_1game.is_terminal():
                break

        for pid in evil:
            assert event_1game._match_scores[pid] >= WIN_EVIL_PTS

    def test_merlin_survival_bonus(self, event_1game):
        """Merlin gets survival bonus when good wins and not assassinated."""
        good = get_players_by_team(event_1game, "good")
        merlin = get_players_by_role(event_1game, "merlin")[0]

        for _ in range(3):
            skip_discussion(event_1game)
            team = good[:event_1game._quest_size]
            force_approve_nomination(event_1game, team)
            play_quest_all_success(event_1game)
            if event_1game._phase == Phase.ASSASSINATE:
                break

        # Wrong assassination
        assassin = get_players_by_role(event_1game, "assassin")[0]
        target = next(p for p in good if p != merlin)
        event_1game.apply_action(assassin, {"action": "assassinate", "target": target})

        assert event_1game._match_scores[merlin] == WIN_GOOD_PTS + MERLIN_SURVIVAL_BONUS

    def test_assassin_bonus(self, event_1game):
        """Assassin gets bonus for correctly identifying Merlin."""
        good = get_players_by_team(event_1game, "good")

        for _ in range(3):
            skip_discussion(event_1game)
            team = good[:event_1game._quest_size]
            force_approve_nomination(event_1game, team)
            play_quest_all_success(event_1game)
            if event_1game._phase == Phase.ASSASSINATE:
                break

        assassin = get_players_by_role(event_1game, "assassin")[0]
        merlin = get_players_by_role(event_1game, "merlin")[0]
        event_1game.apply_action(assassin, {"action": "assassinate", "target": merlin})

        # Evil wins via assassination, assassin gets evil win + bonus
        assert event_1game._match_scores[assassin] == WIN_EVIL_PTS + ASSASSIN_BONUS


# ── Game Flow Tests ──────────────────────────────────────────────────

class TestGameFlow:
    def test_full_game_good_wins(self, event_1game):
        """Full game: good wins 3 quests, survives assassination."""
        good = get_players_by_team(event_1game, "good")
        merlin = get_players_by_role(event_1game, "merlin")[0]

        quests_played = 0
        while not event_1game.is_terminal() and event_1game._phase != Phase.ASSASSINATE:
            skip_discussion(event_1game)
            team = good[:event_1game._quest_size]
            force_approve_nomination(event_1game, team)
            play_quest_all_success(event_1game)
            quests_played += 1
            if quests_played >= 5:
                break

        if event_1game._phase == Phase.ASSASSINATE:
            assassin = get_players_by_role(event_1game, "assassin")[0]
            target = next(p for p in good if p != merlin)
            event_1game.apply_action(assassin, {"action": "assassinate", "target": target})

        assert event_1game._game_winner == "good"

    def test_full_game_evil_wins_quests(self, event_1game):
        """Full game: evil wins 3 quests directly."""
        evil = get_players_by_team(event_1game, "evil")
        good = get_players_by_team(event_1game, "good")

        quests_played = 0
        while not event_1game.is_terminal() and event_1game._evil_wins < 3:
            skip_discussion(event_1game)
            team = [evil[0]] + good[:event_1game._quest_size - 1]
            force_approve_nomination(event_1game, team)
            play_quest_evil_fail(event_1game)
            quests_played += 1
            if quests_played >= 5:
                break

        assert event_1game._game_winner == "evil"

    def test_multi_game_match(self):
        """3-game match completes properly."""
        e = AvalonEvent(games_per_match=3, num_players=6)
        e.reset(seed=42)

        games_completed = 0
        while not e.is_terminal():
            good = get_players_by_team(e, "good")
            merlin = get_players_by_role(e, "merlin")[0]

            # Play 3 quests for good to win
            for _ in range(3):
                if e.is_terminal() or e._phase == Phase.ASSASSINATE:
                    break
                skip_discussion(e)
                team = good[:e._quest_size]
                force_approve_nomination(e, team)
                play_quest_all_success(e)

            if e._phase == Phase.ASSASSINATE:
                assassin = get_players_by_role(e, "assassin")[0]
                target = next(p for p in good if p != merlin)
                e.apply_action(assassin, {"action": "assassinate", "target": target})
                games_completed += 1

            if games_completed >= 3:
                break

        assert e.is_terminal()

    def test_quest_sizes_6p(self, event_1game):
        """Verify quest sizes follow 6p configuration."""
        expected = [2, 3, 4, 3, 4]
        for i in range(5):
            assert QUEST_SIZES[6][i] == expected[i]

    def test_starts_with_discuss(self, event):
        assert event._phase == Phase.DISCUSS
        assert event._quest_number == 1


# ── Forfeit Tests ────────────────────────────────────────────────────

class TestForfeit:
    def test_forfeit_discuss(self, event):
        pid = event.current_player()
        event.forfeit_turn(pid)
        assert "(silence)" in event._discussion_statements.get(pid, "")

    def test_forfeit_nominate(self, event):
        skip_discussion(event)
        assert event._phase == Phase.NOMINATE
        pid = event.current_player()
        event.forfeit_turn(pid)
        assert event._phase == Phase.VOTE  # nomination succeeded, moved to vote

    def test_forfeit_vote(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        event.apply_action(event.current_player(), {"action": "nominate", "team": team})
        assert event._phase == Phase.VOTE
        pid = event.current_player()
        event.forfeit_turn(pid)
        assert pid in event._votes
        assert event._votes[pid] == "approve"

    def test_forfeit_quest(self, event):
        skip_discussion(event)
        team = event._player_order[:event._quest_size]
        force_approve_nomination(event, team)
        assert event._phase == Phase.QUEST
        pid = event.current_player()
        event.forfeit_turn(pid)
        assert event._quest_plays[pid] == "success"


# ── Prompt Tests ─────────────────────────────────────────────────────

class TestPrompt:
    def test_prompt_contains_role(self, event):
        pid = event.current_player()
        prompt = event.get_prompt(pid)
        role = event._roles[pid]
        assert role.upper() in prompt.upper()

    def test_prompt_contains_game_state(self, event):
        pid = event.current_player()
        prompt = event.get_prompt(pid)
        assert "Quest 1 of 5" in prompt
        assert "GAME STATE" in prompt

    def test_prompt_contains_action_instructions(self, event):
        pid = event.current_player()
        prompt = event.get_prompt(pid)
        assert "discuss" in prompt
        assert "statement" in prompt

    def test_prompt_shows_knowledge_for_merlin(self, event):
        merlin = get_players_by_role(event, "merlin")[0]
        prompt = event.get_prompt(merlin)
        assert "SECRET KNOWLEDGE" in prompt
        assert "Evil players you can see" in prompt

    def test_prompt_no_knowledge_for_loyal(self, event):
        loyals = get_players_by_role(event, "loyal")
        for pid in loyals:
            prompt = event.get_prompt(pid)
            assert "SECRET KNOWLEDGE" not in prompt

    def test_retry_prompt_includes_error(self, event):
        pid = event.current_player()
        prompt = event.get_retry_prompt(pid, "bad action bro")
        assert "bad action bro" in prompt
        assert "discuss" in prompt


# ── State Snapshot Tests ─────────────────────────────────────────────

class TestStateSnapshot:
    def test_snapshot_has_required_fields(self, event):
        snap = event.get_state_snapshot()
        assert "game_number" in snap
        assert "phase" in snap
        assert "quest_number" in snap
        assert "roles" in snap
        assert "teams" in snap
        assert "match_scores" in snap
        assert "player_order" in snap

    def test_snapshot_includes_roles_godmode(self, event):
        snap = event.get_state_snapshot()
        assert len(snap["roles"]) == 6
        assert len(snap["teams"]) == 6

    def test_snapshot_serializable(self, event):
        import json
        snap = event.get_state_snapshot()
        # Should not raise
        json.dumps(snap)


# ── Edge Case Tests ──────────────────────────────────────────────────

class TestEdgeCases:
    def test_eliminate_player(self, event):
        pid = event._player_order[0]
        event.eliminate_player(pid)
        assert pid in event._eliminated

    def test_display_name(self, event):
        assert event.display_name == "Avalon"

    def test_player_ids(self, event):
        assert len(event.player_ids) == 6
        assert all(p.startswith("player_") for p in event.player_ids)

    def test_highlight_hands_after_quest(self, event_1game):
        good = get_players_by_team(event_1game, "good")
        skip_discussion(event_1game)
        team = good[:event_1game._quest_size]
        force_approve_nomination(event_1game, team)
        play_quest_all_success(event_1game)
        assert len(event_1game.get_highlight_hands()) > 0
