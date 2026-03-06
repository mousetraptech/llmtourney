"""Avalon — The Resistance: Avalon hidden-role social deduction engine.

6 players (4 good / 2 evil). 5 quests per game, 3 games per match.
Phases: DISCUSS -> NOMINATE -> VOTE -> QUEST -> (loop or ASSASSINATE).

Tests deception persistence, accusation under uncertainty, constrained
omniscience (Merlin), and cross-role coordination.
"""

from __future__ import annotations

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

__all__ = ["AvalonEvent"]

# ── Role configurations by player count ──────────────────────────────

ROLE_CONFIGS = {
    5: {
        "good": ["merlin", "percival", "loyal"],
        "evil": ["assassin", "morgana"],
    },
    6: {
        "good": ["merlin", "percival", "loyal", "loyal"],
        "evil": ["assassin", "morgana"],
    },
    7: {
        "good": ["merlin", "percival", "loyal", "loyal"],
        "evil": ["assassin", "morgana", "oberon"],
    },
    8: {
        "good": ["merlin", "percival", "loyal", "loyal", "loyal"],
        "evil": ["assassin", "morgana", "mordred"],
    },
}

QUEST_SIZES = {
    5: [2, 3, 2, 3, 3],
    6: [2, 3, 4, 3, 4],
    7: [2, 3, 3, 4, 4],
    8: [3, 4, 4, 5, 5],
}

# Quest index (0-based) -> number of fails required to fail the quest.
# Default is 1 fail. Override for specific quests at certain player counts.
QUEST_DOUBLE_FAIL = {
    7: {3},  # Quest 4 (index 3) needs 2 fails at 7p
    8: {3},  # Quest 4 (index 3) needs 2 fails at 8p
}

# ── Scoring ──────────────────────────────────────────────────────────

WIN_GOOD_PTS = 3
WIN_EVIL_PTS = 4
ASSASSIN_BONUS = 2
MERLIN_SURVIVAL_BONUS = 2

# ── Phase constants ──────────────────────────────────────────────────


class Phase:
    DISCUSS = "discuss"
    NOMINATE = "nominate"
    VOTE = "vote"
    QUEST = "quest"
    ASSASSINATE = "assassinate"


# ── Role strategy hints for prompts ──────────────────────────────────

STRATEGY_HINTS = {
    "merlin": (
        "You know the evil players. Guide good players subtly through your "
        "nominations and votes. Avoid patterns that reveal your knowledge — "
        "never name evil players directly or vote too perfectly."
    ),
    "percival": (
        "You see two candidates for Merlin (one is Morgana pretending). "
        "Watch their behavior to figure out which is real Merlin, then "
        "protect them. Be careful not to expose Merlin by following too closely."
    ),
    "loyal": (
        "You have no special information. Use vote history, quest fail "
        "patterns, and discussion statements to infer allegiance. Trust "
        "clusters that vote together consistently."
    ),
    "assassin": (
        "You know your evil allies. Play the long game — act as a convincing "
        "good player. If good wins 3 quests, you must identify Merlin. Track "
        "who seems to have special knowledge — unusually accurate nominations "
        "suggest Merlin."
    ),
    "morgana": (
        "You appear as a Merlin candidate to Percival. Maintain plausibility "
        "as Merlin — behave like a well-informed good player. This protects "
        "the real Merlin from assassination by adding confusion."
    ),
    "mordred": (
        "You are INVISIBLE to Merlin — he cannot see you as evil. Exploit "
        "this by acting as a clean, trustworthy good player. You are the "
        "most dangerous infiltrator."
    ),
    "oberon": (
        "You do NOT know who the other evil players are, and they don't know "
        "you. You must deduce who is evil from behavior and coordinate "
        "implicitly. Play Fail strategically."
    ),
}

# ── Role descriptions for prompts ────────────────────────────────────

