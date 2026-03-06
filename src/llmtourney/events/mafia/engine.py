"""Mafia — classic hidden-role social deduction engine.

7 players (5 town / 2 mafia). 5 games per match.
Phases: DISCUSS -> ACCUSE -> VOTE -> (TIEBREAK) -> NIGHT_INVESTIGATE ->
        NIGHT_PROTECT -> NIGHT_KILL -> (reveal) -> loop.

Tests sustained deception, false accusation, vote coalition reading,
and self-defense under accusation. No mechanical fallback — every
decision is social.
"""

from __future__ import annotations

from collections import Counter

from llmtourney.events.base import MultiplayerSeriesEvent, ValidationResult

__all__ = ["MafiaEvent"]

# ── Role configurations by player count ──────────────────────────────

ROLE_CONFIGS = {
    6: {
        "town": ["sheriff", "doctor", "townsperson", "townsperson"],
        "mafia": ["godfather", "mafioso"],
    },
    7: {
        "town": ["sheriff", "doctor", "townsperson", "townsperson", "townsperson"],
        "mafia": ["godfather", "mafioso"],
    },
    8: {
        "town": ["sheriff", "doctor", "townsperson", "townsperson", "townsperson"],
        "mafia": ["godfather", "mafioso", "mafioso"],
    },
}

# ── Scoring ──────────────────────────────────────────────────────────

WIN_TOWN_PTS = 3
WIN_MAFIA_PTS = 4
SHERIFF_CORRECT_BONUS = 2
DOCTOR_SAVES_SHERIFF_BONUS = 3
GODFATHER_SURVIVAL_BONUS = 2
ACCUSER_MAFIA_ELIMINATION_BONUS = 1

# ── Phase constants ──────────────────────────────────────────────────


class Phase:
    DISCUSS = "discuss"
    ACCUSE = "accuse"
    VOTE = "vote"
    TIEBREAK = "tiebreak"
    NIGHT_INVESTIGATE = "night_investigate"
    NIGHT_PROTECT = "night_protect"
    NIGHT_KILL = "night_kill"


# ── Role strategy hints ─────────────────────────────────────────────

STRATEGY_HINTS = {
    "sheriff": (
        "You investigate one player per night and learn their alignment "
        "(Innocent/Mafia). The Godfather appears Innocent — don't over-trust "
        "a single result. Use your findings to guide town votes, but revealing "
        "your role publicly makes you a night kill target. Time your reveal "
        "carefully."
    ),
    "doctor": (
        "You protect one player each night from the Mafia's kill. You may "
        "protect yourself. Try to infer who the Mafia will target — typically "
        "the Sheriff, strong accusers, or players who've been effective. You "
        "can announce you're the Doctor to build trust, but this paints a "
        "target on you."
    ),
    "townsperson": (
        "You have no special ability. Your power is your vote and your voice. "
        "Analyze voting patterns, accusation behavior, and who defends whom. "
        "Mafia members will often cross-vote (accuse town) and protect each "
        "other (vote No on town elimination attempts)."
    ),
    "godfather": (
        "You appear Innocent to the Sheriff's investigation. You must seem "
        "like a trustworthy town member. Lead accusations against townspeople "
        "convincingly. At night, coordinate with your Mafioso on kill target — "
        "prioritize the Sheriff if identified, then strong accusers."
    ),
    "mafioso": (
        "You know the Godfather. You appear as Mafia to the Sheriff — if "
        "investigated and the Sheriff is alive, you're in danger. Act like "
        "town. Support the Godfather's accusations without appearing to move "
        "in lockstep. At night, vote to kill the Sheriff first, then anyone "
        "building a case against the Mafia."
    ),
}

# ── Role descriptions ────────────────────────────────────────────────

ROLE_DESCRIPTIONS = {
    "sheriff": (
        "SHERIFF (Town) — Each night, investigate one player to learn their "
        "alignment: Innocent or Mafia. The Godfather appears Innocent."
    ),
    "doctor": (
        "DOCTOR (Town) — Each night, protect one player from the Mafia's "
        "kill. You may protect yourself."
    ),
    "townsperson": (
        "TOWNSPERSON (Town) — No special ability. Use your vote and voice "
        "to find and eliminate the Mafia."
    ),
    "godfather": (
        "GODFATHER (Mafia) — You lead the Mafia. You appear Innocent if "
        "investigated by the Sheriff. Your kill vote breaks ties at night."
    ),
    "mafioso": (
        "MAFIOSO (Mafia) — You know who the Godfather is. You appear as "
        "Mafia if investigated by the Sheriff. Vote on night kill targets."
    ),
}

