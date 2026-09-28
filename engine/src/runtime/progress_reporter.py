# -*- coding: utf-8 -*-
class ProgressReporter:
    def __init__(self, bus):
        self.bus = bus
    def report(self, pct, msg):
        self.bus.publish("progress", {"progress": pct, "message": msg})
