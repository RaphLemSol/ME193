# HW9 process log

A running record of what was tried, what failed and what we figured out.

## 2026-11-17: Setup and first decisions

**Decided**
- Folder layout: `uno_q/` (board app), `training/`, `data/`, `docs/`, `media/`. The phone
  page lives in `uno_q/assets/` instead of a separate `ui/` folder, because the board
  serves its page from there. A second copy elsewhere would drift out of sync.
- Step counter: starting with Mohammed's HW7 counter, because it already runs on the
  board in plain numpy (no PyTorch, no laptop, no internet). To be confirmed with Raph.
  Raph's 1-D CNN counter is the alternative being compared. It currently runs on a
  laptop in PyTorch, so it would need its weights moved to numpy to run on the board.
- Policy: start with a lookup table (like the AnnaCode Table Cloner); try a small
  neural net only if needed.
- Phone link: the phone's hotspot, not the board as its own network, so the laptop can
  still reach the board to deploy.

**Checked**
- HW7's sensor was worn on the right lower leg, near the ankle, with the whole board
  strapped there. Its counter was trained only on Mohammed, only on straight 20 m walks
  (3.0% off live after the sensor-angle fix).
- Raph's counter misses about 1 step per turn. Here the count of steps since the last
  turn starts over at each turn, so a step missed right at a turn should matter less.

**Open**
- Start point and route; inside a building or across campus.
- Whether the waist sensor's long I2C wire reads reliably on a walk.
- Whether the HW7 counter holds up on Raph's walking and on turns (first checklist item).

## 2026-11-17: CSV columns and a known page bug

**Decided**
- The walk CSVs use exactly the columns the phone page exports: `walk, walker, kind,
  t_ms, steps, steps_since_turn, turns, turns_left, turns_right, heading_deg, on_stairs,
  label, predicted`. `data/README.md` explains each one.
- `kind` is `demo` or `dagger`. `predicted` is filled only on `dagger` rows.
- `heading_deg` is saved for checking only. It drifts, so the policy won't use it.

**Known bug (left in the page on purpose for now)**
- A `Left` or `Right` label can stay on for one step after the turn has ended.
- **To do: the label-cleanup script handles it.** Plan: once `turns` has gone up for
  that turn (the board has counted it), a `Left` or `Right` row whose `steps_since_turn`
  is already 1 or more becomes `Straight`. Rows *before* the turn is counted are the real
  turn label and are left alone (they also have `steps_since_turn` of 1 or more, so the
  `turns` check is what tells the two apart). Raw files stay unchanged; only the training
  copy is fixed.

## 2026-11-17: Reading the phone page, and the first page fixes

**How the page was checked:** read in full, then its script was run against a fake board
(macOS's built-in JavaScript engine, fake page elements, a board that can refuse, go
silent or answer late). All 20 checks passed after the fixes below. Not yet tried on a
real phone or the real board.

**Findings**
1. **Counts carried over between walks** (the serious one). Start walk set the page's
   numbers to 0, but a quarter-second later the board's running totals overwrote them, so
   walk 2 would start with walk 1's steps and turns. **It wasn't caught because Mock mode
   never asks the board for numbers**: in Mock, the page's own 0 is the only count, so the
   reset looked like it worked. Lesson: test Live, even against a fake board.
2. Data lived only in the phone's memory: a reload lost the walk, and a locked iPhone
   stops the page asking the board, so steps taken while locked get no rows.
3. The "can't reach the board" message only showed on the Record tab, never cleared, and
   the instruction kept showing as if nothing were wrong.
4. The page's walk counter starts over on every reload and on each phone.
5. The download is one file with every walk since the page opened.
6. Undo removes only the tap row; the step rows saved with the wrong label stay.
7. Left/Right switched back to Straight after a fixed 1.5 s, not when the turn ended:
   the likely cause of the turn label staying on for a step after the turn.
8. The HW7 counter's total has decimals (29.6), so the page would have saved a row at
   every update and "steps since the turn" would have had decimals.