# Maximum rounds before forced game end (prevents infinite loops)
MAX_ROUNDS = 10


class MafiaEvent(MultiplayerSeriesEvent):
    """Classic Mafia — hidden role social deduction.

    Parameters
    ----------
    games_per_match : int
        Number of full Mafia games per match (default 5).
    num_players : int
        Number of players (6-8, default 7).
    fixed_roles : dict[str, str] | None
        Optional mapping of player_id -> role for testing.
    """

    def __init__(
        self,
        games_per_match: int = 5,
        num_players: int = 7,
        fixed_roles: dict[str, str] | None = None,
    ) -> None:
        if num_players not in ROLE_CONFIGS:
            raise ValueError(f"Mafia supports 6-8 players, got {num_players}")
        super().__init__(games_per_match, num_players)
        self._fixed_roles = fixed_roles

        # Per-game state (initialized in _start_new_game)
        self._roles: dict[str, str] = {}
        self._teams: dict[str, str] = {}
        self._alive: list[str] = []
        self._round_number: int = 0
        self._phase: str = Phase.DISCUSS

        # Discussion tracking
        self._discussion_statements: dict[str, str] = {}
        self._discussion_order: list[str] = []
        self._discussion_idx: int = 0

        # Accusation tracking (simultaneous but collected sequentially)
        self._accusations: dict[str, str] = {}
        self._accuse_order: list[str] = []
        self._accuse_idx: int = 0

        # Vote tracking
        self._vote_target: str = ""
        self._votes: dict[str, str] = {}
        self._vote_order: list[str] = []
        self._vote_idx: int = 0

        # Tiebreak tracking
        self._tiebreak_candidates: list[str] = []
        self._tiebreak_votes: dict[str, str] = {}
        self._tiebreak_order: list[str] = []
        self._tiebreak_idx: int = 0

        # Night action tracking
        self._night_investigate_target: str = ""
        self._night_protect_target: str = ""
        self._night_kill_votes: dict[str, str] = {}
        self._night_kill_order: list[str] = []
        self._night_kill_idx: int = 0

        # Accumulated knowledge
        self._investigation_results: dict[str, str] = {}
        self._protection_history: list[str] = []

        # Game history
        self._eliminated_players: list[dict] = []
        self._round_history: list[dict] = []
        self._game_log: list[dict] = []
        self._game_winner: str = ""
        self._turn_number: int = 0
        self._player_order: list[str] = []

        # Bonus tracking
        self._sheriff_triggered_eliminations: set[str] = set()
        self._doctor_saved_sheriff: bool = False
        self._current_round_data: dict = {}

    @property
    def display_name(self) -> str:
        return "Mafia"

    # ──────────────────────────────────────────────────────────────────
    # Game lifecycle
    # ──────────────────────────────────────────────────────────────────

    def _start_new_game(self) -> None:
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return

        self._round_number = 0
        self._eliminated_players = []
        self._round_history = []
        self._turn_number = 0
        self._game_winner = ""
        self._investigation_results = {}
        self._protection_history = []
        self._sheriff_triggered_eliminations = set()
        self._doctor_saved_sheriff = False

        # Randomize player seating order
        self._player_order = list(self._player_ids)
        self._rng.shuffle(self._player_order)

        # Assign roles
        self._assign_roles()

        # All players start alive
        self._alive = list(self._player_order)

        # Start first round
        self._begin_round()

    def _assign_roles(self) -> None:
        """Assign roles to players (fixed if provided, else random)."""
        town_roles = {"sheriff", "doctor", "townsperson"}

        if self._fixed_roles and len(self._fixed_roles) == self._num_players:
            self._roles = dict(self._fixed_roles)
            self._teams = {
                pid: "town" if role in town_roles else "mafia"
                for pid, role in self._roles.items()
            }
            return

        config = ROLE_CONFIGS[self._num_players]
        all_roles = list(config["town"]) + list(config["mafia"])
        self._rng.shuffle(all_roles)

        self._roles = {}
        self._teams = {}
        for i, pid in enumerate(self._player_order):
            role = all_roles[i]
            self._roles[pid] = role
            self._teams[pid] = "town" if role in town_roles else "mafia"

    def _begin_round(self) -> None:
        """Start a new day/night cycle."""
        self._round_number += 1
        self._current_round_data = {"round": self._round_number}
        self._start_discussion()

    def _start_discussion(self) -> None:
        self._phase = Phase.DISCUSS
        self._discussion_statements = {}
        self._discussion_order = [p for p in self._player_order if p in self._alive]
        self._discussion_idx = 0

    def _start_accusation(self) -> None:
        self._phase = Phase.ACCUSE
        self._accusations = {}
        self._accuse_order = [p for p in self._player_order if p in self._alive]
        self._accuse_idx = 0

    def _start_voting(self, target: str) -> None:
        self._phase = Phase.VOTE
        self._vote_target = target
        self._votes = {}
        self._vote_order = [p for p in self._player_order if p in self._alive]
        self._vote_idx = 0

    def _start_tiebreak(self, candidates: list[str]) -> None:
        self._phase = Phase.TIEBREAK
        self._tiebreak_candidates = candidates
        self._tiebreak_votes = {}
        self._tiebreak_order = [p for p in self._player_order if p in self._alive]
        self._tiebreak_idx = 0

    def _start_night_investigate(self) -> None:
        self._phase = Phase.NIGHT_INVESTIGATE
        self._night_investigate_target = ""
        sheriff = self._find_living_role("sheriff")
        if not sheriff:
            # Sheriff is dead, skip to protect
            self._start_night_protect()

    def _start_night_protect(self) -> None:
        self._phase = Phase.NIGHT_PROTECT
        self._night_protect_target = ""
        doctor = self._find_living_role("doctor")
        if not doctor:
            # Doctor is dead, skip to kill
            self._start_night_kill()

    def _start_night_kill(self) -> None:
        self._phase = Phase.NIGHT_KILL
        self._night_kill_votes = {}
        living_mafia = [p for p in self._alive if self._teams[p] == "mafia"]
        self._night_kill_order = living_mafia
        self._night_kill_idx = 0
        if not living_mafia:
            # All mafia dead (shouldn't happen — game should have ended)
            self._finish_game("town", "All mafia eliminated")

    def _find_living_role(self, role: str) -> str | None:
        """Find the living player with the given role, or None."""
        for pid in self._alive:
            if self._roles.get(pid) == role:
                return pid
        return None

    # ──────────────────────────────────────────────────────────────────
    # Resolution
    # ──────────────────────────────────────────────────────────────────

    def _resolve_accusations(self) -> None:
        """Resolve simultaneous accusations → voting or tiebreak."""
        self._current_round_data["accusations"] = dict(self._accusations)

        counts = Counter(self._accusations.values())
        if not counts:
            # No accusations (shouldn't happen)
            self._transition_to_night()
            return

        max_count = max(counts.values())
        most_accused = [pid for pid, c in counts.items() if c == max_count]

        if len(most_accused) == 1:
            self._start_voting(most_accused[0])
        else:
            # Tied — tiebreak vote among tied candidates
            self._start_tiebreak(most_accused)

    def _resolve_tiebreak(self) -> None:
        """Resolve tiebreak votes → pick single candidate for trial."""
        counts = Counter(self._tiebreak_votes.values())
        if not counts:
            # No votes somehow — no elimination
            self._current_round_data["tiebreak"] = dict(self._tiebreak_votes)
            self._current_round_data["day_elimination"] = None
            self._transition_to_night()
            return

        max_count = max(counts.values())
        winners = [pid for pid, c in counts.items() if c == max_count]

        if len(winners) == 1:
            target = winners[0]
        else:
            # Still tied after tiebreak — no elimination
            self._current_round_data["tiebreak"] = dict(self._tiebreak_votes)
            self._current_round_data["day_elimination"] = None
            self._transition_to_night()
            return

        self._current_round_data["tiebreak"] = dict(self._tiebreak_votes)
        self._start_voting(target)

    def _resolve_vote(self) -> None:
        """Resolve YES/NO vote on the accused."""
        self._current_round_data["vote_target"] = self._vote_target
        self._current_round_data["votes"] = dict(self._votes)

        yes_count = sum(1 for v in self._votes.values() if v == "yes")
        no_count = len(self._votes) - yes_count

        if yes_count > no_count:
            # Majority YES — eliminate
            eliminated_pid = self._vote_target
            eliminated_role = self._roles[eliminated_pid]
            self._alive.remove(eliminated_pid)
            elim_record = {
                "player_id": eliminated_pid,
                "role": eliminated_role,
                "round": self._round_number,
                "eliminated_by": "vote",
            }
            self._eliminated_players.append(elim_record)
            self._current_round_data["day_elimination"] = elim_record
            self._highlight_turns.append(self._turn_number)

            # Track accuser bonus — who accused the eliminated player?
            if self._teams[eliminated_pid] == "mafia":
                for accuser, target in self._accusations.items():
                    if target == eliminated_pid:
                        self._match_scores[accuser] += ACCUSER_MAFIA_ELIMINATION_BONUS

                # Track sheriff-triggered eliminations
                sheriff = self._find_living_role("sheriff")
                if sheriff is None:
                    # Sheriff might have just been the one eliminated, check roles
                    for pid in self._player_ids:
                        if self._roles.get(pid) == "sheriff" and pid != eliminated_pid:
                            sheriff = pid
                            break
                if sheriff and eliminated_pid in self._investigation_results:
                    if self._investigation_results[eliminated_pid] == "mafia":
                        self._sheriff_triggered_eliminations.add(eliminated_pid)

            # Check win condition after day elimination
            if self._check_win():
                return
        else:
            # Tied or majority NO — no elimination
            self._current_round_data["day_elimination"] = None

        self._transition_to_night()

    def _transition_to_night(self) -> None:
        """Move from day phase to night phase."""
        self._start_night_investigate()

    def _resolve_night(self) -> None:
        """Resolve all night actions simultaneously."""
        # 1. Sheriff investigation result (already stored when action was applied)

        # 2. Resolve mafia kill target
        kill_target = self._resolve_mafia_kill_target()

        # 3. Check Doctor protection
        saved = False
        night_killed_pid = None

        if kill_target:
            if kill_target == self._night_protect_target:
                saved = True
                # Check doctor-saves-sheriff bonus
                if self._roles.get(kill_target) == "sheriff":
                    self._doctor_saved_sheriff = True
            else:
                # Kill succeeds
                night_killed_pid = kill_target
                self._alive.remove(kill_target)
                elim_record = {
                    "player_id": kill_target,
                    "role": self._roles[kill_target],
                    "round": self._round_number,
                    "eliminated_by": "night_kill",
                }
                self._eliminated_players.append(elim_record)
                self._highlight_turns.append(self._turn_number)

        # Record round data
        self._current_round_data["night_kill_target"] = kill_target
        self._current_round_data["night_saved"] = saved
        self._current_round_data["night_kill_announced"] = night_killed_pid
        self._round_history.append(self._current_round_data)

        # Check win conditions after night
        if self._check_win():
            return

        # Safety: max rounds
        if self._round_number >= MAX_ROUNDS:
            self._finish_game("mafia", f"Game reached {MAX_ROUNDS} rounds")
            return

        # Next round
        self._begin_round()

    def _resolve_mafia_kill_target(self) -> str | None:
        """Resolve mafia kill votes. Godfather breaks ties."""
        if not self._night_kill_votes:
            return None

        counts = Counter(self._night_kill_votes.values())
        max_count = max(counts.values())
        candidates = [t for t, c in counts.items() if c == max_count]

        if len(candidates) == 1:
            return candidates[0]

        # Tie — Godfather's choice wins
        godfather = self._find_living_role("godfather")
        if godfather and godfather in self._night_kill_votes:
            return self._night_kill_votes[godfather]

        # Fallback: random from tied
        return self._rng.choice(candidates)

    def _check_win(self) -> bool:
        """Check win conditions. Returns True if game ended."""
        town_alive = sum(1 for p in self._alive if self._teams[p] == "town")
        mafia_alive = sum(1 for p in self._alive if self._teams[p] == "mafia")

        if mafia_alive == 0:
            self._finish_game("town", "All mafia eliminated")
            return True
        if mafia_alive >= town_alive:
            self._finish_game("mafia", "Mafia reached numerical majority")
            return True
        return False

    def _finish_game(self, winner: str, reason: str) -> None:
        """Score the game and start next (or terminate)."""
        self._game_winner = winner

        self._game_log.append({
            "game": self._game_number,
            "winner": winner,
            "reason": reason,
            "rounds": self._round_number,
            "roles": dict(self._roles),
            "eliminated": list(self._eliminated_players),
            "round_history": list(self._round_history),
        })

        # Award points to winning team survivors
        for pid in self._alive:
            team = self._teams[pid]
            if team == winner:
                pts = WIN_TOWN_PTS if team == "town" else WIN_MAFIA_PTS
                self._match_scores[pid] += pts

        # Special bonuses
        # Sheriff correctly identified mafia that got eliminated
        sheriff_pid = next(
            (p for p in self._player_ids if self._roles.get(p) == "sheriff"),
            None,
        )
        if sheriff_pid and self._sheriff_triggered_eliminations:
            self._match_scores[sheriff_pid] += (
                SHERIFF_CORRECT_BONUS * len(self._sheriff_triggered_eliminations)
            )

        # Doctor saved sheriff
        if self._doctor_saved_sheriff:
            doctor_pid = next(
                (p for p in self._player_ids if self._roles.get(p) == "doctor"),
                None,
            )
            if doctor_pid:
                self._match_scores[doctor_pid] += DOCTOR_SAVES_SHERIFF_BONUS

        # Godfather survival bonus
        godfather_pid = next(
            (p for p in self._player_ids if self._roles.get(p) == "godfather"),
            None,
        )
        if godfather_pid and godfather_pid in self._alive:
            self._match_scores[godfather_pid] += GODFATHER_SURVIVAL_BONUS

        self._start_new_game()

    # ──────────────────────────────────────────────────────────────────
    # Core event interface
    # ──────────────────────────────────────────────────────────────────

    def current_player(self) -> str:
        if self._terminal:
            return self._player_order[0] if self._player_order else self._player_ids[0]

        if self._phase == Phase.DISCUSS:
            return self._discussion_order[self._discussion_idx]
        elif self._phase == Phase.ACCUSE:
            return self._accuse_order[self._accuse_idx]
        elif self._phase == Phase.VOTE:
            return self._vote_order[self._vote_idx]
        elif self._phase == Phase.TIEBREAK:
            return self._tiebreak_order[self._tiebreak_idx]
        elif self._phase == Phase.NIGHT_INVESTIGATE:
            sheriff = self._find_living_role("sheriff")
            return sheriff if sheriff else self._alive[0]
        elif self._phase == Phase.NIGHT_PROTECT:
            doctor = self._find_living_role("doctor")
            return doctor if doctor else self._alive[0]
        elif self._phase == Phase.NIGHT_KILL:
            return self._night_kill_order[self._night_kill_idx]

        return self._player_order[0]

    def get_prompt(self, player_id: str) -> str:
        role = self._roles[player_id]
        team = self._teams[player_id]
        label = self._player_labels[player_id]

        lines: list[str] = []

        # Header
        lines.append(f"MAFIA — Game {self._game_number} of {self._games_per_match}")
        lines.append(f"You are Player {label} ({player_id}).")
        lines.append("")

        # Role
        lines.append("== YOUR ROLE ==")
        lines.append(ROLE_DESCRIPTIONS[role])
        lines.append(f"Team: {team.upper()}")
        lines.append("")

        # Secret knowledge
        knowledge_lines = self._build_knowledge_lines(player_id, role)
        if knowledge_lines:
            lines.append("== YOUR SECRET KNOWLEDGE ==")
            lines.extend(knowledge_lines)
            lines.append("")

        # Strategy
        lines.append("== STRATEGY ==")
        lines.append(STRATEGY_HINTS.get(role, "Play wisely."))
        lines.append("")

        # Game state
        lines.append("== GAME STATE ==")
        alive_str = ", ".join(
            f"Player {self._player_labels[p]} ({p})" for p in self._alive
        )
        lines.append(f"Living players ({len(self._alive)}): {alive_str}")

        if self._eliminated_players:
            lines.append("Eliminated players:")
            for ep in self._eliminated_players:
                lbl = self._player_labels[ep["player_id"]]
                lines.append(
                    f"  Player {lbl} ({ep['player_id']}) — {ep['role']} "
                    f"(round {ep['round']}, {ep['eliminated_by']})"
                )

        lines.append(f"Round: {self._round_number}")
        lines.append("")

        # Round history
        if self._round_history:
            lines.append("== ROUND HISTORY ==")
            for rh in self._round_history:
                lines.append(f"--- Round {rh['round']} ---")
                if "discussion" in rh:
                    for pid, stmt in rh["discussion"].items():
                        lbl = self._player_labels[pid]
                        lines.append(f"  {lbl}: \"{stmt}\"")
                if "accusations" in rh:
                    acc_parts = []
                    for pid, target in rh["accusations"].items():
                        acc_parts.append(
                            f"{self._player_labels[pid]}→{self._player_labels[target]}"
                        )
                    lines.append(f"  Accusations: {', '.join(acc_parts)}")
                if rh.get("vote_target"):
                    vt_label = self._player_labels[rh["vote_target"]]
                    vote_parts = []
                    for pid, v in rh.get("votes", {}).items():
                        vote_parts.append(f"{self._player_labels[pid]}: {v}")
                    lines.append(f"  Vote on {vt_label}: {', '.join(vote_parts)}")
                if rh.get("day_elimination"):
                    de = rh["day_elimination"]
                    lbl = self._player_labels[de["player_id"]]
                    lines.append(f"  Day elimination: Player {lbl} ({de['role']})")
                elif rh.get("vote_target"):
                    lines.append("  Day elimination: None (vote failed)")
                if rh.get("night_kill_announced"):
                    nk = rh["night_kill_announced"]
                    nk_role = self._roles.get(nk, "unknown")
                    lbl = self._player_labels[nk]
                    lines.append(f"  Night kill: Player {lbl} ({nk_role})")
                elif rh.get("night_saved"):
                    lines.append("  Night: The village slept peacefully (someone was saved)")
                else:
                    lines.append("  Night: The village slept peacefully")
            lines.append("")

        # Current round discussion (if in progress)
        if self._discussion_statements and self._phase != Phase.DISCUSS:
            lines.append("== DISCUSSION (this round) ==")
            for pid, stmt in self._discussion_statements.items():
                lbl = self._player_labels[pid]
                lines.append(f"Player {lbl}: \"{stmt}\"")
            lines.append("")
        elif self._discussion_statements and self._phase == Phase.DISCUSS:
            # Show statements from players who have already spoken
            spoken = {
                pid: stmt for pid, stmt in self._discussion_statements.items()
            }
            if spoken:
                lines.append("== DISCUSSION (this round, so far) ==")
                for pid, stmt in spoken.items():
                    lbl = self._player_labels[pid]
                    lines.append(f"Player {lbl}: \"{stmt}\"")
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
        self._append_action_instructions(lines, player_id, role, team)
        lines.append("")
        lines.append(
            "IMPORTANT: Keep reasoning under 1024 tokens. "
            "Respond with ONLY valid JSON, no other text."
        )

        return "\n".join(lines)

    def _build_knowledge_lines(
        self, player_id: str, role: str
    ) -> list[str]:
        """Build role-specific secret knowledge lines."""
        lines: list[str] = []

        if role in ("godfather", "mafioso"):
            allies = [
                f"Player {self._player_labels[p]} ({p})"
                for p in self._alive
                if self._teams[p] == "mafia" and p != player_id
            ]
            dead_allies = [
                f"Player {self._player_labels[p]} ({p}) [ELIMINATED]"
                for p in self._player_ids
                if self._teams.get(p) == "mafia"
                and p != player_id
                and p not in self._alive
            ]
            if allies:
                lines.append(f"Your mafia allies (alive): {', '.join(allies)}")
            if dead_allies:
                lines.append(f"Your mafia allies (dead): {', '.join(dead_allies)}")

        elif role == "sheriff" and self._investigation_results:
            lines.append("Your investigation results:")
            for target, result in self._investigation_results.items():
                lbl = self._player_labels[target]
                status = "alive" if target in self._alive else "ELIMINATED"
                lines.append(f"  Player {lbl} ({target}): {result} [{status}]")

        elif role == "doctor" and self._protection_history:
            recent = self._protection_history[-5:]  # last 5
            labels = [self._player_labels[p] for p in recent]
            lines.append(f"Recent protections: {', '.join(labels)}")

        return lines

    def _append_action_instructions(
        self,
        lines: list[str],
        player_id: str,
        _role: str,
        _team: str,
    ) -> None:
        """Append phase-specific action instructions to prompt."""
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

        elif self._phase == Phase.ACCUSE:
            valid_targets = [p for p in self._alive if p != player_id]
            targets_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})" for p in valid_targets
            )
            lines.append(
                "Name ONE player you want to put on trial for elimination. "
                "All players submit their accusation simultaneously — no one "
                "sees others' picks until all are in. The most-accused player "
                "goes to a YES/NO vote."
            )
            lines.append(f"Valid targets: {targets_str}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "accuse", "target": "player_id"}'
            )

        elif self._phase == Phase.VOTE:
            target_label = (
                f"Player {self._player_labels[self._vote_target]} "
                f"({self._vote_target})"
            )
            lines.append(
                f"Should {target_label} be eliminated? "
                "Vote YES to eliminate or NO to spare."
            )
            # Show accusation results
            counts = Counter(self._accusations.values())
            acc_summary = ", ".join(
                f"{self._player_labels[t]}: {c}" for t, c in counts.most_common()
            )
            lines.append(f"Accusation totals: {acc_summary}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "vote", "vote": "yes" or "no"}'
            )

        elif self._phase == Phase.TIEBREAK:
            cand_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})"
                for p in self._tiebreak_candidates
            )
            lines.append(
                f"Accusations were tied between: {cand_str}. "
                "Pick ONE of these players to put on trial."
            )
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "tiebreak", "target": "player_id"}'
            )

        elif self._phase == Phase.NIGHT_INVESTIGATE:
            valid = [p for p in self._alive if p != player_id]
            targets_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})" for p in valid
            )
            lines.append(
                "NIGHT PHASE — You are the Sheriff. Choose one player to "
                "investigate. You will learn if they are Innocent or Mafia. "
                "Note: the Godfather appears Innocent."
            )
            lines.append(f"Valid targets: {targets_str}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "investigate", "target": "player_id"}'
            )

        elif self._phase == Phase.NIGHT_PROTECT:
            targets_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})" for p in self._alive
            )
            lines.append(
                "NIGHT PHASE — You are the Doctor. Choose one player to "
                "protect tonight. If the Mafia targets them, they will "
                "survive. You may protect yourself."
            )
            lines.append(f"Valid targets: {targets_str}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "protect", "target": "player_id"}'
            )

        elif self._phase == Phase.NIGHT_KILL:
            valid = [p for p in self._alive if self._teams[p] == "town"]
            targets_str = ", ".join(
                f"Player {self._player_labels[p]} ({p})" for p in valid
            )
            lines.append(
                "NIGHT PHASE — Choose a town player to kill tonight. "
                "If both mafia members vote for the same target, that player "
                "dies (unless the Doctor protects them). If you disagree, "
                "the Godfather's choice wins."
            )
            lines.append(f"Valid targets: {targets_str}")
            lines.append("")
            lines.append(
                'Respond with ONLY JSON: {"reasoning": "...", '
                '"action": "kill", "target": "player_id"}'
            )

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
                    legal=False, reason="Statement must not be empty."
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.ACCUSE:
            if act != "accuse":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'accuse' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._alive:
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be a living player, got '{target}'.",
                )
            if target == player_id:
                return ValidationResult(
                    legal=False, reason="You cannot accuse yourself."
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.VOTE:
            if act != "vote":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'vote' action, got '{act}'.",
                )
            vote = action.get("vote", "")
            if vote not in ("yes", "no"):
                return ValidationResult(
                    legal=False,
                    reason=f"Vote must be 'yes' or 'no', got '{vote}'.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.TIEBREAK:
            if act != "tiebreak":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'tiebreak' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._tiebreak_candidates:
                valid = ", ".join(self._tiebreak_candidates)
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be one of [{valid}], got '{target}'.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.NIGHT_INVESTIGATE:
            if act != "investigate":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'investigate' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._alive:
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be a living player, got '{target}'.",
                )
            if target == player_id:
                return ValidationResult(
                    legal=False,
                    reason="You cannot investigate yourself.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.NIGHT_PROTECT:
            if act != "protect":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'protect' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._alive:
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be a living player, got '{target}'.",
                )
            return ValidationResult(legal=True)

        elif self._phase == Phase.NIGHT_KILL:
            if act != "kill":
                return ValidationResult(
                    legal=False,
                    reason=f"Expected 'kill' action, got '{act}'.",
                )
            target = action.get("target", "")
            if target not in self._alive:
                return ValidationResult(
                    legal=False,
                    reason=f"Target must be a living player, got '{target}'.",
                )
            if self._teams.get(target) == "mafia":
                return ValidationResult(
                    legal=False,
                    reason="You cannot kill a fellow mafia member.",
                )
            return ValidationResult(legal=True)

        return ValidationResult(legal=False, reason="Unknown game phase.")

    def apply_action(self, player_id: str, action: dict) -> None:
        self._turn_number += 1

        if self._phase == Phase.DISCUSS:
            self._discussion_statements[player_id] = str(
                action["statement"]
            ).strip()
            self._discussion_idx += 1
            if self._discussion_idx >= len(self._discussion_order):
                self._current_round_data["discussion"] = dict(
                    self._discussion_statements
                )
                self._start_accusation()

        elif self._phase == Phase.ACCUSE:
            self._accusations[player_id] = action["target"]
            self._accuse_idx += 1
            if self._accuse_idx >= len(self._accuse_order):
                self._resolve_accusations()

        elif self._phase == Phase.VOTE:
            self._votes[player_id] = action["vote"]
            self._vote_idx += 1
            if self._vote_idx >= len(self._vote_order):
                self._resolve_vote()

        elif self._phase == Phase.TIEBREAK:
            self._tiebreak_votes[player_id] = action["target"]
            self._tiebreak_idx += 1
            if self._tiebreak_idx >= len(self._tiebreak_order):
                self._resolve_tiebreak()

        elif self._phase == Phase.NIGHT_INVESTIGATE:
            target = action["target"]
            self._night_investigate_target = target
            # Godfather appears innocent
            if self._roles.get(target) == "godfather":
                result = "innocent"
            elif self._teams.get(target) == "mafia":
                result = "mafia"
            else:
                result = "innocent"
            self._investigation_results[target] = result
            self._start_night_protect()

        elif self._phase == Phase.NIGHT_PROTECT:
            self._night_protect_target = action["target"]
            self._protection_history.append(action["target"])
            self._start_night_kill()

        elif self._phase == Phase.NIGHT_KILL:
            self._night_kill_votes[player_id] = action["target"]
            self._night_kill_idx += 1
            if self._night_kill_idx >= len(self._night_kill_order):
                self._resolve_night()

    def forfeit_turn(self, player_id: str) -> None:
        if self._phase == Phase.DISCUSS:
            self.apply_action(player_id, {
                "action": "discuss",
                "statement": "(silence)",
            })
        elif self._phase == Phase.ACCUSE:
            valid = [p for p in self._alive if p != player_id]
            target = self._rng.choice(valid) if valid else self._alive[0]
            self.apply_action(player_id, {
                "action": "accuse",
                "target": target,
            })
        elif self._phase == Phase.VOTE:
            self.apply_action(player_id, {
                "action": "vote",
                "vote": "no",
            })
        elif self._phase == Phase.TIEBREAK:
            target = self._rng.choice(self._tiebreak_candidates)
            self.apply_action(player_id, {
                "action": "tiebreak",
                "target": target,
            })
        elif self._phase == Phase.NIGHT_INVESTIGATE:
            valid = [p for p in self._alive if p != player_id]
            target = self._rng.choice(valid) if valid else self._alive[0]
            self.apply_action(player_id, {
                "action": "investigate",
                "target": target,
            })
        elif self._phase == Phase.NIGHT_PROTECT:
            # Default: self-protect
            self.apply_action(player_id, {
                "action": "protect",
                "target": player_id,
            })
        elif self._phase == Phase.NIGHT_KILL:
            town = [p for p in self._alive if self._teams[p] == "town"]
            target = self._rng.choice(town) if town else self._alive[0]
            self.apply_action(player_id, {
                "action": "kill",
                "target": target,
            })

    def eliminate_player(self, player_id: str) -> None:
        """Handle player elimination mid-game (from strikes/forfeit)."""
        if player_id in self._alive:
            self._alive.remove(player_id)

        # If they're the current actor, forfeit their turn
        if not self.is_terminal() and self.current_player() == player_id:
            self.forfeit_turn(player_id)

        # If too few players remain, end the match
        if len(self._alive) < 3:
            self._terminal = True

    def get_state_snapshot(self) -> dict:
        return {
            "game_number": self._game_number,
            "games_per_match": self._games_per_match,
            "turn_number": self._turn_number,
            "phase": self._phase,
            "round_number": self._round_number,
            "alive": list(self._alive),
            "roles": dict(self._roles),
            "teams": dict(self._teams),
            "player_order": list(self._player_order),
            "player_labels": dict(self._player_labels),
            "match_scores": dict(self._match_scores),
            "terminal": self._terminal,
            "game_winner": self._game_winner,
            "discussion_statements": dict(self._discussion_statements),
            "accusations": dict(self._accusations),
            "vote_target": self._vote_target,
            "votes": dict(self._votes),
            "tiebreak_candidates": list(self._tiebreak_candidates),
            "tiebreak_votes": dict(self._tiebreak_votes),
            "night_kill_votes": dict(self._night_kill_votes),
            "eliminated_players": list(self._eliminated_players),
            "round_history": list(self._round_history),
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
                self._match_scores[pid] += WIN_TOWN_PTS * remaining
        self._terminal = True
