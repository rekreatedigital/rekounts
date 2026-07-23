from rekounts.state_machine import StateMachine, DictationState


def test_starts_idle():
    sm = StateMachine()
    assert sm.state == DictationState.IDLE


def test_valid_cycle():
    sm = StateMachine()
    assert sm.to_recording() is True
    assert sm.state == DictationState.RECORDING
    assert sm.to_processing() is True
    assert sm.state == DictationState.PROCESSING
    assert sm.to_idle() is True
    assert sm.state == DictationState.IDLE


def test_cannot_record_while_recording():
    sm = StateMachine()
    sm.to_recording()
    assert sm.to_recording() is False   # rejected
    assert sm.state == DictationState.RECORDING


def test_cannot_process_from_idle():
    sm = StateMachine()
    assert sm.to_processing() is False
    assert sm.state == DictationState.IDLE


def test_can_return_to_idle_from_processing():
    sm = StateMachine()
    sm.to_recording()
    sm.to_processing()
    assert sm.to_idle() is True
    assert sm.state == DictationState.IDLE
