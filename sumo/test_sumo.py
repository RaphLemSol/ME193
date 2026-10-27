"""
Check the behavior tree's priorities without any hardware or network:
    python test_sumo.py
"""

import unittest

import config
from sumo import Blackboard, build_tree


class FakeRobot:
    def __init__(self):
        self.cmd = None
        self.songs = 0

    def drive(self, left, right):
        self.cmd = (left, right)

    def stop(self):
        self.drive(0, 0)

    def sad_song(self):
        self.songs += 1


class TestTree(unittest.TestCase):
    def setUp(self):
        self.robot = FakeRobot()
        self.tree = build_tree(self.robot)
        self.bb = Blackboard()
        self.bb.now = 100.0

    def tick(self, now=None):
        if now is not None:
            self.bb.now = now
        self.tree.tick(self.bb)
        return self.bb.active

    def see_opponent(self, cm):
        self.bb.distance_cm = cm
        self.bb.distance_time = self.bb.now

    def test_search_when_nothing_happening(self):
        self.assertTrue(self.tick().startswith("SEARCH"))
        self.assertEqual(self.robot.cmd, (config.SEARCH_SPEED, -config.SEARCH_SPEED))

    def test_charge_when_opponent_close(self):
        self.see_opponent(20)
        self.assertEqual(self.tick(), "CHARGE")
        self.assertEqual(self.robot.cmd, (config.CHARGE_SPEED, config.CHARGE_SPEED))

    def test_no_charge_when_opponent_far_or_no_echo(self):
        self.see_opponent(80)
        self.assertTrue(self.tick().startswith("SEARCH"))
        self.see_opponent(-1)
        self.assertTrue(self.tick().startswith("SEARCH"))

    def test_stale_distance_ignored(self):
        self.see_opponent(20)
        self.assertTrue(self.tick(now=self.bb.now + config.DISTANCE_STALE_S + 0.1).startswith("SEARCH"))

    def test_operator_charge_lasts_hold_time(self):
        self.bb.charge_until = self.bb.now + config.CHARGE_HOLD_S
        self.assertEqual(self.tick(), "CHARGE")
        self.assertTrue(self.tick(now=self.bb.now + config.CHARGE_HOLD_S + 0.1).startswith("SEARCH"))

    def test_tape_beats_charge(self):
        self.see_opponent(10)
        self.bb.charge_until = self.bb.now + 5
        self.bb.on_tape = True
        self.assertTrue(self.tick().startswith("EDGE"))
        self.assertEqual(self.robot.cmd, (-config.BACKUP_SPEED, -config.BACKUP_SPEED))

    def test_escape_finishes_after_leaving_tape(self):
        self.bb.on_tape = True
        self.tick()
        t0 = self.bb.now
        self.bb.on_tape = False
        # Still backing up just after leaving the tape...
        self.assertTrue(self.tick(now=t0 + 0.1).startswith("EDGE"))
        self.assertEqual(self.robot.cmd, (-config.BACKUP_SPEED, -config.BACKUP_SPEED))
        # ...then turning...
        self.assertTrue(self.tick(now=t0 + config.BACKUP_S + 0.1).startswith("EDGE"))
        left, right = self.robot.cmd
        self.assertEqual(abs(left), config.TURN_SPEED)
        self.assertEqual(left, -right)
        # ...then back to searching.
        self.assertTrue(self.tick(now=t0 + config.BACKUP_S + config.TURN_S + 0.1).startswith("SEARCH"))

    def test_out_beats_everything_and_song_plays_once(self):
        self.bb.on_tape = True
        self.see_opponent(10)
        self.bb.out = True
        for _ in range(5):
            self.assertTrue(self.tick().startswith("OUT"))
        self.assertEqual(self.robot.cmd, (0, 0))
        self.assertEqual(self.robot.songs, 1)

    def test_reset_after_out(self):
        self.bb.out = True
        self.tick()
        self.bb.out = False
        self.bb.song_played = False
        self.assertTrue(self.tick().startswith("SEARCH"))


if __name__ == "__main__":
    unittest.main()