9. Small: the title said "Campus Navigator" (app.yaml: "Nolop Navigator"), and a comment
   said the counter updates every 0.25 s (HW7's updates every 0.5 s).
10. Steps differ between walkers with different stride lengths, so steps since a turn
    from both partners' walks blur where the turn is.

**Decided**
- The table in `data/README.md` is the official walk count (finding 4).
- The board saves one CSV per walk, like HW7's recorder; the phone download is a backup
  (findings 2 and 5).
- Recording checklist: "if you mis-tap, tap Straight right away" (finding 6), Live mode
  and Auto-Lock Never (findings 1 and 2).
- `distance_m` added to `/api/state` and the CSV, next to `steps`; steps vs meters is
  compared on the first walks (finding 10).

**Page fixes** (`uno_q/assets/index.html`)
1. Start walk and Start navigating call `GET /api/reset` and only start once the board
   answers `{"ok": true}`. An answer to a request sent before the reset is thrown away.
   If the board refuses or doesn't answer, the walk doesn't start and the page says why.
2. The warning sits above both tabs (and stays at the top when scrolling), appears after
   1.5 s without an answer, clears as soon as the board answers, and greys out the
   instruction meanwhile. Each request now gives up after 1.5 s, because a dropped
   hotspot can make a request hang instead of failing.
3. Left/Right go back to Straight when the board's turn count goes up. Safety net: after
   10 steps with no turn counted, back to Straight anyway (otherwise a missed turn would
   label the rest of the walk Left). The cleanup rule from earlier stays as a backup.
4. Steps rounded down to whole steps; comment fixed; title "Nolop Navigator".

**Still open**
- **The page doesn't send rows to the board yet**, so the board can't save walks until it
  does (for example sending each row to the board as it is saved).
- A tap made *after* the board already counted the turn (a late tap) stays on until the
  10-step safety net. The cleanup's shift-earlier step has to handle late taps.
- Meters since the last turn: the board could send `distance_at_last_turn`, as it does
  `steps_at_last_turn`, so it doesn't have to be worked out from the rows afterwards.

**What the board app must provide**
1. The page itself: `assets/index.html` on port 7000 (`web_ui` brick).
2. `GET /api/state` → `{"steps", "distance_m", "turns_left", "turns_right",
   "steps_at_last_turn", "heading_deg", "on_stairs"}`. Decimals are fine for `steps` and
   `steps_at_last_turn` (the page rounds down). `steps_since_turn` and `turns` are worked
   out by the page and needn't be sent.
3. `GET /api/reset` → set every count to 0 (steps, distance, turns, steps at last turn,
   heading), then answer `{"ok": true}`, or `{"ok": false, "error": "..."}` if it can't.
4. Answer within 1.5 s, or the page treats the request as failed.
5. Save one CSV per walk with the columns in `data/README.md` (needs the page to send
   its rows, see Still open).
6. Later: run the trained policy, for example `GET /api/predict`, or hand the page the
   policy table.

## 2026-11-17: Rows sent to the board, and meters since the last turn

Checkpoint commit `e188a6c` before this work.

**Sending rows to the board** (`uno_q/assets/index.html`)
- Every saved row goes into an *outbox* on the phone, a waiting line, oldest first. Each
  tick sends the oldest waiting rows (up to 50) in one `POST /api/rows`. Only when the
  board answers `{"ok": true}` do they leave the line. If not, they stay and are tried
  again on the next tick. One send at a time, so the order is kept.
- Every message has a *ticket* (the page's session id + a number). If the board saved a
  batch but its "ok" got lost, the page sends it again and the board skips what it has.
- The outbox is also kept in the phone's storage, so rows waiting to be sent survive a
  page reload.
- Undo: a row still waiting is just dropped; a row the board may already have gets an
  "undo" message in the line, and the board removes it.
- The reset now says who is walking and the kind of walk
  (`/api/reset?walker=Raph&kind=demo`), and the board answers with its walk number,
  which goes on every row. So each row lands in the right walk's file, and the board's
  files and the phone's backup use the same numbers.
- The row count shows "all sent to the board" or "N waiting to send"; ending a walk with
  rows still waiting says to keep the page open.

**Meters since the last turn**
- `/api/state` gets `distance_at_last_turn` next to `steps_at_last_turn`. The CSV gets
  `distance_since_turn` next to `steps_since_turn` (the CSV has no `steps_at_last_turn`
  column, so the matching pair is the "since the turn" one). Both are worked out the same
  way, from the board's count at the moment it counted the turn, so steps vs meters is
  a fair comparison.

**Checked:** 33 checks against the fake board, all passing. They cover the board going
completely silent mid-walk (taps saved meanwhile wait on the phone, then arrive in order,
and the board's copy matches the phone's exactly), only the rows request failing, a lost
"ok" (no duplicates), undo before and after sending, rows waiting through a reload, two
walks going to two files, and mock mode sending nothing. Not checked: undo while that
row's batch is on its way (the code sends an undo in that case, but the test can't time
it), and anything on a real phone or board.

**Problems found while doing it**
- The backup download built its columns from the first row's fields, so the new private
  ticket would have become a junk column. It now writes exactly the CSV columns
  (checked).
- The first test run failed 11 checks: each tick sent waiting rows *before* saving that
  tick's new row, so the newest row always waited an extra quarter-second. The send now
  happens at the end of the tick.

**TURN_GIVE_UP_STEPS = 10 is a guess.** It is how many steps after a Left/Right tap the
page waits for the board to count the turn before going back to Straight. Check it on the
first real walks: how many steps after the tap does the board really count each turn
(rows where `turns` goes up)? It should be a few steps more than the slowest real turn,
but small enough that a missed turn doesn't label a long stretch as Left.

**What the board app must provide (replaces the earlier list)**
1. The page itself: `assets/index.html` on port 7000 (`web_ui` brick).
2. `GET /api/state` → `{"steps", "distance_m", "turns_left", "turns_right",
   "steps_at_last_turn", "distance_at_last_turn", "heading_deg", "on_stairs"}`. Decimals
   are fine; the page rounds.
3. `GET /api/reset?walker=<name>&kind=<demo|dagger>` → set every count to 0 (steps,
   distance, turns, both "at last turn" values, heading), start the next walk number,
   answer `{"ok": true, "walk": <number>}`, or `{"ok": false, "error": "..."}`.
4. `POST /api/rows` with `{"items": [...]}`, in order. Each item has `session` and `seq`,
   and either `row` (the CSV columns: append it to walk `row.walk`'s CSV) or `undo` (the
   `seq` of an earlier row from the same session: remove that row). Skip any item whose
   `seq` is not higher than the last one handled for that session. Answer `{"ok": true}`
   only once everything is saved to disk.
5. Answer every request within 1.5 s, or the page treats it as failed.
6. Later: run the trained policy, for example `GET /api/predict`, or hand the page the
   policy table.

## 2026-11-17: End of day 1 summary

**Decided**
- Layout as in the README; the phone page lives in `uno_q/assets/`.
- Start with Mohammed's HW7 step counter (runs on the board in plain numpy); Raph's CNN
  counter is the alternative being compared. Testing it on Raph's walking is the first
  checklist item. To confirm with Raph.
- Policy: a lookup table first (AnnaCode Table Cloner), a small net only if needed.
- The walk table in `data/README.md` is the official walk count (10 at most).
- The board saves one CSV per walk; the phone's download is the backup.
- Steps and meters are both saved (also since the last turn), to compare on the first
  walks.
- Phone hotspot rather than the board as its own Wi-Fi network.

**Built**
- Phone page fixes: reset the board before each walk (and only start once it confirms),
  a "can't reach the board" warning on both tabs with the instruction greyed out, turn
  labels that end when the board counts the turn (10-step safety net, a guess to check),
  whole steps, matching title.
- Row sending: a waiting line on the phone, tickets against duplicates, undo messages,
  walk numbers from the board, rows kept through a page reload. 33 checks against a fake
  board pass; not yet tried on a real phone or board.
- `uno_q/README.md`: the page ↔ board protocol in plain words, one example walk, and the
  build order (Step 0, then steps 1-9).
- Checklist: Live mode, Auto-Lock Never, tap Straight after a mis-tap, keep the page open
  until all sent, don't restart the hotspot mid-walk.

**Next (2026-11-18, with Raph)**
- Step 0, the hardware risk test: a sketch that records both sensors raw, one short walk
  with turns each, then check for dropouts and whether turns stand out in the waist gyro.
  If either fails, rethink before building the board app.
- Then the board app, in the build order in `uno_q/README.md`.
- The step-counter test on Raph's walking (checklist part 1) can be done with HW7's Step
  Recorder as it is.

## 2026-11-17: Turns from the ankle sensor (test on Raph's recording, no hardware)

**Test.** Mohammed ran `training/ankle_turn_check.py` on Raph's existing ankle recording
(`How many steps/data/walk_20261103_030045.csv` in Raph's repo: 61 counted steps, back and
forth over 2 m, 9 turnarounds, 100 Hz, about 6,000 rows). Method: "up" from the
accelerometer averaged over 1 s; the gyro's turning rate around "up", added up over time
into a heading; the gyro bias measured in the first 5 s, standing still, and subtracted.
Plot: [`media/ankle_turns_raph.png`](../media/ankle_turns_raph.png).

**What it showed**
- Turns stand out clearly at the ankle: 9 climbs, one per turnaround, and a flat heading
  while walking straight.
- No dropouts (no gap over 25 ms in about 6,000 rows). Short wire, so this says nothing
  about a long one.
- Each turnaround reads about 157° instead of 180° (all 9 together: 1409° instead of
  1620°), about 13% low. In any 2 s window each turnaround climbed 118-169°.
- Bias about 7.5°/s. Left in, the heading drifts about 450° in a minute, so the board must
  measure it while standing still at the start of every walk.
- Rerun and checked by Claude: the same numbers. Added check: on 9 of Mohammed's straight
  20 m HW7 walks (Test T21-T29, slow to fast, no turns), the ankle heading never changed
  by more than 14-20° within any 2 s (bias there taken as the walk's average, since a
  straight walk adds up to no turn). So ">60° within 2 s" sits between the walking wobble
  and the turnarounds with room on both sides.

**What it didn't prove**
- One walk by one person; only 180° turnarounds, all in the same direction; no 90° corners
  while walking; no left vs right; straight stretches of only 2 m.
- Why turns read 13% low isn't known: the averaged "up" lags behind the leg's tilt, or
  the walker didn't turn a full 180°. A loop that comes back to the start (known total:
  360°) separates the two.

**Decided**
- Step 0 becomes a one-sensor test: board and sensor on the ankle as in HW7 (short wire),
  loops with 90° left and right corners, the same heading plot. If it passes, the waist
  sensor and the long wire are dropped. The two-sensor test stays as the backup.
- Turn counting (build step 9) uses the ankle sensor and measures the bias while the
  walker stands still for 5 s right after Start. The waist sensor (step 8) only if Step 0
  fails.
