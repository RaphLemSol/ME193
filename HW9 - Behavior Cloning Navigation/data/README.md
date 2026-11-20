# Walk data

Every full walk of the route is saved as one CSV **by the board**, like HW7's Step
Recorder saves each trial, and then copied into `walks/` on the laptop. The phone page
sends each row to the board as soon as it is saved. If the board doesn't answer, the rows
wait on the phone and are sent when it answers again. The page's **Download CSV** button
is only a backup. Both partners' walks go here, because the policy
is trained on both. For the step-by-step routine, see
[RECORDING_CHECKLIST.md](RECORDING_CHECKLIST.md).

(The board app isn't written yet. Until it is, the phone download is the only copy.)

The walk number on every row comes from the board: when a walk starts, the page tells the
board who is walking and which kind of walk it is, and the board answers with the next
walk number. So the board's files and the phone's backup use the same numbers.

## The 10-walk budget

The assignment allows **10 full walks in total**, both partners together, including
correction (DAgger) walks. **This table is the official walk count.** The counter on the
phone page is not: it starts over when the page reloads, and each phone counts only its
own walks. Every full walk gets a row here, even a failed one, so the count stays honest.
Short counted test walks of the step counter are not full route walks and are logged in
the process log instead.

| # | File | Walker | Date | Kind | Used for training? | Notes |
|---|---|---|---|---|---|---|
| 1 | Mohammed_demo_W01.csv | Mohammed | 2026-11-19 | demo | yes | 3 turns counted |
| 2 | Mohammed_demo_W02.csv | Mohammed | 2026-11-19 | demo | no (excluded) | 3rd left not counted, turns stayed 2 |
| 3 | Raph_demo_W03.csv | Raph | 2026-11-19 | demo | yes | 3 turns counted |
| 4 | Raph_demo_W04.csv | Raph | 2026-11-19 | demo | yes | 3 turns counted |
| 5 | Mohammed_dagger_W05.csv | Mohammed | 2026-11-19 | dagger | in part (steps < 40) | 3rd left not counted; 2 Right turns counted at step 60 |
| 6 | Mohammed_dagger_W06.csv | Mohammed | 2026-11-19 | dagger | yes |  |
| 7 | Raph_dagger_W07.csv | Raph | 2026-11-19 | dagger | in part (steps <= 36) | the two lefts after the stairs counted as one turn (slow first corner) |
| 8 | Raph_dagger_W08.csv | Raph | 2026-11-19 | dagger | yes | ends at step 56: the board lost power and rebooted |
| 9 | Mohammed_dagger_W09.csv | Mohammed | 2026-11-19 | dagger | no | aborted: started, then stopped before any correction was tapped (reason not recorded); no data saved |
| 10 | Mohammed_dagger_W10.csv | Mohammed | 2026-11-19 | dagger | no | aborted: started, then stopped before any correction was tapped (reason not recorded); no data saved |
| 11 | Mohammed_dagger_W11.csv | Mohammed (page setting) | 2026-11-19 | dagger | no | final filmed test; over the limit of 10 by one; see process_log.md |

**Kind** is `demo` (a recorded walk: the walker labels what they do) or `dagger` (a
correction walk: the policy guides, and the walker presses the right action whenever it
is wrong). On the phone page these are the **Record demo** tab and the **Navigate +
correct** tab with "Save my corrections" ticked.

## File names

One file per walk: `walks/Person_kind_Wnn.csv`, numbered across both partners in the
order walked (the number in the table above), for example `walks/Raph_demo_W01.csv`,
`walks/Mohammed_demo_W02.csv`, `walks/Mohammed_dagger_W07.csv`.

On the board the walk numbers carry on from its own files. Test and practice walks were
moved to `python/walks/tests/` on the board (2026-11-19), and the numbering started again
at W01 for the route walks; W09 and W10 (aborted, no data) are in `python/walks/excluded/`.
The table above is the official count: **11 walks total, over the limit of 10 by one: 7 used
to train the navigator (W05 and W07 in part), W02 recorded but excluded (missed turn), W11
the final filmed test, W09 and W10 aborted with no data saved.**

**`walks_excluded.txt`** lists board files that are not route walks (the three tests): they
are never pulled into `walks/` and never trained on. Add a walk there (with a comment why)
to leave it out of training without deleting anything.

**`excluded/`** keeps, as a record, route walks that were recorded but not trained on and
are never pulled into `walks/`: `Mohammed_demo_W02.csv` (3rd left not counted). The final
test W11 is in `walks/` and listed in `walks_excluded.txt`. W09 and W10 (aborted, no rows)
stay on the board only.

**`cleaned/`** holds the cleaned copies made by `training/clean_labels.py` (same columns plus
`raw_label` and `note`). They are made again from `walks/` every time; the files in
`walks/` are never changed.

The phone's backup download is different: one file, `nav_data_<date>-<time>.csv`, with
every walk since the page was opened, and walk numbers that start at 1 on each phone.
Use it only when the board's copy is missing, and split it by the `walk` column.

## Columns

These are exactly the columns the phone page (`uno_q/assets/index.html`) exports, in
this order, and the board's files will use the same ones. Each row is one moment of the
walk, a snapshot of what the sensors said and which button was pressed then.

| Column | What it means, in plain words |
|---|---|
| `walk` | Which walk this row belongs to (the walk number, the same on every row of a file). |
| `walker` | Who was walking: Mohammed or Raph. |
| `kind` | `demo` (a recorded walk) or `dagger` (a correction walk). |
| `t_ms` | The phone's clock when this row was saved, in milliseconds (1000 ms = 1 second). It is a standard computer clock (counting from 1 Jan 1970), so subtract a walk's first `t_ms` to get the time since that walk started. |
| `steps` | How many steps the walker has taken since the walk began, as a whole number (the counter's running total, rounded down). |
| `distance_m` | How far the walker has gone since the walk began, in meters (to 0.1 m), from the same step counter. Saved next to `steps` to compare the two on the first walks: a person with shorter strides takes more steps for the same corridor, but should cover the same meters. |
| `steps_since_turn` | How many steps since the last turn. The count starts over at 0 at every turn. **The policy uses this** (or the next column). |
| `distance_since_turn` | How many meters since the last turn (to 0.1 m), measured the same way: the distance now minus the distance at the moment the board counted the turn. Saved next to `steps_since_turn` so the two can be compared fairly on the first walks. |
| `turns` | How many turns so far, left and right together. |
| `turns_left` | How many of those turns were to the left. **The policy uses this.** |
| `turns_right` | How many were to the right. **The policy uses this.** |
| `heading_deg` | Which way the walker faces, in degrees, worked out by adding up the waist gyro's turning. It slowly drifts wrong over a long walk, so it is saved only for checking afterwards. **The policy does not use it.** |
| `on_stairs` | Whether the walker is on stairs right now (yes or no). **The policy uses this.** |
| `label` | The button the walker had pressed: what they were doing. One of `Straight`, `Left`, `Right`, `Stairs`, `Arrived`. This is the answer the policy learns to copy. |
| `predicted` | Only on `dagger` rows: what the policy told the walker to do, before any correction. Where it differs from `label`, the policy was wrong and the walker corrected it. Empty on `demo` rows. |

`turns` is always `turns_left` + `turns_right`, `steps_since_turn` is `steps` minus the
step count at the last turn, and `distance_since_turn` is `distance_m` minus the distance
at the last turn. They are saved anyway because they make the files easy
to read by eye.

Raw labels are never edited in these files. Label cleanup is done by a training script,
so the original recording is always kept. The script will:
- shift each turn label a few steps earlier, to undo the walker's reaction delay
- fix a `Left` or `Right` label that stays on after the turn has ended. The page now ends
  a turn label when the board counts the turn (and after 10 steps at the latest), which
  should stop this in new walks; the cleanup keeps the fix as a safety net (see
  `docs/process_log.md`)
