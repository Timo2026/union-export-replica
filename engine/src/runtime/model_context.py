"""Per-process model context for upload-to-analysis continuity."""
from collections import OrderedDict
from datetime import datetime, timezone
from secrets import token_urlsafe
from threading import RLock

_MAX_MODELS = 64
_MAX_FEEDBACK = 20
_store = OrderedDict()
_lock = RLock()


def create_context(*, file_name, geometry, material, quantity, surface, tolerance, process):
    model_id = token_urlsafe(18)
    ctx = {"model_id": model_id, "created_at": datetime.now(timezone.utc).isoformat(),
           "file_name": str(file_name), "geometry": geometry, "material": str(material),
           "quantity": int(quantity), "surface": str(surface), "tolerance": str(tolerance),
           "process": str(process), "feedback": []}
    with _lock:
        _store[model_id] = ctx
        _store.move_to_end(model_id)
        while len(_store) > _MAX_MODELS:
            _store.popitem(last=False)
    return ctx


def get_context(model_id):
    with _lock:
        return _store.get(str(model_id))


def add_feedback(model_id, feedback):
    with _lock:
        ctx = _store.get(str(model_id))
        if ctx is None:
            return None
        ctx["feedback"].append(feedback)
        del ctx["feedback"][:-_MAX_FEEDBACK]
        return feedback
