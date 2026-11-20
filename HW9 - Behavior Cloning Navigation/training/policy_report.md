# Policy table (2026-11-19 18:14)

From 7 walks (127 rows): Mohammed_dagger_W05.csv, Mohammed_dagger_W06.csv, Mohammed_demo_W01.csv, Raph_dagger_W07.csv, Raph_dagger_W08.csv, Raph_demo_W03.csv, Raph_demo_W04.csv
Steps since the last turn in buckets of 4; votes per action (correction rows count 3).
S = Straight, L = Left, R = Right, St = Stairs, A = Arrived. A situation not in the table uses the nearest one (same stretch first).

```
After 0 left, 0 right turns:
    0-3: Straight (S5)
    4-7: Straight (S4 St2)
    8-11: Stairs (St6)
    12-15: Stairs (St6)
    16-19: Stairs (St6)
    20-23: Stairs (St6)
    24-27: Stairs (St21 L3)
    28-31: Stairs (St12 L9)
    32-35: Left (L9 S6)
    36-39: Left (L3)
After 1 left, 0 right turns:
    0-3: Left (L9)
    4-7: Left (L7)
After 2 left, 0 right turns:
    0-3: Straight (S3)
    4-7: Straight (S6)
    8-11: Straight (S4 L2)
    12-15: Left (L5 S4)
    16-19: Left (L7)
    20-23: Left (L1)
After 3 left, 0 right turns:
    0-3: Stairs (St3)
    4-7: Straight (S4 St2)
    8-11: Straight (S6)
    12-15: Arrived (A5 S3)
    16-19: Arrived (A2)
```

Leave-one-walk-out test: 82/105 rows agree (78%)
  Mohammed_demo_W01.csv: 28/33 rows agree; turn rows 5/10
  Raph_demo_W03.csv: 28/36 rows agree; turn rows 6/10
  Raph_demo_W04.csv: 26/36 rows agree; turn rows 5/11
