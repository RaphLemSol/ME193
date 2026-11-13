# Fitting Anna's V data with gradient descent

Files: `annacode-v.tsv` (the data), `fit_v.py` (Python, makes `v_fit.png` and
`v_loss.png`), `make_excel.py` (makes `v_gradient_descent.xlsx`, 5 iterations
on m & b with live formulas).

## The data

120 points of (x, output). Plotted, they make a V: the output falls with a
slope of about -2 down to 0 at x ≈ 60, then rises with a slope of about +2.

To keep the numbers near 1, I divide both by 100: **u = x/100**, **t = output/100**.
Without this, the gradient for m is about 100 times bigger than the one for b,
and no single learning rate works for both. This is called feature scaling.

## 1. One neuron

A neuron multiplies its input by a weight, adds a bias, and (optionally)
passes the result through an activation function:

    z = m*u + b          (m = weight, b = bias)
    y = z                (linear neuron)

**Loss.** How wrong the neuron is, averaged over all N points (mean squared error):

    L = (1/N) * Σ (y_i - t_i)²

**Gradient.** How L changes when m or b changes (chain rule, with y_i = m*u_i + b):

    dL/dm = (2/N) * Σ (y_i - t_i) * u_i
    dL/db = (2/N) * Σ (y_i - t_i)

**Gradient descent.** Take a small step downhill, against the gradient:

    m ← m - lr * dL/dm
    b ← b - lr * dL/db

lr is the learning rate (0.5 here). Too big and it overshoots and blows up;
too small and it takes forever. One pass of this over all the data is one
**epoch** (here, one iteration).

The spreadsheet's **Linear neuron** sheet does exactly this for 5 iterations,
starting at m = 0, b = 0:

| iter | m | b | loss | dL/dm | dL/db |
|---|---|---|---|---|---|
| 0 | 0.00000 | 0.00000 | 0.22178 | -0.48501 | -0.82484 |
| 1 | 0.24250 | 0.41242 | 0.07666 | 0.20172 | 0.28767 |
| 2 | 0.14164 | 0.26859 | 0.05698 | -0.05104 | -0.11964 |
| 3 | 0.16717 | 0.32841 | 0.05418 | 0.04071 | 0.03027 |
| 4 | 0.14681 | 0.31327 | 0.05365 | 0.00617 | -0.02414 |
| 5 | 0.14373 | 0.32534 | 0.05345 | 0.01798 | -0.00366 |

The loss drops fast, then flattens. After 2000 iterations the best line is
almost flat (m = -0.04, b = 0.44): **a straight line can't make a V.**

## 2. A ReLU activation

ReLU ("rectified linear unit") sets negative numbers to zero:

    y = ReLU(z) = max(0, z)        ReLU'(z) = 1 if z > 0, else 0

The chain rule picks up that extra factor:

    dL/dm = (2/N) * Σ (y_i - t_i) * ReLU'(z_i) * u_i
    dL/db = (2/N) * Σ (y_i - t_i) * ReLU'(z_i)

Points where the neuron is "off" (z ≤ 0) have ReLU' = 0, so they don't move
the weights at all. The **ReLU neuron** sheet runs 5 iterations from
m = 1, b = -0.5 (on for x > 50, so it starts out fitting the right arm of the V):

| iter | m | b | loss | dL/dm | dL/db |
|---|---|---|---|---|---|
| 0 | 1.00000 | -0.50000 | 0.12732 | -0.09381 | -0.10242 |
| 1 | 1.04690 | -0.44879 | 0.12059 | -0.04243 | -0.06185 |
| 2 | 1.06812 | -0.41786 | 0.11907 | -0.00607 | -0.02402 |
| 3 | 1.07116 | -0.40585 | 0.11891 | 0.00869 | -0.00306 |
| 4 | 1.06681 | -0.40432 | 0.11887 | 0.00693 | -0.00528 |
| 5 | 1.06335 | -0.40168 | 0.11884 | 0.00700 | -0.00495 |

One ReLU neuron makes a "hockey stick": flat, then a ramp. That's half a V.
Left to run for 2000 epochs, the loss of the half-V (0.119) is worse than
the flat line's (0.052), so it slowly turns itself on everywhere and becomes
that same flat line.

## 3. A ReLU layer: width 2, depth 2

Two ReLU neurons side by side (a layer of **width 2**), added up by an
output neuron (**depth 2**: hidden layer + output layer):

    h1 = ReLU(w1*u + b1)          one neuron for the right arm
    h2 = ReLU(w2*u + b2)          one for the left arm
    y  = v1*h1 + v2*h2 + c

**Backpropagation** is the chain rule, starting at the loss and working back
one layer at a time, reusing what was already computed:

    dL/dy  = (2/N) * (y - t)                      for each point
    dL/dv1 = Σ dL/dy * h1         dL/dc = Σ dL/dy
    dL/dz1 = dL/dy * v1 * ReLU'(z1)               (back through the output weight, then the ReLU)
    dL/dw1 = Σ dL/dz1 * u         dL/db1 = Σ dL/dz1
    (same for neuron 2)

Then every weight takes a gradient descent step. After 2000 epochs
(`fit_v.py`), the loss is 0.0005 (100 times lower than the line) and the
fit is the V: the neurons switch on at x ≈ 60, with slopes of +1.99 and
-1.99. Each neuron learned one arm, and the output neuron added them.

This is the same idea the finger-counting CNN uses, just bigger: many ReLU
neurons, weights found by backpropagation and gradient descent.
