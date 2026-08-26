"""Explicit meeting state machine.

Replaces the "large collection of loosely managed booleans" the product
spec warns against with one enum and one table of legal transitions. Any
attempt to move to a state that isn't reachable from the current one raises
immediately, so bugs show up as a loud error instead of a UI stuck showing
stale/contradictory status.
"""

from __future__ import annotations

from enum import Enum


class MeetingState(str, Enum):
    IDLE = "idle"
    PREPARING = "preparing"
    RECORDING = "recording"
    PAUSED = "paused"
    RESUMED = "resumed"
    FINALIZING = "finalizing"
    GENERATING_NOTES = "generating_notes"
    COMPLETED = "completed"
    ERROR = "error"
    RECOVERY = "recovery"


_ALLOWED_TRANSITIONS: dict[MeetingState, set[MeetingState]] = {
    MeetingState.IDLE: {MeetingState.PREPARING, MeetingState.RECOVERY},
    MeetingState.PREPARING: {MeetingState.RECORDING, MeetingState.ERROR, MeetingState.IDLE},
    MeetingState.RECORDING: {
        MeetingState.PAUSED,
        MeetingState.FINALIZING,
        MeetingState.ERROR,
    },
    MeetingState.PAUSED: {MeetingState.RESUMED, MeetingState.FINALIZING, MeetingState.ERROR},
    MeetingState.RESUMED: {MeetingState.RECORDING, MeetingState.PAUSED, MeetingState.ERROR},
    MeetingState.FINALIZING: {MeetingState.GENERATING_NOTES, MeetingState.COMPLETED, MeetingState.ERROR},
    MeetingState.GENERATING_NOTES: {MeetingState.COMPLETED, MeetingState.ERROR},
    MeetingState.COMPLETED: set(),
    MeetingState.ERROR: {MeetingState.RECOVERY, MeetingState.IDLE},
    MeetingState.RECOVERY: {MeetingState.RECORDING, MeetingState.FINALIZING, MeetingState.IDLE, MeetingState.ERROR},
}


class IllegalStateTransition(RuntimeError):
    def __init__(self, current: MeetingState, target: MeetingState):
        super().__init__(f"Cannot transition from {current.value} to {target.value}")
        self.current = current
        self.target = target


class MeetingStateMachine:
    def __init__(self, initial: MeetingState = MeetingState.IDLE):
        self._state = initial
        self._history: list[MeetingState] = [initial]

    @property
    def state(self) -> MeetingState:
        return self._state

    def can_transition(self, target: MeetingState) -> bool:
        return target in _ALLOWED_TRANSITIONS.get(self._state, set())

    def transition(self, target: MeetingState) -> None:
        if not self.can_transition(target):
            raise IllegalStateTransition(self._state, target)
        self._state = target
        self._history.append(target)

    @property
    def history(self) -> list[MeetingState]:
        return list(self._history)
