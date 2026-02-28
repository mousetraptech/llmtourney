"""Event — abstract base class for all tournament events.

Each event is a self-contained game engine that implements this interface.
The TournamentEngine interacts with events only through these methods.

Class hierarchy:
    Event (ABC)
    ├── TwoPlayerSeriesEvent — best-of-N series for 2-player board games
    │   ├── CheckersEvent, TicTacToeEvent, ConnectFourEvent, ReversiEvent
    └── MultiplayerSeriesEvent — N-player series with rank-based scoring
        ├── BullshitEvent, LiarsDiceEvent, YahtzeeEvent
    (HoldemEvent and ScrabbleEvent extend Event directly)
"""

from __future__ import annotations

import random
import string
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from llmtourney.core.schemas import load_schema


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a player's action against game rules."""

    legal: bool
    reason: str | None = None


class Event(ABC):
    """Abstract base for tournament events.

    Subclasses must set ``_player_ids``, ``_action_schema``, and
    ``_terminal`` before the tournament engine calls any methods.
    """

    # ------------------------------------------------------------------
    # Concrete — identical in every engine
    # ------------------------------------------------------------------

    def is_terminal(self) -> bool:
        """Return True if the game/match is over."""
        return self._terminal

    def force_forfeit_match(self, player_id: str) -> None:
        """Force-end the match (stuck-loop or escalation)."""
        self._terminal = True

    @property
    def player_ids(self) -> list[str]:
        """Return ordered list of player IDs for this event."""
        return list(self._player_ids)

    @property
    def action_schema(self) -> dict:
        """Return the JSON Schema for valid actions in this event."""
        return self._action_schema

    @property
    def display_name(self) -> str:
        """Human-readable display name for this event.

        Defaults to the class name without 'Event' suffix.
        Override for custom display names (e.g., Roller Derby).
        """
        name = type(self).__name__
        return name.removesuffix("Event") or name

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining games/chips to opponent on match forfeit.

        Default implementation delegates to force_forfeit_match.
        Series-based and chip-based engines should override.
        """
        self.force_forfeit_match(forfeiting_player_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_event_schema(self) -> dict:
        """Load schema.json from the subclass's package directory."""
        mod = sys.modules[type(self).__module__]
        schema_path = Path(mod.__file__).parent / "schema.json"
        return load_schema(schema_path)

    # ------------------------------------------------------------------
    # Abstract — must be implemented by every engine
    # ------------------------------------------------------------------

    @abstractmethod
    def reset(self, seed: int) -> None:
        """Initialize/reset game state with the given seed."""

    @abstractmethod
    def current_player(self) -> str:
        """Return the player ID whose turn it is."""

    @abstractmethod
    def get_prompt(self, player_id: str) -> str:
        """Generate the prompt for the given player based on current state."""

    @abstractmethod
    def get_retry_prompt(self, player_id: str, error_reason: str) -> str:
        """Generate a retry prompt explaining what went wrong."""

    @abstractmethod
    def validate_action(self, player_id: str, action: dict) -> ValidationResult:
        """Check if an action is legal. Does not modify state."""

    @abstractmethod
    def apply_action(self, player_id: str, action: dict) -> None:
        """Apply a validated action to the game state."""

    @abstractmethod
    def forfeit_turn(self, player_id: str) -> None:
        """Apply the default forfeit action (check if free, else fold/pass)."""

    @abstractmethod
    def get_scores(self) -> dict[str, float]:
        """Return final scores. Only meaningful when is_terminal() is True."""

    @abstractmethod
    def get_state_snapshot(self) -> dict:
        """Return a serializable snapshot of the current game state."""

    @abstractmethod
    def get_highlight_hands(self) -> list[int]:
        """Return list of hand/turn numbers flagged as highlights."""


# ======================================================================
# TwoPlayerSeriesEvent
# ======================================================================

