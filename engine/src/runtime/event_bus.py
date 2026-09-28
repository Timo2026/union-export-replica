# -*- coding: utf-8 -*-
class EventBus:
    def __init__(self):
        self._subs = {}
    def subscribe(self, event, fn):
        self._subs.setdefault(event, []).append(fn)
    def publish(self, event, data=None):
        for fn in self._subs.get(event, []):
            try:
                fn(data)
            except Exception:
                pass
