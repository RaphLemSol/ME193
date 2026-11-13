# Stop-action movie: how FingerNet works

About 2-3 minutes. Shoot it on paper: printouts from `python visualize.py`
(saved in `movie/`), sticky notes, and markers, moved a little each frame
(phone on a stand, an app like Stop Motion Studio, 8-12 frames per second).
Record the voice-over yourself (Zoom or your phone) and lay it over the clips.
The words below are a starting point; say them your way.

| # | What's on the table (frames) | Voice-over |
|---|---|---|
| 1 | The safe; a hand slides into the taped square showing 3 fingers. | "This safe opens with a finger code. A neural net I built has to look at this picture and say: three fingers." |
| 2 | `01_camera_crop.png`, then a grid of sticky notes over it, each with a number. | "To the computer the picture is just numbers. The camera picture is shrunk to 64 by 64 pixels, with a red, green and blue value for each: 12,288 numbers." |
| 3 | `02_input_channels.png` pulled apart into 3 sheets. | "I split it into its red, green and blue layers, and shift the numbers so the average is zero. That way a darker room doesn't change things as much." |
| 4 | A small 5x5 square of clear plastic (the filter) sliding across the picture, leaving a trail of numbers on a new sheet. | "The first layer is a convolution. A filter, a little 5 by 5 grid of weights, slides over every spot. At each spot it multiplies and adds. A big number means 'what I'm looking for is here.'" |
| 5 | `03_conv1_filters.png`; then the 16 maps of `04_conv1_ReLU.png` appear one by one. | "There are 16 of these filters. That's the width of this layer. Some light up at edges, some at skin, some at the carpet. Every negative number is set to zero. That's ReLU, the same activation I used to fit the V." |
| 6 | A 2x2 window jumps across a map; only the biggest number in each block is kept (paper shrinks to half). | "Then pooling: in every 2 by 2 block, keep only the biggest number. The picture gets half as big, it keeps what was found, and a finger that moves a pixel doesn't matter." |
| 7 | `05` → `06` → `07` → `08` → `09` stacked: the sheets get smaller and more numerous. | "Then it does that two more times: 32 filters, then 64. That's the depth. Each layer looks at the one before it, so it goes from edges to finger shapes to 'three fingers sticking up'. The pictures get smaller, but there are more of them." |
| 8 | 64 tiny sheets unstacked into one long line of 4096 sticky notes, all strings running to 6 boxes labeled 0-5. | "At the end, all 4,096 numbers go into a linear layer: 6 neurons, one per answer, each a weighted sum of everything." |
| 9 | `10_probabilities.png`; the "3" bar grows. | "Softmax turns those 6 scores into probabilities that add up to 1. The biggest one is the answer." |
| 10 | A hand-drawn "3 ✔" vs "the net said 2 ✘"; a big red loss number. | "How does it learn the weights? I showed it about [FILL IN] labeled pictures. When it's wrong, the cross-entropy loss is big. It's small when it's confident and right." |
| 11 | Arrows drawn backward from the loss through the layers; little weight dials turning. | "Backpropagation uses the chain rule to find, for every one of the 49,000 weights, which way to turn it to lower the loss. That's the same math as m and b in the spreadsheet, just many more weights. Then gradient descent takes a small step. Repeat thousands of times." |
| 12 | One hand photo becomes many: rotated, shifted, flipped, darker. | "To get more training data, every picture is randomly rotated, shifted, flipped and re-lit each time. That made it [FILL IN: e.g. 12%] more accurate on bursts it never saw." |
| 13 | The loss curve from `models/training.png` drawn going down, epoch by epoch. | "The loss goes down every epoch, and it got [FILL IN]% right on pictures it never saw. 3 was the hardest." |
| 14 | Three hands in a row (4, 1, 3), boxes filling, the latch opening. | "Finally, the lock: hold each number for one second, three numbers, and if it matches, the safe opens." |
