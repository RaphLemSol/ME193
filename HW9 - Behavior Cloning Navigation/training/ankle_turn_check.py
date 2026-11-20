"""Can turns be seen from the ANKLE gyro alone? (HW9 Step 0 check, no turn logic yet.)

Usage:  python ankle_turn_check.py <recording.csv>
Writes ankle_turns.png (raw heading) and ankle_turns_bias.png (after removing the gyro
bias) into the current folder, and prints the heading every 2 s.

Reads either format:
- Raph's recordings: columns t_ms, ax, ay, az, gx, gy, gz
- HW7 Step Recorder recordings: time (UTC date and time), ax ... gz, activity, person
Acceleration in g, rotation in degrees per second, 100 readings per second.

How it works:
1. "Up": the accelerometer measures gravity plus the leg's own movement. Averaged over
   1 s, the leg's swing back and forth cancels out and what's left points straight up,
   seen from the sensor. This works however the sensor sits on the leg.
2. Turning rate: the gyro measures rotation around its own three axes. The part of that
   rotation around "up" is the walker turning left or right (positive one way, negative
   the other); the leg's swing is rotation around a sideways axis and mostly drops out.
3. Heading: adding up turning rate x time gives how far the walker has turned in total.
   A turn shows as a climb (or a drop), walking straight as a flat stretch.
4. Bias: a gyro reads a false rotation even when still (Raph's sensor: about 34 deg/s on
   gx alone). Added up over a minute that is hundreds of degrees, so the first 5 s, when
   the walker stands still, are used to measure it. It is measured and subtracted for
   EACH gyro axis (gx, gy, gz) BEFORE taking the part around "up". (Measuring it as one
   number around "up" doesn't work: how much of the gx offset shows up around "up"
   depends on the leg's tilt, which differs between standing and walking and changes
   every stride. On Step 0's loops that gave +350 and -276 deg; per axis gives +309 and
   -318, the same ~12% short both ways.)
"""
import numpy as np, sys, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

d = np.genfromtxt(sys.argv[1], delimiter=",", names=True, dtype=None, encoding="utf-8")
if "t_ms" in d.dtype.names:            # Raph's format: milliseconds
    t = (d["t_ms"]-d["t_ms"][0])/1000
else:                                  # HW7 format: "2026-11-01T23:17:28.892503+00:00"
    stamps = np.array([s[:26] for s in d["time"]], dtype="datetime64[us]")   # drop the "+00:00"
    t = (stamps - stamps[0]) / np.timedelta64(1, "s")
acc = np.c_[d["ax"],d["ay"],d["az"]]; gyr = np.c_[d["gx"],d["gy"],d["gz"]]
dt = np.diff(t, prepend=t[0])          # time between readings, in s
# Dropout check: readings should come every 10 ms; a gap over 25 ms means lost readings
print("rows", len(t), "duration", round(t[-1],1), "s; gaps >25ms:", int((np.diff(t)>0.025).sum()))

# 1. gravity direction ("up"), smoothed over 1 s (100 readings), so the ankle's own swing
#    averages out; then made 1 long, so only its direction is kept
k = 100; g = np.array([np.convolve(acc[:,i], np.ones(k)/k, "same") for i in range(3)]).T
g /= np.linalg.norm(g, axis=1, keepdims=True)
# 2. rotation around "up", deg/s: the part of the gyro reading that points along g
yaw_rate = (gyr*g).sum(1)
# 3. heading, deg: turning rate x time, added up
heading = np.cumsum(yaw_rate*dt)
# smooth heading over 2 s so the wobble from each step cancels, for the plot
hs = np.convolve(heading, np.ones(200)/200, "same")
plt.figure(figsize=(10,4)); plt.plot(t, heading, lw=.5, label="raw heading"); plt.plot(t, hs, lw=2, label="smoothed 2 s")
plt.xlabel("time (s)"); plt.ylabel("heading (deg)"); plt.legend(); plt.title("Ankle sensor: heading from gyro around gravity")
plt.tight_layout(); plt.savefig("ankle_turns.png", dpi=110)
print("heading samples every 2 s:", np.round(hs[::200]).astype(int).tolist())

# 4. Remove the gyro bias, measured while standing still at the start (first 5 s): the
#    average of each gyro axis, subtracted from the raw readings, then the turning rate
#    around "up" again. The accelerometer's spread is printed to check the walker really
#    stood still then (under about 0.03 g; a little sway is fine).
still = t < 5
bias = gyr[still].mean(0)
print("bias per axis gx gy gz (deg/s):", np.round(bias,2), " accel std while 'still':", np.round(acc[still].std(0),3))
yaw_rate2 = ((gyr-bias)*g).sum(1)
h2 = np.cumsum(yaw_rate2*dt); h2s = np.convolve(h2, np.ones(200)/200, "same")
print("bias-removed heading every 2 s:", np.round(h2s[::200]).astype(int).tolist())
# The first and last 1 s are left off the plot: the 2 s smoothing runs past the ends of the
# data there. The scale fits the data, with a gray line every 90° (one right-angle corner).
shown = slice(100, len(t)-100)
plt.figure(figsize=(10,4)); plt.plot(t[shown], h2s[shown], lw=2)
lo, hi = h2s[shown].min(), h2s[shown].max()
for n in range(int(np.floor(lo/90)), int(np.ceil(hi/90))+1): plt.axhline(n*90, color="gray", lw=.4)
plt.ylim(lo - 20, hi + 20)
plt.xlabel("time (s)"); plt.ylabel("heading (deg)"); plt.title("Ankle heading after removing gyro bias (gray lines every 90°)")
plt.tight_layout(); plt.savefig("ankle_turns_bias.png", dpi=110)
