"""Event — abstract base class for all tournament events.

Each event is a self-contained game engine that implements this interface.
The TournamentEngine interacts with events only through these methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a player's action against game rules."""

    legal: bool
    reason: str | None = None


class Event(ABC):
    """Abstract base for tournament events."""

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
    def is_terminal(self) -> bool:
        """Return True if the game/match is over."""

    @abstractmethod
    def get_scores(self) -> dict[str, float]:
        """Return final scores. Only meaningful when is_terminal() is True."""

    @abstractmethod
    def get_state_snapshot(self) -> dict:
        """Return a serializable snapshot of the current game state."""

    @property
    @abstractmethod
    def player_ids(self) -> list[str]:
        """Return ordered list of player IDs for this event."""

    @property
    @abstractmethod
    def action_schema(self) -> dict:
        """Return the JSON Schema for valid actions in this event."""

    def award_forfeit_wins(self, forfeiting_player_id: str) -> None:
        """Award remaining games/chips to opponent on match forfeit.

        Default implementation delegates to force_forfeit_match.
        Series-based and chip-based engines should override.
        """
        self.force_forfeit_match(forfeiting_player_id)

    @abstractmethod
    def get_highlight_hands(self) -> list[int]:
        """Return list of hand/turn numbers flagged as highlights."""