- Checklist: stand still 5 s after pressing Start.
- `ankle_turn_check.py` now also reads HW7 recordings (`time` column), so Step 0 needs no
  new code: HW7's Step Recorder records the walk. Comments added; the calculations are
  unchanged (same output on Raph's walk).

**Added after the test: corner length.** A 90° corner taken while walking may take longer
than 2 s, so part of it would fall outside the 2 s window and it could read under 60°.
When checking the Step 0 loop plots, measure how long each corner's climb lasts. If
corners take longer than 2 s, **widen the turn window to 3 s instead of lowering the 60°
threshold**: a lower threshold moves toward the walking wobble, while a wider window
keeps clear of it (on HW7's straight walks the wobble stayed under 27° within 3 s,
against under 20° within 2 s).

## 2026-11-18: Step 0 on Raph's board (ankle sensor only)

Run from the terminal with HW7's Step Recorder app (`arduino-app-cli`, no App Lab) on
Raph's UNO Q; Raph's own app paused meanwhile, with his OK. Board and sensor on Raph's
right ankle as in HW7. Recordings in `data/step0/`, plots in `media/step0_*.png`.

**Tilt test:** the accelerometer reads ±1 g on each axis pointing up or down (others
within 0.16 g of 0). The gyro has a large steady offset: **gx about +34°/s when still**
(gy about 0, gz about -3), the same in all 7 still stretches. Raph's November recording
starts with gx = 35°/s, so probably the same sensor.

**LoopLeft** (Raph, 4 left corners, `Raph_Test_T01`) and **LoopRight** (Raph, 4 right
corners, `Raph_Test_T02`):

| | LoopLeft | LoopRight |
|---|---|---|
| Total heading change (per-axis bias) | +309° | -318° |
| Corners | +68, +78, +73, +80° | -89, -84, -79, -87° |
| How long each climb took | 1.0, 0.9, 1.6, 1.6 s | 1.6, 1.5, 1.4, 1.7 s |
| Biggest change within 2 s at a corner | 74-92° | 92-117° |
| Biggest change within 2 s walking straight | 17° | 23° |
| Rows of zeros / -1s, gaps over 25 ms | none | none |
| Steps: counted / live count | 28 / 26.4 ± 2.9 | 27 / 26.8 ± 3.8 |

So every corner clears 60° within 2 s, every climb is under 2 s (the window stays 2 s,
no need for 3 s), and the straights stay well under 60°. The HW7 step counter stayed
within its ± on this sensor despite the gx offset (two trials only).

**Finding: remove the gyro bias per axis, not as one number.** The script first measured
the bias as one number, the turning rate around "up" while standing still. But how much
of the gx offset shows up around "up" depends on how the shin is tilted, which differs
between standing and walking and changes every stride, so the subtracted number was a
little wrong the whole walk. Totals with one number: LoopLeft +350°, LoopRight -276°
(74° apart; LoopLeft's near-360° was luck). With the bias of gx, gy and gz each
subtracted before taking the part around "up": +309° and -318°, both about 12% short,
like Raph's November turnarounds (13%). `ankle_turn_check.py` now does this, and build
step 9 says so. (Raph's November walk barely changes: 1405° vs 1400°.) The steady ~12%
shortfall is not corrected: turns are only compared with 60°.

**Paired corners in LoopLeft.** Corners 1-2 and 3-4 came only 1-1.5 s apart. A simple
corner finder merged each pair into one ~170° turn. For the turn rule: a 3 s window would
also merge them, so widening it has a cost; and the pause before the next turn can count
must be shorter than about 1 s.

**Jump at the start of walking.** The heading rises +10° (LoopLeft) and +22° (LoopRight)
in the first steps after standing, positive both times whatever the turn direction:
probably the leg's angle changing from standing to walking. Under 60°, so it doesn't
count as a turn, but it adds to the totals.

**Possible left/right difference (needs more data).** Left corners read about 75° on
average, right corners about 85°. With the sensor on the right ankle it could be real
(a left turn swings the right foot around, a right turn pivots on it), but it is one
loop each, by one walker.

**Plots:** `ankle_turn_check.py`'s bias-removed plot now fits its scale to the data, with
a gray line every 90°, so corners are visible (before, the 180° lines forced it up to
1,800°). `media/ankle_turns_raph.png` is still the old plot.

**SpotTurns** (Raph, `Raph_Test_T03`: a left turn of about 180° on the spot, a ~3 s pause,
a right turn of about 180°; steps not counted, live count 2.8 ± 3.5 from the pivots):
- Turn 1 **+182°** (climb 2.3 s, 146° within 2 s), turn 2 **-181°** (climb 2.1 s, 179°
  within 2 s), total +1°. No rows of zeros or -1s, no gaps over 25 ms. Heading flat
  before, between and after.
- **Turns on the spot read the full angle; walking corners read about 12% short.** So
  the gyro's scale is fine and the shortfall comes from walking (likely the 1 s average
  of "up" while the shin swings). Not corrected, since turns are only compared with 60°.
- Spot turns took just over 2 s but still cleared 60° within 2 s easily, so the window
  stays 2 s. **Open for the turn rule:** with a pause under 1 s, a slow 180° turn could
  be counted twice; decide how a U-turn counts.
- The gx offset was 34.9°/s here (34.1 and 34.25 in the loops): it shifts a little
  between trials, so measuring it at the start of every walk is right.

**Mohammed's three trials** (`Mohammed_Test_T02`-`T04`; files renamed so both walkers fit:
`data/step0/Raph_*.csv` and `Mohammed_*.csv`, plots `media/step0_raph_*.png` and
`media/step0_mohammed_*.png`):

| | LoopLeft | LoopRight | SpotTurns |
|---|---|---|---|
| Total heading change | +280° | -356° | -10° (right -174°, left +164°) |
| Corners | +71, +73, +64, +83° | -89, -88, -95, -82° | -174°, +164° |
| How long each climb took | 1.6, 1.4, 1.3, 0.9 s | 1.4, 1.0, 1.0, 0.9 s | 2.2, 2.4 s |
| Biggest change within 2 s at a corner | 71-92° | 76-87° | 149°, 151° |
| Biggest change within 2 s walking straight | 18° | 14° | — |
| Rows of zeros / -1s, gaps over 25 ms | none | none | none |
| Steps: counted / live count | 28 / **18.5 ± 3.7** | 28 / **21.7 ± 3.7** | 0 / 4.6 ± 4.0 |

**Left vs right, both walkers:** left corners read lower for both: Mohammed 73° vs 88°
on average, Raph 75° vs 85°. For Mohammed at least part of it is a slow drift while
walking straight: his heading drifts *rightward* by about 3-5°/s on straight stretches
(LoopLeft: -22°, -22°; LoopRight: -4 to -17°), which pulls each left corner down and
pushes each right corner up by a few degrees, and takes 44° off his LoopLeft total.
Raph's straights drift the other way and less (0 to +2°/s). It can't be told apart from
a slightly curved path yet. Either way it is too slow to look like a turn (under 12°
within 2 s).

**Step 0 passes for both walkers.** No dropouts on any trial; every corner and spot turn
is a clear step in the right direction; every one changes more than 60° within 2 s (the
lowest: 71°, Mohammed's LoopLeft corner 2) and every climb is under 2 s except the slow
180° spot turns (2.1-2.4 s, which still clear 60° easily); straight walking stays under
23° within 2 s. **Decision: the waist sensor and the long wire are dropped; turns come
from the ankle sensor.** Thinnest margin: corners 71° vs the 60° rule, against 23° for
straights. A rule nearer the middle (about 45°) would leave more room both ways; to
decide when building step 9.

**New problem: the step counter undercounts Mohammed on this sensor.** Live counts were
18.5 and 21.7 for 28 counted steps (34% and 22% low, outside the ±), while Raph's two
loops were within the ± (26.4 and 26.8 for 28 and 27). The HW7 counter was trained on
Mohammed, so this isn't about the walker it learned from. Candidates: this sensor's gx
offset of about 34°/s (the counter's rotation-size features include it), a different
strap position, or the small loops' many corners (counters miss steps in turns). This
goes into the step-counter decision (checklist part 1).

## 2026-11-18: Experiment: does the sensor explain the undercount? (before/after swap)

**Question.** On Raph's sensor the HW7 step counter undercounted Mohammed's LoopLeft badly
(18.5 for 28 steps) but not Raph's (26.4 for 28). Raph's sensor has a gyro offset of about
34°/s on gx, and the HW7 counter was trained on Mohammed's own sensor. If the sensor is the
cause, swapping in Mohammed's sensor should fix Mohammed's count.

**What changed:** only the sensor (Mohammed's MPU-6050, the one the HW7 counter was trained
on, same wiring, 0x68). Same board, same app, same loop, same walkers, right ankle. The
sensor was swapped with the board on; the sketch's reconnect fix set it up again (log:
"no_answer" at 18:20:19, "reading again" at 18:20:57). Recordings in
`data/sensor_swap/`. Board trial T06 was walked by Raph but saved under Mohammed by
mistake: the copy `Raph_LoopLeft_MohammedSensor.csv` has its `person` column set to Raph;
the board's own files are unchanged.

**Mohammed's sensor, 10 s still on the table** (`MohammedSensor_Still.csv`, board T05):
gyro offset **gx -3.0, gy +2.2, gz -0.3°/s** (Raph's: gx +34.9, gy -0.3, gz -2.9),
noise 0.1°/s per axis. No dropouts.

**Step counts, LoopLeft, 28 counted steps each:**

| Walker | Raph's sensor (before) | Mohammed's sensor (after) |
|---|---|---|
| Mohammed | 18.5 ± 3.7 (-34%) | **22.0 ± 3.7** (-21%), board T07 |
| Raph | 26.4 ± 2.9 (-6%, within ±) | **32.1 ± 3.0** (+15%, outside ±), board T06 |

**What it showed**
- The swap raised *both* walkers' counts, by 3.5 and 5.7 steps: this sensor makes the
  counter count more, for everyone. It didn't fix Mohammed specifically.
- **On both sensors, Mohammed's walk counts about 8-10 steps fewer than Raph's** for the
  same 28 steps (18.5 vs 26.4; 22.0 vs 32.1). So the main cause is how Mohammed walks
  these small loops, not the sensor. The HW7 counter was trained on 20 m straight walks;
  tight loops with four corners may look different in his gait.
- Neither sensor gets both walkers right: Raph's sensor fits Raph, Mohammed's sensor
  still undercounts Mohammed and now overcounts Raph.
- Turns don't care about the sensor: LoopLeft totals +319° for Raph (+309° on his sensor)
  and +273° for Mohammed (+280° on Raph's sensor). Mohammed's rightward drift on the
  straights showed up again on the new sensor, so it follows the walker (gait or a
  slightly curved path), not the sensor.

**What it didn't prove:** one trial per walker and sensor, so the normal spread between
repeats of the same walk is unknown (a few steps would be enough to blur this). The strap
position also changed with every swap.

**For the step-counter decision (checklist part 1):** the HW7 counter as it is can't be
trusted on loops with corners: 22-34% off for Mohammed on either sensor. Options: test it
on straight walks with each sensor (what it was trained for), retrain it with both
walkers' walks including corners, or compare Raph's CNN counter on the same recordings.

## 2026-11-18: Raph's CNN counter on today's recordings (offline, on the laptop)

`training/compare_raph_cnn.py` runs Raph's counter (his `step_net.py` and
`models/step_net.pt` from his repo, unchanged) over every recording from Step 0 and the
sensor swap. Nothing on the board changed. His model is loaded with `weights_only=True`
(his own loader allows the model file to run code). Check first: on his own November walk
it counts 52 of 61 steps (his report: 50).

**As recorded, it counts 0 steps on every walk.** The reason is how the sensor sits on the
leg: in his recordings gravity is on the sensor's y axis and the leg swings on y and z;
HW7's strap puts gravity on x and the swing on x and z. His training tilted the data up to
25° and flipped signs but never swapped axes, so his nets have never seen a swing on our
axes. With our axes renamed to his layout (his x = our y, his y = our x, his z = -our z, a
plain rotation; the mirror-image version without the z flip does much worse):

| Recording | Counted | HW7 counter (live) | Raph's CNN |
|---|---|---|---|
| Raph LoopLeft (Raph's sensor) | 28 | 26.4 | **28** |
| Raph LoopRight (Raph's sensor) | 27 | 26.8 | **28** |
| Raph SpotTurns | 0 | 2.8 | **2** |
| Mohammed LoopLeft (Raph's sensor) | 28 | 18.5 | **26** |
| Mohammed LoopRight (Raph's sensor) | 28 | 21.7 | **28** |
| Mohammed SpotTurns | 0 | 4.6 | **0** |
| Mohammed's sensor, still on the table | 0 | 0.2 | **0** |
| Mohammed LoopLeft (Mohammed's sensor) | 28 | 22.0 | **28** |
| Raph LoopLeft (Mohammed's sensor) | 28 | 32.1 | **28** |

**What it shows:** once the axes match, Raph's counter is within 2 steps on every
recording: both walkers, both sensors, loops with four corners. The HW7 counter was off by
up to 10 steps and depended on walker and sensor. Raph's counter finds each stride of the
strapped leg directly, which seems to hold up in corners and for both gaits, where HW7's
counter (a rate estimated from 2 s clips, trained on straight walks) doesn't. It only
counts whole strides, so counts come in steps of 2. Limits: one recording per walker,
sensor and loop; the axis renaming was chosen from these recordings' orientation (where
gravity and the swing are), not from the counts.

## 2026-11-18: Step-counter decision so far

**Decision:** no more dedicated step-counter tests (no straight walks). The counter is
judged from the real route demos: both walkers walk the same route, and their step totals
are compared.

**Why that is enough for now:**
- **The turn count does most of the work in the policy.** Which leg of the route the
  walker is on comes from the number of left and right turns, and Step 0 showed the ankle
  gyro counts every corner clearly for both walkers.
- **Steps since the last turn only time the warnings:** when to say "turn left soon" on a
  straight stretch. An error of a few steps there shifts a warning a little; it doesn't
  send the walker the wrong way.
- **The route demos will show how far apart our counts are.** Both walkers on the same
  route, each stretch between turns the same length: if their steps since the last turn
  disagree a lot, the policy will blur where the warnings go, and that shows up in the
  labels and in training.

**What today's comparison adds:** Raph's CNN counter, with the axes renamed, matched the
counted steps on every recording, while the HW7 counter undercounted Mohammed by up to a
third. It is the stronger candidate for the route demos. To use it live it needs: its
nets in plain numpy on the board (as HW7's counter is), and the axis renaming built in.
To decide before the first route demo.

## 2026-11-18: Decision: Raph's CNN counter for the route demos

**Decided (Mohammed and Raph):** the route demos use Raph's CNN step counter, not the HW7
counter.

**Why:**
- On every recording from today (both walkers, both sensors, loops with four corners and
  spot turns) it was within 2 steps of the counted steps, once our axes are renamed to his
  layout. The HW7 counter was off by up to 10 of 28 steps and depended on walker and
  sensor (it undercounted Mohammed by 21-34% on either sensor).
- It finds each swing of the strapped leg directly, which held up in corners; the HW7
  counter estimates a rate from 2 s clips and was trained on straight walks only.
- Steps since the last turn time the warnings, and both walkers' demos go into one
  policy, so a counter that agrees across walkers matters more than one that suits one
  person.

**What it needs before the first route demo:** its five nets in plain numpy on the board
(the board has no PyTorch; HW7's counter already runs this way), the axis renaming built
in, and a check that the numpy version gives the same output as his PyTorch version.

## 2026-11-18: Distance decision, and Raph's counter ported to numpy

**Distance:** `distance_m` stays in `/api/state` as steps × 0.41 m (Raph's fitted 0.823 m per
stride), so nothing on the page or in the protocol changes. **The steps-vs-meters
comparison is dropped:** with this counter, meters are just steps times a constant, so they
add no information; and a stranger following the guide wouldn't have a stride-length
setting of their own anyway.

**Steps arrive late and in twos:** a stride is counted about 0.6-0.85 s after it happens
(once it is 0.6 s old, checked every 0.25 s), and the count goes up by 2. So "steps since
the last turn" also jumps by 2, a little late. Fine for now; to remember when timing the
warnings before a turn.

**Speed on the UNO Q:** a numpy forward pass with StepNet's exact layer sizes (random
weights), 5 nets on one 4 s window: **35 ms median** (36.6 ms slowest) inside the app's
container on the board, while Step Recorder ran. One window every 250 ms = about 14% of one
of the 4 cores. Fast enough.

**Export** (`training/export_raph_cnn.py`): Raph's `models/step_net.pt` (his commit
`713da130607d`, loaded with `weights_only=True`) -> `uno_q/python/raph_step_model.npz`,
weights unchanged, plus his counting settings, the axis swap and the stride length.
**16,201 trainable weights per net**, matching Raph's Notion page, plus 288 batch-norm
running averages. 329 KB for all five.

**Port** (`uno_q/python/stride_counter.py`, numpy only): the same layers (conv 8->24 with
stride 2, batch norm, ReLU; five dilated blocks 1-16 with batch norm, ReLU and the input
added back; 1x1 output; linear stretch to 400; sigmoid), his input preparation (including
(|acc| - 1) / 2 and |gyro - median| / 300), his counting rule line for line (threshold 0.5,
0.4 s apart, counted at 0.6 s old, 1 s of context, steps from the average's peaks, each
net's own count for the ±), scipy's find_peaks rewritten in numpy (flat tops counted once,
at the middle), and a live counter with the same controls as HW7's.

**Check** (`training/check_numpy_port.py`, PyTorch vs numpy on the same windows, all nine
recordings from today plus Raph's November walk): largest score difference anywhere
**7.5 × 10⁻⁷** (tolerance 10⁻⁵); peaks identical to scipy's in every window; the same
strides at the same samples, the same per-net counts and the same steps on every recording
(26/28/0/28/28/2/0/28/28 and 52 on his walk); the live counter, fed one sample at a time,
gives the same steps. Not yet run on the board itself (build step 4).

**Port review:** Mohammed and Raph read `prep`, `find_peaks` and `StrideCount.update` in
`stride_counter.py` against Raph's `step_net.py`: it looks right. Together with the
side-by-side check above.

**Raph's sensor back on** (swapped with the board on: "no_answer" at 18:43:04, "reading
again" at 18:44:05). Still test on the table (`data/sensor_swap/RaphSensor_Still.csv`,
board `Raph_Test_T04`): gyro offset **gx +35.1, gy -0.6, gz -2.5°/s**, noise 0.1°/s, no
dropouts. gx of about +35°/s confirms it is Raph's sensor (Mohammed's: -3.0).

## 2026-11-18: Board app step 1 on the board; walking days on the board's own network

**Build step 1 runs on Raph's board** (from the terminal, `arduino-app-cli`): the page is
served on port 7000, byte for byte the repo's page; Mock mode works (steps, since turn,
turns, Start/End walk, Download CSV). Step Recorder stopped meanwhile; all of today's board
recordings and the board's trial logs were copied to `data/` first.

**Decided (Mohammed and Raph; Chris confirmed that running our own Wi-Fi network on campus
is OK):** Mohammed's phone can't use Tufts_Robot and we don't use a phone hotspot, so on
walking days the board makes its own Wi-Fi network, **NolopNav**, with the page always at
http://10.42.0.1:7000. Build step 2 (the address on the LED matrix) is skipped.
- NolopNav starts by itself on walking days (so a power-bank swap mid-walk brings it back),
  and the board goes back to Tufts_Robot each evening.
- Mohammed types the password himself; it stays in the board's network settings only, not
  in the repo or any notes.
- Nolop Navigator is the default app on walking days, switched back with the network.
- Network changes go over the USB-C cable (adb), tested first. Checked today: the Wi-Fi
  chip supports hotspot mode, the `arduino` user may change network settings without the
  admin password, adb is on the laptop (App Lab's), but the board showed **no USB data link**
  yet (not plugged in, or a charge-only cable). `arduino-app-cli` has no command to clear a
  default app, so the evening step sets one Raph chooses.
- Commands and the switch-back steps: `uno_q/README.md`, "Walking days". Not switched yet:
  the build continues on Tufts_Robot until the app is ready for real walks.

**Build step 3 runs on the board** (19:09): HW7's sketch (unchanged, new header comment) and
`python/sensor.py`, which collects the readings 10 times a second, checks each one (all
zeros = lost power, raw -1 = no answer), counts lost readings from the running numbers and
logs a summary every 10 s. Raph's sensor flat on the table: **999 readings in 10.1 s, 0
lost, 0 bad**, latest gx +34.9 to +35.1°/s (his sensor's offset), az -1.05 g. (The first
summary showed 1,391: the readings queued while the app started, collected in one go.)
Change from HW7: a batch that arrives cut short is still dropped, but the last running
number is kept, so the next batch shows how many readings were lost; each lost reading
becomes a "not real" placeholder, so the step counter's 4 s window stays 4 s (step 4).

**Evening default app:** Raph's How Many Steps (`/home/arduino/ArduinoApps/Steps-UnoQ`), the
app that was running when we started on his board, so each evening the board goes back to
how Raph had it (Raph agreed). **USB test, second try (19:20):** still no link: adb listed no
device and the laptop's USB list showed no board at all, with the cable that worked with App
Lab this morning. The laptop had also left Tufts_Robot (address 10.243.41.251), so the board
couldn't be reached over Wi-Fi either. To retry.

**USB test passed (19:16)**, once the board was plugged in again (it restarted on plugging
in): `adb devices` lists it, `adb shell` reaches the board named Raph as user `arduino`, and
over USB that user may change network settings. So NolopNav can be switched over the cable.

**Build step 4 runs on the board** (19:18): `main.py` feeds every reading (placeholders for
lost ones too) to `LiveStrideCounter` and logs the steps each time they change, plus a
summary every 10 s with how long the 5 nets took. First tested on the laptop with stand-ins
for the board's libraries, replaying Raph's LoopLeft in batches (one cut short): 28 steps,
the same as the checked port, and 10 lost readings filled in. On the board, standing still:
1,015 readings in 10.2 s, 0 lost, **0 steps**; the nets ran 41 times in 10 s, **median
49 ms, slowest 52 ms** (91 ms only for the first run), against a budget of one run every
250 ms: about 20% of one core. (The speed test's 35 ms left out the input preparation and
peak finding.)

**Problem after the board restarted:** the sketch didn't answer Python at all
(`get_batch` timed out every 10 s), and the router never saw the sketch register its
functions; it logged bursts of "invalid packet, expected array" instead. Starting the app
again and recreating its container didn't help; **restarting the app, which flashes the
sketch again, did**. Cause unknown (possibly the microcontroller starts before Linux's
router is ready after a power-up, so its first messages are lost). **To test before the
first walk:** with Nolop Navigator as the default app, power-cycle the board (as a power-bank
swap would) and check readings flow; if they don't, the app could restart itself when no
readings arrive at all.

Also after the unexpected power-off: the app container's log file had a stretch of null
bytes (the log was being written when the power went), so `app logs` stopped there. Fixed
by deleting Nolop Navigator's container (`docker rm nolop-navigator-main-1`; the CLI built a
fresh one on the next start). Only the old log lines were affected.

**Known limit of the live counter:** while a 4 s window holds a "not real" reading (a lost
or bad one), the nets don't run, so a cut-short batch while walking loses the strides of
about 1.6 s around it (2-4 steps). Cut-short batches came about 6 times an hour today.

**Restart test** (19:21, Nolop Navigator set as the default app over USB, then the USB cable
unplugged and plugged back in = power off/on): the app **started by itself and readings
flowed from the start, without a reflash** (about 1,000 per 10 s, 0 lost, nets 49 ms). The
router again logged one burst of "invalid packet" messages (37, at once, during start-up)
and this time it did no harm. So the earlier failure (19:16) is still unexplained; it came
after manual starts (start, then a fresh container, no reflash). One good restart of one
tried: to repeat tomorrow with the power bank.
- What first looked like a one-minute gap was the board's clock: after a restart it starts
  from a saved time about 50 s behind and jumps forward when it syncs over the network
  (19:23:18). The app measured intervals with the wall clock, so it saw "60.3 s" and briefly
  "no reading for 0.5 s"; in fact 884 readings (about 9 s of data) had arrived since it
  started. Fixed: `sensor.py` and `main.py` now use `time.monotonic()`, a clock that only
  counts forward. On NolopNav (no internet) the board's clock never syncs: its time of day
  may be wrong, but it won't jump.

**Sketch not answering after some starts: what we found.** Starts today, and whether the
sketch answered Python:

| Time | How the app started | Router: burst of 37 "invalid packet" before Python connects | Sketch answered |
|---|---|---|---|
| 19:09 | `restart` while running | (not checked) | yes |
| 19:16, 19:17 | `start` from stopped, after the board restarted on plugging in | burst at 19:16:24 | no |
| 19:18 | `restart` while running | (flash) | yes |
| 19:22 | by itself at power-up (default app), restart test 1 | yes, 19:22:10 | yes |
| 19:26 | `restart` while running | yes, 19:26:34 | yes |
| 19:35 | `restart`: stopped the app but didn't start it again (no error shown) | — | — |
| 19:36 | `start` from stopped | **none** | **no** |
| 19:37 | `restart` while running | **none** | **no** |
| 19:38 | power off/on (USB unplugged and plugged in), default app, restart test 2 | yes, 19:38:41 | **yes** |

The burst is the sketch starting up (its first bytes on the link to Linux before the two
sides are in step), so **no burst = the microcontroller isn't running the sketch after
flashing** (the flashing tool halts it to write the program; it seems not to have been let
go). After the half-failed restart at 19:35, neither `start` nor `restart` got it running
again; a full power-off did. Restart test 2 passed: the app started by itself and readings
flowed without a reflash.
- **For walking days:** after any deploy, check the router log shows the burst and the app
  log shows readings (`Sensor: ~1000 readings in 10 s`). If the sketch doesn't answer, power
  the board off and on (unplug the cable or power bank for 5 s); that has worked every time.
- The 19:16 failure fits too, if plugging in the USB cable restarted the board while
  the microcontroller was being flashed or held; not proven.

**Build steps 5-7 run on the board** (`/api/state`, `/api/reset`, `/api/rows`; `python/walks.py`
saves each walk's rows to `walks/Person_kind_Wnn.csv` with tickets, undo and safe rewrites).
Laptop tests first (10 checks on the walk store, including a resent batch, undo and a
restart; the whole app with stand-in libraries). **Live test with the page** (Mohammed on
the laptop, Raph swinging the board): steps went 2 -> 16 in twos; taps Left, Straight,
Stairs, then Undo. **The board's walk file matches the page's Download CSV exactly, row by
row** (10 rows); the Stairs row reached the board and was removed by the undo ("+0 -1").
Walk 1 on the board is empty (started, no rows). Files in `data/live_test/`.

**Build step 9 (turns, `python/turns.py`) runs on the board.** First version (60° within
2 s, then from the last turn) on the 8 Step 0 recordings: 6 of 8 exact; Raph's 180° spot
turns counted as 3 + 3 (it counted every 60°), and one of Mohammed's corners was missed (it
took about 4 s with a pause: 49° -> 119°, no 2 s stretch reached 60°). The live heading also
drifts more than the offline script's (Mohammed's LoopRight -413° live vs -356°), because
"up" can only be averaged over the past second. **Final rule:** 60° within **3 s** (as
decided for slow corners: widen the window, don't lower 60°), and after a turn the next one
in the same direction is measured as a quarter turn (60° beyond 30° past the last one).
**`training/check_turns.py`: all 8 recordings counted exactly** (every corner of the 6
loops, including Raph's paired corners, and 2 + 2 for the 180° spot turns), no false turns;
straight walking at most 19-31° within 3 s. **On the board:** board flat on the table, Start,
5 s still (offset gx 38.3°/s, 0.007 g), then 90° left -> Turn L, 90° right -> Turn R; the
page's Left label went back to Straight by itself. Raph's sensor's gx offset moved 36.1 ->
38.3°/s in two minutes (warming up), so measuring it at every Start is right.

**Back to Raph's setup at the end of the day:** How Many Steps (`Steps-UnoQ`) running and
the default app again; Nolop Navigator stopped (its files and saved walks stay on the board).

## 2026-11-19: Label cleanup, the policy, Navigate on the board's policy, one command

Built before the walking session (3-6 pm), so nothing needs coding during it. Not yet on
the board: it runs Raph's app today.

**Label cleanup** (`training/clean_labels.py`, raw files never changed): the board's counted
turns place the turn labels, the taps only check them. Each counted turn gets its label on
the rows of the **6 steps before it** (`--lead`, about 3 s of walking: the instruction comes
that far ahead; to tune on real walks); every other row is Straight except Stairs/Arrived
taps. That also fixes a Left/Right left on after a turn. Taps are matched to counted turns
(20 steps before to 4 after) and reported: on time (with how many steps early), late, no
tap, the other way, and **taps with no counted turn** (CHECK: a missed turn or a mis-tap).
Rows describing the same moment are merged. Corrections (DAgger walks) are kept as they are.

**Policy** (`uno_q/python/policy.py`, used by both the board and training): a lookup table
like the AnnaCode Table Cloner. Situation = (left turns, right turns, stairs, steps since
the last turn in buckets of 4); answer = the most common cleaned action; correction rows
count 3 times; an unseen situation borrows from the nearest one (a different turn count
costs 100, stairs 50, each bucket 1, so the same stretch first). `training/train_policy.py`
prints the table per stretch, tests it leaving one walk out, writes
`training/policy_report.md` and `uno_q/python/policy.json`.

**Tests** (`training/tests/test_pipeline.py`, 24 checks, all pass): fake walks made the way
the page and the board make them (Mohammed: on-time tap, late tap left on, stairs, arrived;
Raph: more steps per stretch, an untapped turn, a tap the other way, a mis-tap; a correction
walk; an empty walk; an excluded test walk), with every cleaned label and report count
checked, and the table's answers (Left/Right at the end of each stretch, Stairs, Arrived,
nearest-situation fallback, a correction outvoting demos). On the fake walks the
leave-one-walk-out test agrees with 91% of rows. The real Live-test walks clean without
errors (the swung-board walk's Left tap is flagged CHECK: no turn was counted). Bugs found
by the tests and fixed: the cleaner changed labels in place before reading the taps (so it
saw its own labels), and the report file was overwritten by test runs.

**`/api/predict` and Navigate:** the board answers with the policy for its own current state;
`policy.json` is read again whenever it changes, so a new policy needs no restart (no
reflash, no power-off). The page's Navigate mode (Live) asks every 0.25 s (a turn can be
counted between steps), shows "board policy" or "nearest known situation", shows "No
policy" when there is none, and saves the board's answer as `predicted` on corrections.
Mock mode keeps the placeholder. Checked: the board app with stand-in libraries (no policy
-> "no policy on the board yet"; policy copied in -> loaded and answered without a
restart); the page with a fake board (8 new checks, and the 33 earlier ones still pass,
one updated: a correction now saves the board policy's answer).

**One command** (`training/update_policy.py --via usb | nolop | ip`): checks the board is
Raph, pulls the walks (skipping `data/walks_excluded.txt`: the three Live-test walks
W01-W03 still on the board, so route walks start at W04), cleans, trains, copies only
policy.json (temporary name, then renamed), and checks the policy answers and sensor readings
arrive; if they don't, it prints the power-off steps. Tested with a folder standing in for
the board (pull, skip, clean, train, deploy, run twice). **Not yet tested against the real
board:** it was off the cable and not on Tufts_Robot this morning; run `--check-only` with
the board plugged in before the session.
- Added after the first commit: `--code-only` (put the app on the board before the first walk,
  when there is nothing to train yet: the board still runs the previous version, without
  `/api/predict`), the command no longer stops when there are no walks yet, and the cleaner
  empties `data/cleaned/` first, so a walk excluded later can't keep training the policy
  from an old cleaned copy (test added).

## 2026-11-19: Why /api/predict "didn't answer" (it was the laptop side, not the board)

Session 3-6 pm, run from Raph's Windows laptop (Claude Code took over from Mohammed's).

**Symptom:** `update_policy.py --via usb --check-only` (on Mohammed's Mac) said `/api/predict`
closed the connection without a response.

**What we checked:**
- Asked the board directly over Tufts_Robot from Raph's laptop: `curl
  http://10.247.137.63:7000/api/predict` answered `{"ok": false, "error": "no policy on the
  board yet"}` (the right answer with no policy), and `/api/state` answered too. **The board
  app was fine; nothing on the board was changed or redeployed.**
- `/api/predict` is the only part of the check that uses HTTP (the app/readings checks read
  the log), which is why only it failed.

**Cause (most likely, not reproduced on the Mac):** over USB the script forwarded the
laptop's port **7000** to the board. On a Mac, AirPlay Receiver already listens on 7000, so
`adb forward` failed (its error was hidden) and the request went to AirPlay, which closes
the connection with no answer. `tools/deploy.py` avoids this by using 7007.

**Fixed in `training/update_policy.py`:**
- USB: laptop port 7007 -> board port 7000, and a failed `adb forward` now stops with adb's
  own message.
- adb is also looked for in App Lab's Windows folder (it only knew the Mac one).
- Wi-Fi (`--via ip` / `--via nolop`): ssh/scp now remember the board as `nolop-raph`
  (`HostKeyAlias`, `StrictHostKeyChecking=accept-new`). On Raph's laptop the first try
  failed with "Host key verification failed": the laptop knew the board only under
  deploy.py's name `unoq`, so the name check read nothing and the script stopped.

**Result:** `update_policy.py --via ip --host 10.247.137.63 --check-only`: connected to Raph,
app running, 1003 readings in 10 s, `/api/predict` = "no policy on the board yet".
`training/tests/test_pipeline.py`: all passed. **Not tested yet:** the USB path (no board on
Raph's laptop's cable at the time) and `--code-only` from Windows (scp of a Windows path).

## 2026-11-19: First walk test: page showed 0, "Walks used 4/10", false left turns

Times are local (the board's log is in UTC, 5 h ahead).

**What happened:** the walk test (~3:43-3:46 pm) was walked with the page in **Mock** mode by
mistake, so the board was never reset and nothing was saved. The board still counted, from
the moment it was strapped on: 42 steps and **16 left / 2 right turns**. Most "turns" came
while standing or at 0-8 steps: false turns. Before that, from 3:41 the heading climbed a
steady ~17 deg/s with no steps, so the gyro offset measured at power-on (on the table) no
longer fit once the board was on the ankle.

Then the page was set to Raph + Live and Start was pressed at 3:46:58 on the **Navigate**
tab, so the board made `Raph_dagger_W04.csv` (a correction walk, not a demo). The offset was
measured while moving: log says "accelerometer spread 0.356 g - NOT STILL, turns may be
off" (still is under 0.05 g). Afterwards the heading drifted ~2 deg/s while standing.
The page showed 0 steps / 0 rows correctly: no steps were walked after that Start, and
rows are only saved per step or tap.

**"Walks used 4/10"** is not a count of real walks: the page shows the board's walk number,
and the board numbers a walk one more than the highest W-number among the files in
`python/walks/`. The three 2026-11-18 test files (W01-W03) plus the new W04 made it 4.

**Done (nothing deleted, nothing deployed):** moved all 4 files on the board to
`python/walks/tests/` (never pulled, never numbered); `data/walks_excluded.txt` lines for
W01-W03 turned into comments so a real walk can reuse those names. The app still has W04 in
memory, so the next walk is W05 until the app restarts; after a restart it is W01.
The official count stays the table in `data/README.md` (0 route walks so far).

**Open problem:** turn counting depends on standing completely still for the 5 s after Start.

## 2026-11-19: Walk test W07, all test walks moved, walk count from the board, deployed

**W07 (Raph, Live, demo; walked 28 steps, 4 corners).** Board: 28 steps (exact), 5 turns.
Started 3:58:55 pm; gyro offset measured still (0.006 g). Turns (local time, steps since the
previous turn; angles from the walk file's heading for 1-3, from the 10 s log summaries for
4-5, which are rough):

| # | Time | Dir | At step | Since previous | Angle |
|---|---|---|---|---|---|
| 1 | 3:59:08.3 | L | 4 | 4 | about +80° |
| 2 | 3:59:15.0 | R | 12 | 8 | about -92° |
| 3 | 3:59:18.9 | R | 14 | 2 | about -86° |
| 4 | 3:59:41.3 | R | 22 | 8 | over 60° (rule); summaries -96° -> -147° |
| 5 | 3:59:51.8 | L | 28 | 6 | over 60° (rule); net only about +29° in the summaries |

Turn 5 came 3.6 s after the last step, with no steps after it: Raph turning to the laptop at
the end, not a mid-stretch turn. So the 4 walked corners were all counted, plus one turn at
the end while standing. Not checked: whether turns 2 and 3 (2 steps apart) were two real
corners.

**Problem found:** W07's file has only 8 rows, up to step 16 (3:59:22). The board got no
rows after that, although it counted to 28. Rows 18-28 never reached the board (page ended,
reloaded, or stopped sending: not known yet). A demo must keep sending rows to the end.

W05 (0 rows) and W06 (offset measured NOT STILL, 0.210 g) were also tests.

**Done:** moved W05-W07 to `python/walks/tests/` (now W01-W07 there, nothing deleted).
Page: Live is the default, the walker is remembered per device (browser storage), and
"Walks used" is the board's count of walk files in `python/walks/` (`walks_used` in
`/api/state`; tests/ not counted) instead of the browser's own counter. Tested on the laptop
(fake board in headless Edge, WalkStore with a temp folder), then deployed with
`update_policy.py --via ip --code-only` from Windows (first time): code copied, app
restarted, sketch started, 1010 readings in 10 s, `/api/state` walks_used = 0, no policy yet.

## 2026-11-19: Rows stopped at 3:59:22 (page side), USB works, board on NolopNav

**W07's missing rows (after step 16, 3:59:22 pm):** the board did NOT lose Tufts_Robot:
NetworkManager logged nothing from 20:40 until the deploy restart at 21:04 (UTC), and the
board kept counting to 28 steps. So the page stopped sending rows (recording stopped, a
reload, or the device stopped polling/sending, e.g. screen lock). Can't tell which: the
board doesn't log page requests, and the deploy restart cleared the app's log from then.
Next test: watch the row count rise every 2 steps.

**USB route tested (first time):** `adb devices` lists the board over the USB-C data cable
on Raph's Windows laptop (adb is in `%LOCALAPPDATA%\Arduino15\packages\arduino\tools\adb\32.0.0\`),
`adb shell` opens bash as `arduino` on Raph.

**NolopNav created** by Mohammed in `adb shell` (password typed with `read -rs`, never shown
or written down). Checked: AP mode, 10.42.0.1/24, wpa-psk.

**Morning steps run over USB:** autoconnect on with priority 10, Nolop Navigator default,
`nmcli connection up NolopNav` -> activated. Checked over USB: wlan0 on NolopNav at
10.42.0.1, app running, ~1010 readings in 10 s, `http://10.42.0.1:7000/api/state` answers
(walks_used 0) and the page loads (HTTP 200). The laptop can't reach the board over Wi-Fi now;
use USB or join NolopNav.

## 2026-11-19: Two practice walks on NolopNav (W01, W02), not route demos

Both are practice, not route demos; they go to `python/walks/tests/` (not deleted; the
move is confirmed in the next entry).
- **W01** (Raph): phone test on NolopNav, about 20 steps, 3 corners tapped; the board
  counted 4 turns because of a walking mistake. No Arrived tapped.
- **W02** (Mohammed): 20 steps, Left tapped at step 4, Right at step 16, Arrived tapped.
  Phone copy: `nav_data_2026-11-19-21-51.csv` (13 rows, same as the board's file).

**What worked:** rows reached the board every 2 steps to the end (W02's phone CSV: a row at
every even step 2-20 plus the 3 tap rows). With Auto-Lock off, walk 7's problem (rows
stopping mid-walk) didn't come back, so screen sleep was the likely cause.

**Taps vs the board's turns (W02):** the board counted each turn at the same step as the tap
(Left tapped at 4, counted at 4; Right tapped at 16, counted at 16). The turn only shows up
in the next row, 2 steps later, because the step count goes up 2 at a time. So in the
cleanup's terms these taps are on time (0 steps early).

**Watch:** after the Left turn, the heading drifted about 30° on a straight stretch
(56° at step 8 to 24° at step 16). The Left corner itself read only about +55° between
rows (2° -> 55°); it still passed the 60°-within-3-s rule, but not by much. On long demos,
check that every corner is counted (missed corners would put the policy on the wrong
stretch).

**Move confirmed (over USB):** both files are in `python/walks/tests/practice_2026-11-19/`
(a subfolder: `tests/` already had the 2026-11-18 `Mohammed_demo_W02.csv`, so the same name
couldn't go there). `python/walks/` is empty; `/api/state` walks_used = 0.

**The board rebooted by itself** at about 4:57 pm, right after the USB-C cable was plugged
in (probably a short power dip when the power source changed). It came back on its own:
NolopNav active at 10.42.0.1, Nolop Navigator running, sensor reading (~1000 readings in
10 s, no power-off needed). The reboot also cleared the app's memory of W01/W02, so the
next walk is W01. Lesson: plugging or unplugging power mid-walk restarts the board and ends
the walk; don't do it during a demo.

## 2026-11-19: Route B demos (W01-W04), first policy trained and on the board

Route B: stairs down, left, straight, left, (stairs), Nolop. Demos: W01, W02 (Mohammed), W03,
W04 (Raph). Turns counted at steps: W01 34/38/54, W03 30/34/54, W04 32/38/54. **W02 excluded**
(`data/walks_excluded.txt`, file kept): its 3rd left (about step 54) wasn't counted, turns
stayed 2, so its Stairs/Arrived end would be learned under "2 turns", right where the other
walks say Left. W02 still counts toward the 10 walks (4 used).

`update_policy.py --via usb` (first full run over USB): pulled 3 walks (W02 skipped),
cleaned (all 3 turns counted in each; Left taps 0-2 steps before the counted turn), trained
22 situations, copied policy.json, check OK (1019 readings in 10 s, /api/predict answers).
Leave one walk out: 79% of rows agree; turn rows 8/16.

**Table vs what we expected:**
- 0 turns: Straight 0-7, Stairs 8-31, Straight 32-35. **Left never wins before the 1st
  turn** (28-31: St3 L2 S1; 32-35: S2 L1). The Stairs taps run right up to the corner, and
  the cleanup keeps Stairs taps, so they eat most of the 6-step Left warning. The first
  "Left" only appears once the board has counted the turn: too late for a new walker.
- 1 turn: Left 0-3 (as expected), Straight 4-7 (W04 turned at 6 steps).
- 2 turns: Left only at 12-15; 16-19 is a tie (S2 L2) that goes to Straight, so a walker who
  needs 18-20 steps for that stretch (W03) hears Straight just before the corner.
- 3 turns: Stairs 0-3, Straight 4-15 (12-15: S3 A2), Arrived from 16 (expected 12-16).

## 2026-11-19: A label-cleaning rule we chose: the turn warning wins, up to the turn

**Our choice (not something the data forced), in `training/clean_labels.py`:** in the 6 steps
before every counted turn, up to and including the step at which the board counted it
(while the row doesn't show the turn yet), the label is the turn (Left/Right), even over a
Stairs tap. Arrived taps are always kept.

**Why:**
- On Route B the stairs end right at the first left. We tapped Stairs until the bottom, and
  the cleanup used to keep Stairs taps, so the 6-step Left warning was mostly hidden: before
  the 1st turn, Left never won, and a new walker would get "Left" only after turning.
- The old window stopped one step short (steps S-6 .. S-2). The row saved at the turn step,
  just before the board's count arrived, said Straight. Those rows made Straight win or tie at
  the end of a stretch (2 turns, 16-19: S2 L2 -> Straight), so a walker with a longer stretch
  heard Straight right before the corner. With the warning running to S, every row after the
  warning starts says the turn, so the end of each stretch (and anything past it, which uses
  the stretch's last bucket) says Left.
- What we give up: Stairs now shows for fewer steps before a corner (it gives way to Left).

Tests added (`training/tests/test_pipeline.py`, "rule:" checks); all tests pass.

**Retrained on W01, W03, W04 (W02 still excluded), copied over USB:** board's policy.json
matches the laptop's, "Policy loaded: 22 situations, trained 17:40", 996 readings in 10 s.
Leave one walk out: 85% of rows agree (was 79%), turn rows 27/31 (was 8/16).
New table: 0 turns: Straight 0-7, Stairs 8-23, **Left 24-35** (24-27 is a St3 L3 tie, which
goes to Left by the action order); 1 turn: **Left 0-7**; 2 turns: Straight 0-11, **Left 12-23**;
3 turns: Stairs 0-3, Straight 4-15, Arrived 16+ (unchanged).

**Still open:** the board's tie rule (`policy.py`, best()) puts Straight first, so a future
Straight-vs-turn tie would go to Straight. No such tie in this table; changing it needs a
code deploy.

## 2026-11-19: DAgger walks W05-W08, final training set, final policy

**DAgger walks:** W05, W06 (Mohammed), W07, W08 (Raph). 8 of 10 walks used; no more DAgger.
No retraining between them: the board's policy.json was trained 17:40 and copied at 17:40,
before W05 (about 17:44); all four ran on that policy. In all four, the walker corrected the
policy's early "Left" on the stairs (steps 24-30, 0 turns) to Stairs.

**W07: the two lefts after the stairs counted as ONE turn.** Not the quarter-turn rule (that
only applies after a turn has been counted, and none had been). From the log and the walk
file: the first left was slow. The heading went -72° (step 30) -> +7° (34) -> +16° (36) over
about 9 s, with a ~6 s pause between steps 34 and 36, so no 3 s window reached 60° and it
wasn't counted. The second left was then counted at step 38 (probably with the tail of the
first). After that every turn was one behind (the 3rd left counted as turn 2, at step 56).
Also: the gyro offset at Start was measured "NOT STILL" (0.051 g, just over 0.05).

**Final training set:** W01, W03, W04 (demos) and W06, W08 (DAgger) in full; W05 only rows
before step 40 and W07 only rows up to step 36 (`data/walks_trim.txt`, new: labels are worked
out on the whole walk, then later rows dropped; raw files unchanged; tests added); W02
excluded (3rd left not counted).
- W05 cut at 40: in the file, at step 58 it still had 2 turns (20 steps after the 2nd: the
  3rd left wasn't counted), and at step 60 the board had counted 2 Right turns. Rows after
  40 are on a wrong turn count.
- W07 cut at 36: rows after that are one turn behind (above).
- W08's last row is at step 56 with no Arrived: the board lost power and rebooted at about
  5:59 pm (uptime 0 at 22:59 UTC), which most likely ended the walk.

**Final policy** (`update_policy.py --via usb`, 7 walks, 127 rows, 23 situations), copied over
USB; board's policy.json is byte-identical to the laptop's (trained 18:14). Sensor: heading
changes live (-76° -> -84° in 6 s). Table: 0 turns: Straight 0-7, Stairs 8-31, Left 32-39;
1 turn: Left 0-7; 2 turns: Straight 0-11, Left 12-23 (12-15: L5 S4); 3 turns: Stairs 0-3,
Straight 4-11, Arrived 12-19 (12-15: A5 S3).
Leave one walk out (demos only): 78% of rows, turn rows 16/31 (was 85%, 27/31). The drop is
expected: the DAgger corrections (x3) moved the first Left from step 24 to 32, while the
demos' cleaned labels (the turn-warning rule) still say Left from 24, and the test compares
against those labels.

**The board's log is damaged since the reboot:** reading it fails with "invalid character
'\x00'" (zeros written into the log file when the power went). So `app logs` and the
log-based checks in update_policy.py may show old lines from before the reboot, or nothing.
Checked the board's state through /api/state instead.

**Turn detector at 45° (replay only, nothing changed on the board):** `check_turns.py` on the
8 Step 0 recordings with the threshold set to 45°: 6 of 8 got extra turns (a 4-corner loop
counted as 5-7; spot turns as 3), 2 of 8 matched. At 60° all 8 match. Not changed: it would
double-count corners, a slow corner like W07's could still be missed, and every training row
holds turn counts from the 60° counter (no raw gyro saved to recompute them).

## 2026-11-19: Final test (W11), aborted W09/W10, walk count

**W09, W10:** final-test attempts, aborted: started, then stopped before any correction was
tapped (reason not recorded). Both files have 0 rows. Not used for training (the final
policy was trained before them). Moved on the board to `python/walks/excluded/`.

**W11, the final filmed test** (Navigate + correct, on the final policy trained 18:14). Taps:
Straight at step 32, Left 34, Straight 38, Left 50, Arrived 54. The board counted only 2
turns: the two lefts after the stairs merged into one turn (as in W07), so it stayed one turn
behind for the rest of the walk. It said Left at the right moments for the corners, but it
needed 3 corrections: Straight at the bottom of the stairs (it said Left at step 32),
Straight after the first left (it said Left at 38), and Arrived at Nolop (it said Straight
at 54). So it was not a clean success. Kept as a record, not trained on
(`data/walks_excluded.txt`).

**Walk count:** 11 walks total, over the limit of 10 by one: 7 used to train the navigator
(W05 and W07 in part), W02 recorded but excluded (missed turn), W11 the final filmed test,
W09 and W10 aborted with no data saved.

Note: the board's clock runs about 15 min slow on NolopNav (no internet to set it; "System
clock synchronized: no"), so walk file times from after the reboots are about 15 min early.

## 2026-11-19: Evening switch-back

Over USB: NolopNav autoconnect off and down (the board rejoined Tufts_Robot, 10.247.137.63),
How Many Steps (`Steps-UnoQ`) set as the default app and started, Nolop Navigator stopped.
First check: 0 IMU samples over MQTT. The board was power-cycled; after How Many Steps had
started, 1038 samples arrived in about 10 s on `ME193_Raphael_steps/imu`. (Earlier zeros were
counted while the app was still starting; its log is unreadable, same zero-byte damage.)
W02's raw file was added to `data/excluded/` as a record (same file as on the board).

## Tomorrow: final test with a new walker (checklist)

Walk 14 would be 4 over the limit of 10, so ask first.

1. **Email Chris** for an OK on walk 14 (a final test with a walker who doesn't know the way).
   No OK, no walk.
2. **Morning steps, over USB** (`uno_q/README.md`, "Walking days"): board plugged into the
   laptop, `adb devices` lists it; NolopNav autoconnect on (priority 10) and up; Nolop
   Navigator the default app and running.
3. **Sensor check:** the router log shows the sketch's start-up burst (about 37 "invalid
   packet" lines), and on the page the heading changes a little while the board stands
   still. Heading stuck at exactly 0.0 or no burst: unplug the power 5 s, plug in, wait 1 min.
   (The app log can't be read since the power losses; use the page or /api/state.)
4. **Phone:** joins NolopNav, Auto-Lock off, opens http://10.42.0.1:7000 and reloads it;
   Data = Live, the right walker, Navigate tab.
5. **Tester briefing:** after Start, stand completely still for 5 s; "Left" means turn at
   the next corner; make one clear, unhurried turn per corner (no stopping mid-turn); keep
   walking at a normal pace on the straights; don't touch the board or its power.
6. **Film:** the whole walk from the start to Nolop, and screen-record the phone so the
   instructions show at each turn.
7. **Afterward:** evening steps over USB (NolopNav off, Tufts_Robot, How Many Steps the
   default and running, MQTT samples flowing); pull the walk file; record it in the walk
   table and this log (what the board said vs what the tester did); commit and push.
