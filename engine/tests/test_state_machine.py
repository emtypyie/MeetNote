import pytest

from state.machine import IllegalStateTransition, MeetingState, MeetingStateMachine


def test_happy_path_transitions():
    m = MeetingStateMachine()
    assert m.state == MeetingState.IDLE
    m.transition(MeetingState.PREPARING)
    m.transition(MeetingState.RECORDING)
    m.transition(MeetingState.PAUSED)
    m.transition(MeetingState.RESUMED)
    m.transition(MeetingState.RECORDING)
    m.transition(MeetingState.FINALIZING)
    m.transition(MeetingState.GENERATING_NOTES)
    m.transition(MeetingState.COMPLETED)
    assert m.state == MeetingState.COMPLETED


def test_illegal_transition_raises():
    m = MeetingStateMachine()
    with pytest.raises(IllegalStateTransition):
        m.transition(MeetingState.COMPLETED)


def test_completed_is_terminal():
    m = MeetingStateMachine(MeetingState.COMPLETED)
    assert not m.can_transition(MeetingState.RECORDING)
    with pytest.raises(IllegalStateTransition):
        m.transition(MeetingState.RECORDING)


def test_error_can_recover_via_recovery_state():
    m = MeetingStateMachine(MeetingState.RECORDING)
    m.transition(MeetingState.ERROR)
    m.transition(MeetingState.RECOVERY)
    m.transition(MeetingState.RECORDING)
    assert m.state == MeetingState.RECORDING


def test_history_is_recorded():
    m = MeetingStateMachine()
    m.transition(MeetingState.PREPARING)
    m.transition(MeetingState.RECORDING)
    assert m.history == [MeetingState.IDLE, MeetingState.PREPARING, MeetingState.RECORDING]