ROLE_DESCRIPTIONS = {
    "merlin": "MERLIN (Good) — You see all evil players{mordred_caveat}. Good wins if 3 quests succeed AND you survive assassination.",
    "percival": "PERCIVAL (Good) — You see two Merlin candidates (one is Morgana). Protect the real Merlin.",
    "loyal": "LOYAL SERVANT OF ARTHUR (Good) — No special information. Deduce evil from behavior.",
    "assassin": "ASSASSIN (Evil) — If good wins 3 quests, you name one player as Merlin. Correct guess = evil wins.",
    "morgana": "MORGANA (Evil) — You appear as a Merlin candidate to Percival, adding confusion.",
    "mordred": "MORDRED (Evil) — You are invisible to Merlin. He cannot see you as evil.",
    "oberon": "OBERON (Evil) — You are isolated. Other evil players don't know you, and you don't know them.",
}


class AvalonEvent(MultiplayerSeriesEvent):
    """The Resistance: Avalon — hidden role social deduction.

    Parameters
    ----------
    games_per_match : int
        Number of full Avalon games per match (default 3).
    num_players : int
        Number of players (5-8, default 6).
    """

    def __init__(
        self,
        games_per_match: int = 3,
        num_players: int = 6,
    ) -> None:
        if num_players not in ROLE_CONFIGS:
            raise ValueError(f"Avalon supports 5-8 players, got {num_players}")
        super().__init__(games_per_match, num_players)

        # Per-game state (initialized in _start_new_game)
        self._roles: dict[str, str] = {}
        self._teams: dict[str, str] = {}
        self._role_knowledge: dict[str, dict] = {}
        self._quest_number: int = 0
        self._quest_results: list[dict] = []
        self._good_wins: int = 0
        self._evil_wins: int = 0
        self._leader_idx: int = 0
        self._consecutive_rejections: int = 0
        self._phase: str = Phase.DISCUSS
        self._proposed_team: list[str] = []
        self._votes: dict[str, str] = {}
        self._quest_plays: dict[str, str] = {}
        self._discussion_statements: dict[str, str] = {}
        self._discussion_order: list[str] = []
        self._discussion_idx: int = 0
        self._proposal_history: list[dict] = []
        self._game_log: list[dict] = []
        self._turn_number: int = 0
        self._player_order: list[str] = []
        self._eliminated: set[str] = set()
        self._game_winner: str = ""  # "good" or "evil"
        self._assassination_target: str = ""
        self._assassination_correct: bool = False
        # Track who voted in current voting round (for sequential voting)
        self._vote_order: list[str] = []
        self._vote_idx: int = 0

    @property
    def display_name(self) -> str:
        return "Avalon"

    # ──────────────────────────────────────────────────────────────────
    # Game lifecycle
    # ──────────────────────────────────────────────────────────────────

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._quest_number = 0
        self._quest_results = []
        self._good_wins = 0
        self._evil_wins = 0
        self._consecutive_rejections = 0
        self._proposal_history = []
        self._game_log = []
        self._turn_number = 0
        self._game_winner = ""
        self._assassination_target = ""
        self._assassination_correct = False

        # Randomize player seating order
        self._player_order = list(self._player_ids)
        self._rng.shuffle(self._player_order)

        # Random starting leader
        self._leader_idx = self._rng.randint(0, len(self._player_order) - 1)

        # Assign roles
        self._assign_roles()

        # Build role knowledge (sight phase)
        self._build_role_knowledge()

        # Start first quest
        self._begin_quest()

    def _assign_roles(self) -> None:
        """Randomly assign roles to players."""
        config = ROLE_CONFIGS[self._num_players]
        all_roles = list(config["good"]) + list(config["evil"])
        self._rng.shuffle(all_roles)

        self._roles = {}
        self._teams = {}
        good_roles = {"merlin", "percival", "loyal"}
        for i, pid in enumerate(self._player_order):
            role = all_roles[i]
            self._roles[pid] = role
            self._teams[pid] = "good" if role in good_roles else "evil"

    def _build_role_knowledge(self) -> None:
        """Build per-player knowledge from the sight phase."""
        self._role_knowledge = {}
        evil_players = [
            p for p in self._player_order if self._teams[p] == "evil"
        ]
        for pid in self._player_order:
            role = self._roles[pid]
            knowledge: dict = {}

            if role == "merlin":
                # Sees all evil except Mordred
                visible_evil = [
                    p for p in evil_players
                    if self._roles[p] != "mordred"
                ]
                if visible_evil:
                    knowledge["evil_players"] = sorted(visible_evil)

            elif role == "percival":
                # Sees Merlin and Morgana (but not which is which)
                candidates = [
                    p for p in self._player_order
                    if self._roles[p] in ("merlin", "morgana")
                ]
                if candidates:
                    knowledge["merlin_candidates"] = sorted(candidates)

            elif role in ("assassin", "morgana"):
                # Evil players see each other (except Oberon)
                visible_evil = [
                    p for p in evil_players
                    if self._roles[p] != "oberon" and p != pid
                ]
                if visible_evil:
                    knowledge["evil_allies"] = sorted(visible_evil)

            elif role == "mordred":
                # Mordred sees other evil (except Oberon)
                visible_evil = [
                    p for p in evil_players
                    if self._roles[p] != "oberon" and p != pid
                ]
                if visible_evil:
                    knowledge["evil_allies"] = sorted(visible_evil)

            # oberon and loyal get empty knowledge
            self._role_knowledge[pid] = knowledge

    def _begin_quest(self) -> None:
        """Start a new quest with discussion phase."""
        self._quest_number += 1
        self._consecutive_rejections = 0
        self._start_discussion()

    def _start_discussion(self) -> None:
        """Begin the discussion phase for the current quest."""
        self._phase = Phase.DISCUSS
        self._discussion_statements = {}
        self._discussion_order = list(self._player_order)
        self._discussion_idx = 0

    def _start_nomination(self) -> None:
        """Transition to nomination phase."""
        self._phase = Phase.NOMINATE
        self._proposed_team = []

    def _start_voting(self) -> None:
        """Transition to voting phase (sequential)."""
        self._phase = Phase.VOTE
        self._votes = {}
        self._vote_order = list(self._player_order)
        self._vote_idx = 0

    def _start_quest_play(self) -> None:
        """Transition to quest phase — team members play."""
        self._phase = Phase.QUEST
        self._quest_plays = {}

    def _start_assassination(self) -> None:
        """Transition to assassination phase."""
        self._phase = Phase.ASSASSINATE

    @property
    def _leader(self) -> str:
        return self._player_order[self._leader_idx]

    @property
    def _quest_size(self) -> int:
        return QUEST_SIZES[self._num_players][self._quest_number - 1]

    @property
    def _fail_threshold(self) -> int:
        """Number of fails needed for quest to fail."""
        double_fail_quests = QUEST_DOUBLE_FAIL.get(self._num_players, set())
        if (self._quest_number - 1) in double_fail_quests:
            return 2
        return 1

    def _advance_leader(self) -> None:
        """Rotate leadership to next player."""
        self._leader_idx = (self._leader_idx + 1) % len(self._player_order)

    def _resolve_vote(self) -> None:
        """Resolve a completed vote."""
        approves = sum(1 for v in self._votes.values() if v == "approve")
        rejects = len(self._votes) - approves
        approved = approves > rejects  # strict majority

        # Record proposal
        self._proposal_history.append({
            "quest": self._quest_number,
            "attempt": self._consecutive_rejections + 1,
            "leader": self._leader,
            "proposed_team": list(self._proposed_team),
            "votes": dict(self._votes),
            "approved": approved,
        })

        if approved:
            self._start_quest_play()
        else:
            self._consecutive_rejections += 1
            if self._consecutive_rejections >= 5:
                # 5 consecutive rejections = evil wins
                self._evil_wins = 3
                self._finish_game("evil", "5 consecutive proposal rejections")
            else:
                self._advance_leader()
                # Go back to discussion for new nomination
                self._start_discussion()

    def _resolve_quest(self) -> None:
        """Resolve a completed quest."""
        fail_count = sum(1 for v in self._quest_plays.values() if v == "fail")
        success_count = len(self._quest_plays) - fail_count
        quest_passed = fail_count < self._fail_threshold

        result = {
            "quest": self._quest_number,
            "team": list(self._proposed_team),
            "success_count": success_count,
            "fail_count": fail_count,
            "result": "success" if quest_passed else "fail",
        }
        self._quest_results.append(result)
        self._highlight_turns.append(self._turn_number)

        if quest_passed:
            self._good_wins += 1
        else:
            self._evil_wins += 1

        # Check win conditions
        if self._good_wins >= 3:
            # Good wins 3 quests — but Assassin gets a shot
            self._start_assassination()
        elif self._evil_wins >= 3:
            self._finish_game("evil", "Evil won 3 quests")
        elif self._quest_number >= 5:
            # Shouldn't happen (one side must have 3 by quest 5)
            self._finish_game("evil", "All 5 quests completed without 3 good wins")
        else:
            # Next quest
            self._advance_leader()
            self._begin_quest()

    def _resolve_assassination(self, target: str) -> None:
        """Resolve the assassination attempt."""
        merlin = next(
            p for p in self._player_order if self._roles[p] == "merlin"
        )
        self._assassination_target = target
        self._assassination_correct = target == merlin

        if self._assassination_correct:
            self._finish_game("evil", "Assassin correctly identified Merlin")
        else:
            self._finish_game("good", "Merlin survived assassination")

    def _finish_game(self, winner: str, reason: str) -> None:
        """Score the game and start next (or terminate)."""
        self._game_winner = winner

        # Log the game
        self._game_log.append({
            "game": self._game_number,
            "winner": winner,
            "reason": reason,
            "quest_results": list(self._quest_results),
            "roles": dict(self._roles),
            "assassination_target": self._assassination_target,
            "assassination_correct": self._assassination_correct,
        })

        # Award points
        merlin_pid = next(
            (p for p in self._player_order if self._roles[p] == "merlin"),
            None,
        )
        assassin_pid = next(
            (p for p in self._player_order if self._roles[p] == "assassin"),
            None,
        )

        for pid in self._player_order:
            team = self._teams[pid]
            if team == winner:
                pts = WIN_GOOD_PTS if team == "good" else WIN_EVIL_PTS
                self._match_scores[pid] += pts

        # Bonus points
        if winner == "evil" and self._assassination_correct and assassin_pid:
            self._match_scores[assassin_pid] += ASSASSIN_BONUS
        if winner == "good" and merlin_pid:
            # Merlin survived — bonus
            self._match_scores[merlin_pid] += MERLIN_SURVIVAL_BONUS

        self._start_new_game()

    # ──────────────────────────────────────────────────────────────────
    # Core event interface
    # ──────────────────────────────────────────────────────────────────

    def current_player(self) -> str:
        if self._terminal:
            return self._player_order[0] if self._player_order else self._player_ids[0]
        if self._phase == Phase.DISCUSS:
            return self._discussion_order[self._discussion_idx]
        elif self._phase == Phase.NOMINATE:
            return self._leader
        elif self._phase == Phase.VOTE:
            return self._vote_order[self._vote_idx]
        elif self._phase == Phase.QUEST:
            # Next team member who hasn't played yet
            for pid in self._proposed_team:
                if pid not in self._quest_plays:
                    return pid
            return self._proposed_team[0]  # shouldn't happen
        elif self._phase == Phase.ASSASSINATE:
            return next(
                p for p in self._player_order if self._roles[p] == "assassin"
            )
        return self._player_order[0]

    def get_prompt(self, player_id: str) -> str:
        role = self._roles[player_id]
        team = self._teams[player_id]
        label = self._player_labels[player_id]
        knowledge = self._role_knowledge.get(player_id, {})

        lines: list[str] = []

        # Header
        lines.append(f"THE RESISTANCE: AVALON — Game {self._game_number} of {self._games_per_match}")
        lines.append(f"You are Player {label} ({player_id}).")
        lines.append("")

        # Role brief
        mordred_caveat = ""
        if any(self._roles[p] == "mordred" for p in self._player_order):
            mordred_caveat = " (except Mordred, who is invisible to you)"
        desc = ROLE_DESCRIPTIONS[role].format(mordred_caveat=mordred_caveat)
        lines.append(f"== YOUR ROLE ==")
        lines.append(desc)
        lines.append(f"Team: {team.upper()}")
        lines.append("")

        # Role knowledge
        if knowledge:
            lines.append("== YOUR SECRET KNOWLEDGE ==")
            if "evil_players" in knowledge:
                evil_labels = [
                    f"Player {self._player_labels[p]} ({p})"
                    for p in knowledge["evil_players"]
                ]
                lines.append(f"Evil players you can see: {', '.join(evil_labels)}")
            if "evil_allies" in knowledge:
                ally_labels = [
                    f"Player {self._player_labels[p]} ({p})"
                    for p in knowledge["evil_allies"]
                ]
                lines.append(f"Your evil allies: {', '.join(ally_labels)}")
            if "merlin_candidates" in knowledge:
                cand_labels = [
                    f"Player {self._player_labels[p]} ({p})"
                    for p in knowledge["merlin_candidates"]
                ]
                lines.append(f"Merlin candidates (one is Morgana): {', '.join(cand_labels)}")
            lines.append("")

        # Strategy hint
        lines.append(f"== STRATEGY ==")
        lines.append(STRATEGY_HINTS.get(role, "Play wisely."))
        lines.append("")

        # Game state
        lines.append("== GAME STATE ==")
        lines.append(f"Players: {', '.join(f'Player {self._player_labels[p]} ({p})' for p in self._player_order)}")
        lines.append(f"Quest {self._quest_number} of 5 | Team size needed: {self._quest_size}")
        lines.append(f"Quest scores — Good: {self._good_wins}, Evil: {self._evil_wins}")
        leader_label = f"Player {self._player_labels[self._leader]} ({self._leader})"
        lines.append(f"Current leader: {leader_label}")
        lines.append(f"Consecutive rejections: {self._consecutive_rejections}/5")
        lines.append("")

        # Quest history
        if self._quest_results:
            lines.append("== QUEST HISTORY ==")
            for qr in self._quest_results:
                lines.append(
                    f"Quest {qr['quest']}: {qr['result'].upper()} "
                    f"(team: {', '.join(qr['team'])} | "
                    f"{qr['success_count']} success, {qr['fail_count']} fail)"
                )
            lines.append("")

        # Proposal/vote history
        if self._proposal_history:
            lines.append("== PROPOSAL & VOTE HISTORY ==")
            for ph in self._proposal_history:
                status = "APPROVED" if ph["approved"] else "REJECTED"
                team_str = ", ".join(ph["proposed_team"])
                vote_summary = ", ".join(
                    f"{self._player_labels[p]}: {v}"
                    for p, v in ph["votes"].items()
                )
                lines.append(
                    f"Quest {ph['quest']} attempt {ph['attempt']}: "
                    f"{self._player_labels[ph['leader']]} proposed [{team_str}] "
                    f"— {status} ({vote_summary})"
                )
            lines.append("")

        # Discussion statements for current quest
        if self._discussion_statements:
            lines.append("== DISCUSSION (this quest) ==")
            for pid, stmt in self._discussion_statements.items():
                lines.append(f"Player {self._player_labels[pid]}: \"{stmt}\"")
            lines.append("")

        # Match scores
        lines.append("== MATCH SCORES ==")
        score_parts = []
        for pid in self._player_order:
            lbl = self._player_labels[pid]
            s = self._match_scores[pid]
            marker = " (you)" if pid == player_id else ""
            score_parts.append(f"{lbl}: {s:.0f}{marker}")
        lines.append(", ".join(score_parts))
        lines.append("")

        # Phase-specific instructions
        lines.append("== YOUR ACTION ==")
        if self._phase == Phase.DISCUSS:
            lines.append(
                "Make a public statement to all players. Discuss strategy, "
                "share suspicions, defend yourself, or coordinate. Everyone "
                "can see what you say. Your 'reasoning' field is private."
            )
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "discuss", "statement": "your public statement"}'
            )

        elif self._phase == Phase.NOMINATE:
            lines.append(
                f"You are the LEADER. Nominate a team of {self._quest_size} "
                f"players for Quest {self._quest_number}. Use player IDs."
            )
            lines.append(f"Available players: {', '.join(self._player_order)}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "nominate", '
                f'"team": ["player_id_1", ..., "player_id_{self._quest_size}"]}}'
            )

        elif self._phase == Phase.VOTE:
            team_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})"
                for p in self._proposed_team
            )
            lines.append(
                f"Leader {self._player_labels[self._leader]} proposed team: [{team_str}]"
            )
            lines.append("Vote to approve or reject this team.")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "vote", "vote": "approve" or "reject"}'
            )

        elif self._phase == Phase.QUEST:
            lines.append(
                f"You are on the quest team! Play your card secretly."
            )
            if team == "good":
                lines.append("As a GOOD player, you MUST play 'success'.")
            else:
                lines.append(
                    "As an EVIL player, you may play 'success' (to hide) "
                    "or 'fail' (to sabotage the quest)."
                )
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "quest", "play": "success" or "fail"}'
            )

        elif self._phase == Phase.ASSASSINATE:
            lines.append(
                "Good has won 3 quests! As the ASSASSIN, you have ONE chance "
                "to name Merlin. If you are correct, EVIL wins instead!"
            )
            non_evil = [
                f"Player {self._player_labels[p]} ({p})"
                for p in self._player_order
                if self._teams[p] == "good"
            ]
            lines.append(f"Good players: {', '.join(non_evil)}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "assassinate", "target": "player_id"}'
            )

        lines.append("")
        lines.append("IMPORTANT: Keep reasoning under 1024 tokens. Respond with ONLY valid JSON, no other text.")

        return "\n".join(lines)

    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        return (
            f"Your last action was invalid: {error_reason}\n\n"
            f"{self.get_prompt(player_id)}"
        )

    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        act = action.get("action")

        if self._phase == Phase.DISCUSS:
            if act != "discuss":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'discuss' action, got '{act}'.",
                )
            stmt = action.get("statement", "")
            if not stmt or not str(stmt).strip():
                return ValidationResult(
                    legal=False,
                    reason="Statement must not be empty.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.NOMINATE:
            if act != "nominate":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'nominate' action, got '{act}'.",
                )
            team = action.get("team", [])
            if not isinstance(team, list):
                return ValidationResult(
                    legal=False,
                    reason="Team must be a list of player IDs.",
                )
            if len(team) != self._quest_size:
                return ValidationResult(
                    legal=False,
                    reason=f"Team must have exactly {self._quest_size} players, got {len(team)}.",
                )
            valid_ids = set(self._player_order)
            for pid in team:
                if pid not in valid_ids:
                    return ValidationResult(
                        legal=False,
                        reason=f"Unknown player ID: '{pid}'.",
                    )
            if len(set(team)) != len(team):
                return ValidationResult(
                    legal=False,
                    reason="Team contains duplicate player IDs.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.VOTE:
            if act != "vote":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'vote' action, got '{act}'.",
                )
            vote = action.get("vote", "")
            if vote not in ("approve", "reject"):
                return ValidationResult(
                    legal=False,
                    reason=f"Vote must be 'approve' or 'reject', got '{vote}'.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.QUEST:
            if act != "quest":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'quest' action, got '{act}'.",
                )
            play = action.get("play", "")
            if play not in ("success", "fail"):
                return ValidationResult(
                    legal=False,
                    reason=f"Play must be 'success' or 'fail', got '{play}'.",
                )
            # Enforce: good players MUST play success
            if self._teams[player_id] == "good" and play == "fail":
                return ValidationResult(
                    legal=False,
                    reason="Good players MUST play 'success'. You cannot play 'fail'.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.ASSASSINATE:
            if act != "assassinate":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'assassinate' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._player_order:
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be a valid player ID, got '{target}'.",
                )
            if target == player_id:
                return ValidationResult(
                    legal=False,
                    reason="You cannot assassinate yourself.",
                )
            if self._teams.get(target) == "evil":
                return ValidationResult(
                    legal=False,
                    reason="You cannot assassinate a known evil player.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(legal=False, reason="Unknown game phase.")

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1

        if self._phase == Phase.DISCUSS:
            self._discussion_statements[player_id] = str(action["statement"]).strip()
            self._discussion_idx += 1
            if self._discussion_idx >= len(self._discussion_order):
                # All players have spoken — move to nomination
                self._start_nomination()

        elif self._phase == Phase.NOMINATE:
            self._proposed_team = list(action["team"])
            self._start_voting()

        elif self._phase == Phase.VOTE:
            self._votes[player_id] = action["vote"]
            self._vote_idx += 1
            if self._vote_idx >= len(self._vote_order):
                # All votes in — resolve
                self._resolve_vote()

        elif self._phase == Phase.QUEST:
            self._quest_plays[player_id] = action["play"]
            if len(self._quest_plays) >= len(self._proposed_team):
                # All quest plays in — resolve
                self._resolve_quest()

        elif self._phase == Phase.ASSASSINATE:
            self._resolve_assassination(action["target"])

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.DISCUSS:
            self.apply_action(player_id, {
                "action": "discuss",
                "statement": "(silence)",
            })
        elif self._phase == Phase.NOMINATE:
            # Pick first N players by seat order
            team = self._player_order[: self._quest_size]
            self.apply_action(player_id, {
                "action": "nominate",
                "team": team,
            })
        elif self._phase == Phase.VOTE:
            self.apply_action(player_id, {
                "action": "vote",
                "vote": "approve",
            })
        elif self._phase == Phase.QUEST:
            self.apply_action(player_id, {
                "action": "quest",
                "play": "success",
            })
        elif self._phase == Phase.ASSASSINATE:
            # Random non-evil player
            good_players = [
                p for p in self._player_order
                if self._teams[p] == "good"
            ]
            target = self._rng.choice(good_players) if good_players else self._player_order[0]
            self.apply_action(player_id, {
                "action": "assassinate",
                "target": target,
            })

    def eliminate_player(self, player_id: str) -> None:
        """Handle player elimination mid-game."""
        self._eliminated.add(player_id)

        # If they're the current actor, forfeit their turn
        if not self.is_terminal() and self.current_player() == player_id:
            self.forfeit_turn(player_id)

        # If too few players remain, end the match
        active = [p for p in self._player_order if p not in self._eliminated]
        if len(active) < 5:
            self._terminal = True

    def get_state_snapshot(self) -> dict:
        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "turn_number": self._turn_number,
            "phase": self._phase,
            "quest_number": self._quest_number,
            "quest_size": self._quest_size if self._quest_number > 0 else 0,
            "good_wins": self._good_wins,
            "evil_wins": self._evil_wins,
            "leader": self._leader if self._player_order else "",
            "leader_label": self._player_labels.get(self._leader, "") if self._player_order else "",
            "consecutive_rejections": self._consecutive_rejections,
            "proposed_team": list(self._proposed_team),
            "votes": dict(self._votes),
            "quest_plays": dict(self._quest_plays),
            "quest_results": list(self._quest_results),
            "discussion_statements": dict(self._discussion_statements),
            "proposal_history": list(self._proposal_history),
            "roles": dict(self._roles),
            "teams": dict(self._teams),
            "player_order": list(self._player_order),
            "player_labels": dict(self._player_labels),
            "match_scores": dict(self._match_scores),
            "terminal": self._terminal,
            "game_winner": self._game_winner,
            "assassination_target": self._assassination_target,
            "assassination_correct": self._assassination_correct,
            "game_log": list(self._game_log),
        }

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)

    # ──────────────────────────────────────────────────────────────────
    # Scoring override — direct points, not rank-based
    # ──────────────────────────────────────────────────────────────────

    def get_scores(self) -> dict[str, float]:
        return dict(self._match_scores)

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """On forfeit, award remaining games' points to others."""
        remaining = self._games_per_match - self._game_number + 1
        for pid in self._player_ids:
            if pid != forfeiting_player_id:
                self._match_scores[pid] += WIN_GOOD_PTS * remaining
        self._terminal = True
