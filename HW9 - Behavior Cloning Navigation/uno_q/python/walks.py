"""Saving the walks on the board: GET /api/reset and POST /api/rows (build steps 6 and 7).

The phone page labels the walk; the board keeps the real copy of every walk, one CSV per
walk in walks/ (next to this file): walks/Person_kind_Wnn.csv, e.g. Raph_demo_W03.csv,
with exactly the page's columns (COLUMNS, see data/README.md). The protocol is in
uno_q/README.md ("How the phone and the board talk").

- start_walk(walker, kind): a new walk. Its number is one more than the highest walk number
  among the files already saved (so numbers carry on across restarts and never repeat).
- add_items(items): the page's waiting line, in order. Each item has a ticket (session, seq)
  and either "row" (the CSV columns) or "undo" (the seq of an earlier row from the same
  session). The board remembers the highest seq handled per session and skips anything not
  higher, so a batch sent twice (its "ok" lost) is saved once. A row goes into its own
  walk's file (row["walk"]); an undo removes the row with that seq. Every walk touched is
  rewritten whole (a walk is only ~1000 rows) to a temporary file that then replaces the
  old one, so a power cut can't leave half a file. Only then does the page get "ok".
- A walk whose file exists but isn't in memory (the app restarted) is read back first, so
  its earlier rows are kept. Those rows have no tickets any more, so they can't be undone.
  The highest seq per session is also forgotten on a restart; a batch resent right after a
  restart could be saved twice (a known gap, see uno_q/README.md).
"""
import csv
import os
import re

COLUMNS = ["walk", "walker", "kind", "t_ms", "steps", "distance_m", "steps_since_turn",
           "distance_since_turn", "turns", "turns_left", "turns_right", "heading_deg",
           "on_stairs", "label", "predicted"]
KINDS = ("demo", "dagger")
NAME_RE = re.compile(r"^(?P<walker>[A-Za-z0-9]+)_(?P<kind>demo|dagger)_W(?P<walk>\d+)\.csv$")


def safe_name(walker):
    """Letters and digits only (the name goes into a file name)."""
    return re.sub(r"[^A-Za-z0-9]", "", str(walker))


class WalkStore:
    def __init__(self, folder, logger):
        self.folder = folder
        self.logger = logger
        os.makedirs(folder, exist_ok=True)
        self.walks = {}            # walk number -> {"walker", "kind", "rows": [(seq or None, row dict)]}
        self.last_seq = {}         # page session -> highest seq handled

    # --- files ---------------------------------------------------------------------------

    def saved_numbers(self):
        """Walk number -> file name, for every walk file in the folder."""
        out = {}
        for name in os.listdir(self.folder):
            m = NAME_RE.match(name)
            if m:
                out[int(m["walk"])] = name
        return out

    def route_walk_count(self):
        """How many route walks are saved: the walk files directly in walks/ (demo and dagger,
        including the one running now; its file is written at Start). Test walks moved to
        walks/tests/ are not counted. The page shows this as "Walks used" (2026-11-19: it used
        to show the walk number, which counted test files and differed per browser)."""
        return len(self.saved_numbers())

    def path(self, number):
        w = self.walks[number]
        return os.path.join(self.folder, f"{w['walker']}_{w['kind']}_W{number:02d}.csv")

    def load(self, number, walker, kind):
        """Make sure walk `number` is in memory, reading its file back if it has one."""
        if number in self.walks:
            return
        self.walks[number] = {"walker": walker, "kind": kind, "rows": []}
        name = self.saved_numbers().get(number)
        if name:
            m = NAME_RE.match(name)
            self.walks[number].update(walker=m["walker"], kind=m["kind"])
            with open(os.path.join(self.folder, name), newline="") as f:
                self.walks[number]["rows"] = [(None, row) for row in csv.DictReader(f)]
            self.logger.info(f"Read back {name}: {len(self.walks[number]['rows'])} rows")

    def write(self, number):
        """Rewrite walk `number`'s whole CSV: temporary file first, then swap it in."""
        path = self.path(number)
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLUMNS)
            for _, row in self.walks[number]["rows"]:
                w.writerow([row.get(c, "") for c in COLUMNS])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    # --- the API ---------------------------------------------------------------------------

    def start_walk(self, walker, kind):
        """GET /api/reset: a new walk. Returns its number, or raises ValueError (the page shows it)."""
        walker = safe_name(walker)
        if not walker:
            raise ValueError("no walker name")
        if kind not in KINDS:
            raise ValueError(f"kind must be demo or dagger, not {kind!r}")
        number = max([0, *self.saved_numbers(), *self.walks]) + 1
        self.walks[number] = {"walker": walker, "kind": kind, "rows": []}
        self.write(number)                 # an empty file (header only) reserves the number
        self.logger.info(f"Walk {number} started: {os.path.basename(self.path(number))}")
        return number

    def add_items(self, items):
        """POST /api/rows: handle the page's items in order. Returns how many rows were added
        and removed, and how many items were skipped (already handled)."""
        touched, added, removed, skipped = set(), 0, 0, 0
        for item in items:
            session, seq = str(item["session"]), int(item["seq"])
            if seq <= self.last_seq.get(session, 0):
                skipped += 1               # already handled (a batch sent again)
                continue
            if "row" in item:
                row = {c: item["row"].get(c, "") for c in COLUMNS}
                number = int(row["walk"])
                self.load(number, safe_name(row["walker"]), row["kind"])
                self.walks[number]["rows"].append(((session, seq), row))
                touched.add(number)
                added += 1
            elif "undo" in item:
                target = (session, int(item["undo"]))
                for number, w in self.walks.items():
                    before = len(w["rows"])
                    w["rows"] = [(t, r) for t, r in w["rows"] if t != target]
                    if len(w["rows"]) != before:
                        touched.add(number)
                        removed += before - len(w["rows"])
            self.last_seq[session] = seq
        for number in touched:
            self.write(number)
        return {"added": added, "removed": removed, "skipped": skipped}
