import threading
from enum import Enum


class DictationState(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


# allowed transitions: from -> set of valid targets
_ALLOWED = {
    DictationState.IDLE: {DictationState.RECORDING},
    DictationState.RECORDING: {DictationState.PROCESSING, DictationState.IDLE},
    DictationState.PROCESSING: {DictationState.IDLE},
}


class StateMachine:
    def __init__(self):
        self.state = DictationState.IDLE
        # Transitions can be driven from several threads at once (hotkey thread,
        # the processing worker, the auto-stop timer). The lock makes each
        # check-and-set atomic so, e.g., a PTT release and an auto-stop firing
        # simultaneously can't both win the RECORDING -> PROCESSING transition.
        self._lock = threading.Lock()

    def _transition(self, target: DictationState) -> bool:
        with self._lock:
            if target in _ALLOWED[self.state]:
                self.state = target
                return True
            return False

    def to_recording(self) -> bool:
        return self._transition(DictationState.RECORDING)

    def to_processing(self) -> bool:
        return self._transition(DictationState.PROCESSING)

    def to_idle(self) -> bool:
        return self._transition(DictationState.IDLE)
