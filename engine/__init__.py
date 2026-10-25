"""Position engine: the only package that touches the game. Everything else uses
the Engine interface, backed by MemoryEngine in game or SimulatorEngine without it."""

from engine.base import Engine
from engine.models import AOB_NOT_FOUND, ATTACHED, ERROR, STATUSES, WAITING_FOR_GAME, EngineState


def create_engine(simulate=False, **kwargs):
    if simulate:
        from engine.simulator import SimulatorEngine
        return SimulatorEngine(**kwargs)
    from engine.memory import MemoryEngine
    return MemoryEngine(**kwargs)


__all__ = ["Engine", "EngineState", "create_engine", "STATUSES",
           "WAITING_FOR_GAME", "ATTACHED", "AOB_NOT_FOUND", "ERROR"]
