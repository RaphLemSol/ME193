# Draft for the Notion page

Copy this into Notion, add the pictures/video, and replace every **[FILL IN]**.
The numbers come from your own runs (`models/report.json`, the UNO Q log).

---

## The Impenetrable Safe

[VIDEO: walk up, press the button, LEDs light up, 3 numbers, latch opens. Then a wrong code: red X, intruder snapshot.]

GitHub: [FILL IN link to `the impenetrable safe` in your repo]

My safe opens with a finger code instead of a key. You press the button, the
LEDs light up, and you hold up three numbers with your fingers in the square
under the camera. A convolutional neural net I built from scratch in PyTorch
counts the fingers about 15 times a second. If the three numbers match the
code, a gear motor turns the latch open. It started out running on my laptop
with a USB webcam, and now it runs entirely on the Arduino UNO Q, with the same
webcam and the same trained model.

### How it works

1. **Press the button.** The UNO Q's RGB LED turns blue and its LED matrix
   shows three empty boxes.
2. **Hold up fingers in the square.** The webcam, on a fixed stand, looks down
   at a marked square. Each picture is cropped to the square, shrunk to 64×64,
   and passed to the net, which gives a probability for 0, 1, 2, 3, 4 and 5 fingers.
3. **The lock decides.** A number counts once the net is at least 75% sure of
   it for a full second. It flashes on the matrix and fills a box. After three
   numbers, the code is checked.
4. **Right code:** green LED, an open padlock on the matrix, and the motor
   opens the latch. **Wrong code:** red LED, an X on the matrix, and a
   snapshot of the intruder's hand is saved. Three wrong codes lock it out
   for 30 s, then 60 s, 120 s...

### What's in it

| Part | What it does |
|---|---|
| **FingerNet** | My CNN: 3 convolution + ReLU + max-pooling layers, then a linear layer to 6 outputs (about 49,000 weights). Trained with cross-entropy loss and Adam on about 10,000 pictures of my hand, with random rotations, shifts, zoom, flips, color changes, blur and noise so it doesn't memorize one exact pose. |
| **Computer version** | The webcam plugs into the laptop and PyTorch runs the net. The laptop sends the lock's decisions to the board over MQTT, and the board runs the button, LEDs and motor. |
| **UNO Q version** | The webcam plugs into the UNO Q's USB-C hub. The trained weights are exported, and I rewrote the net's forward pass in plain numpy so it runs on the board's Linux side without PyTorch. It gives the same answers as PyTorch to about 0.0000001. The board's microcontroller runs the button, RGB LED, LED matrix and motor driver. |
| **Hardware** | Arduino UNO Q, USB webcam on a stand, push button, Cytron Maker Drive, and a yellow gear motor as the latch. |

### Results

- **The finger counter:** about 70% right on single pictures it never trained
  on. Fists and an empty square (0) are right 100% of the time, and 1, 2, 4
  and 5 about 76–84%. **3 is the hard one** (often read as 2).
- **The whole safe is more reliable than that,** because a number has to be
  held steadily for a full second. One wrong frame can't enter a digit.
- **Speed:** the UNO Q runs the net in about 15 ms per picture, at 11–15
  pictures a second, which is about as fast as my laptop.
- It opened on the UNO Q for the right code (entered in about 6 s) and
  stayed shut for wrong ones.

---

## Before the box: fitting Anna's V data

[IMAGE: v_data/v_fit.png]   [IMAGE: v_data/v_loss.png]   [FILE: v_data/v_gradient_descent.xlsx]

Copy the math from `v_data/MATH.md`. The short version:

- **One neuron** is y = m·x + b. The loss is the mean squared error, the
  gradients are dL/dm = (2/N)Σ(y−t)x and dL/db = (2/N)Σ(y−t), and gradient
  descent steps m and b downhill: m ← m − lr·dL/dm. The spreadsheet does 5
  iterations of this; the loss drops from 0.222 to 0.053. But a line can't make a V.
- **A ReLU** (max(0, z)) adds a factor of 0 or 1 to the gradient. One ReLU
  neuron makes half a V.
