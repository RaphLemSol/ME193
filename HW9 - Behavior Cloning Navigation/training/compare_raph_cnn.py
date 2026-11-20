"""Run Raph's CNN step counter offline on our recordings, to compare it with the counted steps.

Usage (from anywhere; the laptop needs torch, scipy and numpy):
    python compare_raph_cnn.py <folder of Raph's "How many steps"> <recording.csv> ...
    python compare_raph_cnn.py <folder> --as-recorded <recording.csv> ...

The folder is a copy of https://github.com/RaphLemSol/ME193/tree/main/How%20many%20steps
(step_net.py, gait_config.py and models/step_net.pt are used, unchanged).

How Raph's counter works (step_net.py): for every 4 s window, five small 1-D convolutional
nets score how likely it is that the strapped leg is at mid-swing at each moment. Each peak
of their average above 0.5 is one stride of that leg = 2 steps. The gyro's offset is
removed per window (its median), so a sensor's offset doesn't matter to it.

Why the axes are renamed: his nets were trained on his own recordings, where the sensor sits
so that gravity is on its y axis and the leg swings on y and z. HW7's strap puts gravity on
x and the swing on x and z, so x and y are swapped. His training tilted the data by up to
25° and flipped signs, but never swapped axes, so on our recordings as they are the nets see
no strides at all (0 steps on every walk). By default this script renames our axes to his
layout first: his x = our y, his y = our x, his z = -our z. (Swapping two axes alone would
also mirror the data; flipping z makes it a plain rotation, like the sensor turned on the
leg.) --as-recorded skips the renaming, to show the 0 counts.

Safety: his own loader uses torch.load(weights_only=False), which can run code stored in the
model file. Here it is loaded with weights_only=True, which accepts only tensors and plain
values.
"""
import sys
import numpy as np
import torch

repo = sys.argv[1]
args = sys.argv[2:]
as_recorded = "--as-recorded" in args
files = [a for a in args if a != "--as-recorded"]

sys.path.insert(0, repo)           # import Raph's step_net.py (and its gait_config.py) from his folder
import step_net as sn              # noqa: E402

# Our axes -> Raph's layout (rows: his x, y, z; columns: our x, y, z)
TO_RAPH = np.eye(3) if as_recorded else np.array([[0, 1, 0],
                                                  [1, 0, 0],
                                                  [0, 0, -1]])

# The five nets, loaded safely (see above)
saved = torch.load(f"{repo}/models/step_net.pt", weights_only=True)
nets = []
for state in saved["nets"]:
    net = sn.StepNet()
    net.load_state_dict(state)
    nets.append(net.eval())

print("axes:", "as recorded" if as_recorded else "renamed to Raph's layout")
print(f"{'recording':45s} CNN steps (spread between the 5 nets)")
for f in files:
    d = np.genfromtxt(f, delimiter=",", names=True, dtype=None, encoding="utf-8")
    acc = np.c_[d["ax"], d["ay"], d["az"]].astype(float)      # g
    gyro = np.c_[d["gx"], d["gy"], d["gz"]].astype(float)     # deg/s
    data = np.c_[acc @ TO_RAPH.T, gyro @ TO_RAPH.T]
    counter = sn.run_counter(nets, data)   # his live counting, run over the whole recording
    print(f"{f.split('/')[-1]:45s} {counter.steps:4d} (± {counter.spread():.1f})")