class TwoPlayerSeriesEvent(Event):
    """Base for 2-player best-of-N series games.

    Provides common init, reset, scoring, opponent helper, and the
    advance-or-end loop.  Subclasses implement ``_init_game_state()``
    for board/game-specific reset.
    """

    def __init__(self, games_per_match: int = 9) -> None:
        self._games_per_match = games_per_match
        self._player_ids = ["player_a", "player_b"]
        self._action_schema = self._load_event_schema()

        # Series-level state (reset in reset())
        self._game_number: int = 0
        self._game_results: list[str] = []
        self._series_scores: dict[str, float] = {}
        self._turn_number: int = 0
        self._game_turn: int = 0
        self._terminal: bool = False
        self._first_player: str = ""

    def reset(self, seed: int) -> None:
        self._active_player = self._player_ids[0]
        self._game_number = 1
        self._game_results = []
        self._series_scores = {p: 0.0 for p in self._player_ids}
        self._turn_number = 0
        self._game_turn = 0
        self._terminal = False
        self._first_player = self._player_ids[0]
        self._init_game_state()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def get_scores(self) -> dict[str, float]:
        return dict(self._series_scores)

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining games to opponent."""
        opponent = self._opponent(forfeiting_player_id)
        remaining = self._games_per_match - len(self._game_results)
        self._series_scores[opponent] += float(remaining)
        self._terminal = True

    # ------------------------------------------------------------------
    # Series flow
    # ------------------------------------------------------------------

    def _advance_or_end(self) -> None:
        """Start next game in the series or end the match."""
        self._game_number += 1
        if self._game_number > self._games_per_match:
            self._terminal = True
            return
        self._game_turn = 0
        self._first_player = self._opponent(self._first_player)
        self._active_player = self._first_player
        self._init_game_state()

    @abstractmethod
    def _init_game_state(self) -> None:
        """Reset board and game-specific state for a new game."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _opponent(player_id: str) -> str:
        return "player_b" if player_id == "player_a" else "player_a"


# ======================================================================
# MultiplayerSeriesEvent
# ======================================================================

class MultiplayerSeriesEvent(Event):
    """Base for N-player series games with rank-based scoring.

    Provides common init (dynamic player IDs/labels), reset, scoring,
    and forfeit logic.  Subclasses implement ``_start_new_game()`` for
    game-specific initialization.
    """

    def __init__(
        self,
        games_per_match: int = 1,
        num_players: int = 4,
    ) -> None:
        self._games_per_match = games_per_match
        self._num_players = num_players

        self._player_ids = [
            f"player_{string.ascii_lowercase[i]}" for i in range(num_players)
        ]
        self._player_labels = {
            pid: string.ascii_uppercase[i]
            for i, pid in enumerate(self._player_ids)
        }
        self._action_schema = self._load_event_schema()

        # Match-level state (reset in reset())
        self._rng: random.Random | None = None
        self._game_number: int = 0
        self._terminal: bool = False
        self._match_scores: dict[str, float] = {
            p: 0.0 for p in self._player_ids
        }
        self._highlight_turns: list[int] = []

    def reset(self, seed: int) -> None:
        self._rng = random.Random(seed)
        self._game_number = 0
        self._terminal = False
        self._match_scores = {p: 0.0 for p in self._player_ids}
        self._highlight_turns = []
        self._start_new_game()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def get_scores(self) -> dict[str, float]:
        return dict(self._match_scores)

    def get_highlight_hands(self) -> list[int]:
        return list(self._highlight_turns)

    def _forfeit_points_per_game(self) -> float:
        """Points awarded to each non-forfeiting player per remaining game.

        Override if your scoring differs (e.g., LiarsDice uses N not N-1).
        """
        return float(self._num_players - 1)

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        remaining_games = self._games_per_match - self._game_number + 1
        pts = self._forfeit_points_per_game()
        for pid in self._player_ids:
            if pid != forfeiting_player_id:
                self._match_scores[pid] += pts * remaining_games
        self._terminal = True

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    def _start_new_game(self) -> None:
        """Initialize game-specific state for a new game in the series."""