- **A layer of two ReLU neurons + an output neuron**, trained with
  backpropagation (the chain rule, layer by layer), fits the V almost
  perfectly: each neuron learned one arm, both switching on at x ≈ 60 with
  slopes ±2.

---

## 1. The lock policy: how does it decide?

- The safe ignores the camera until the **button** is pressed. Then the
  UNO Q's LED turns blue, the LED matrix shows three empty boxes, and it
  skips 0.5 s of frames so you have time to get your hand in place.
- Every frame, the net gives 6 probabilities (0-5 fingers). These are
  **smoothed** (a running average) so one bad frame can't count.
- A **digit counts** when the same number has been held, at 75%+ confidence,
  for **1 second**. The LED matrix flashes it and fills one of the three boxes.
- The next digit must be **different** (or the square cleared with a fist),
  so holding one hand still can't count twice.
- After **3 digits**, it hashes them and compares with the stored hash.
  Right: green LED, latch opens, relocks after 20 s or a button press.
  Wrong: red X, and it **doesn't say which digit was wrong**.
- **3 wrong codes in a row → lockout** for 30 s, doubling each time
  (30, 60, 120 s...). A wrong code also saves an **intruder snapshot**.
- No new digit for 15 s → it gives up and stays locked.
- The code is never stored, only a salted SHA-256 hash of it.

[DIAGRAM: state machine IDLE → ENTERING → OPEN / wrong → IDLE / LOCKOUT]

---

## 2. Limitations (at least 4)

1. **Only 60 possible codes** (5 × 4 × 3 with three different numbers). Even
   with the lockout doubling, a patient person could try them all in a few hours.
2. **Anyone watching sees the code.** The fingers are the code, held up
   in full view (and the matrix flashes each digit).
3. **It only knows the hands and light it was trained on.** Different skin
   tones, rings, sleeves, a dark room, or sunlight on the square can lower the
   accuracy. [FILL IN: your accuracy on a held-out person, e.g. "on Anna, whom
   it never saw: 87%"]
4. **The camera must not move.** the taped square's position is calibrated
   once. If the stand is bumped, it crops the wrong part of the picture.
5. **Some numbers look alike.** [FILL IN from your confusion matrix, e.g. "3
   got mistaken for 2 or 4 x% of the time"], and finger combinations it
   never saw (e.g. 3 made with thumb, pinky and ring) may fail.
6. **Laptop mode isn't secure.** The laptop talks to the box over a
   public MQTT broker with no password, so anyone who knows the topic could
   send "open". Board mode doesn't listen to MQTT at all.
7. **The latch is timed, not measured.** The gear motor runs for a set
   time; it has no sensor saying the latch actually closed. A jam or a weak
   battery could leave it half open, and after a power cut it doesn't know
   where the latch is.
8. **No light of its own.** The room's lighting changes how the hand looks.
9. **It could be fooled** by a photo of a hand, since the net only sees a picture.

---

## 3. How does the neural net work?

[EMBED: the stop-action movie, with my voice-over]

(The movie covers: pixels → convolution filters → ReLU → max pooling → three
layers → linear layer → softmax → the training loop: loss, backpropagation,
gradient descent, and data augmentation.)

---

## 4. How did the UNO Q compare with the computer?

| | Laptop | UNO Q |
|---|---|---|
| Runs the net with | PyTorch | my numpy version of the same net (same weights) |
| Time per picture | [FILL IN] ms | [FILL IN] ms |
| Frames per second | [FILL IN] | [FILL IN] |
| Accuracy | [FILL IN] | [FILL IN: same model, so same unless the camera acts differently] |
| Setup pains | [FILL IN] | [FILL IN: e.g. camera access in the App Lab container, no screen to see what the camera sees] |

[FILL IN: a few sentences. Did the webcam's exposure/color look different on
the board? Was it fast enough? Was it more reliable without the laptop?]

---

## The usual questions

- **What I'm proud of:** [FILL IN]
- **What was hardest:** [FILL IN]
- **What I'd do next:** [FILL IN]
- **How I used Claude:** [FILL IN]
- **Something new I did (not done in class):** wrote the CNN's forward pass
  from scratch in numpy for the UNO Q (and checked it matches PyTorch),
  intruder snapshots, hashed code with lockout, and pictures of every layer
  of the net.
