"""Bounded document snapshots: simple and safe for small 0.1 projects."""
class History:
    def __init__(self, limit=100):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []

    def record(self, before, after, label):
        if before.to_dict() == after.to_dict():
            return False
        self.undo_stack.append((before.clone(), after.clone(), label))
        self.undo_stack = self.undo_stack[-self.limit:]
        self.redo_stack.clear()
        return True

    def undo(self):
        if not self.undo_stack:
            return None
        step = self.undo_stack.pop()
        self.redo_stack.append(step)
        return step[0].clone()

    def redo(self):
        if not self.redo_stack:
            return None
        step = self.redo_stack.pop()
        self.undo_stack.append(step)
        return step[1].clone()
