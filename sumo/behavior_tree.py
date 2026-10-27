"""
A tiny behavior tree: just enough nodes for the sumo robot.

Every node has tick(bb) -> SUCCESS, FAILURE or RUNNING. `bb` is the
blackboard: a shared object holding everything the robot currently knows.

    Selector  tries its children top to bottom and stops at the first one
              that doesn't fail ("do the first thing that applies").
    Sequence  runs its children in order and stops at the first one that
              doesn't succeed ("only if this, then that").
    Condition a yes/no question about the blackboard.
    Action    does something; returns RUNNING while it is still busy.
"""

SUCCESS = "SUCCESS"
FAILURE = "FAILURE"
RUNNING = "RUNNING"


class Node:
    def __init__(self, name):
        self.name = name

    def tick(self, bb):
        raise NotImplementedError


class Selector(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children

    def tick(self, bb):
        for child in self.children:
            status = child.tick(bb)
            if status != FAILURE:
                return status
        return FAILURE


class Sequence(Node):
    def __init__(self, name, children):
        super().__init__(name)
        self.children = children

    def tick(self, bb):
        for child in self.children:
            status = child.tick(bb)
            if status != SUCCESS:
                return status
        return SUCCESS


class Condition(Node):
    def __init__(self, name, check):
        super().__init__(name)
        self.check = check

    def tick(self, bb):
        return SUCCESS if self.check(bb) else FAILURE


class Action(Node):
    """Runs `do(bb)`, which returns a status (None counts as RUNNING).
    Records its own name in bb.active so the robot can report what it's doing."""

    def __init__(self, name, do):
        super().__init__(name)
        self.do = do

    def tick(self, bb):
        bb.active = self.name
        status = self.do(bb)
        return RUNNING if status is None else status
