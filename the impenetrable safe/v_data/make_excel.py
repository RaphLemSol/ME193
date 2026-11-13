"""
Build v_gradient_descent.xlsx: 5 iterations of gradient descent on m & b,
done with live Excel formulas (change the learning rate or the starting m, b
in the yellow cells and every iteration recomputes).

    python make_excel.py

Sheets:
  Linear neuron   y = m*u + b
  ReLU neuron     y = ReLU(m*u + b)
Both use u = x/100 and t = output/100 (same as fit_v.py, whose printout
should match the numbers Excel shows).
"""

from pathlib import Path

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference, ScatterChart, Series
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter as col

from fit_v import LINEAR_INIT, LR, RELU_INIT, SCALE

HERE = Path(__file__).resolve().parent
ITERS = 5
FIRST = 16                     # first data row
INPUT = PatternFill("solid", fgColor="FFF2A8")
HEAD = Font(bold=True)


def build_sheet(ws, title, relu, init):
    data = np.loadtxt(HERE / "annacode-v.tsv", delimiter="\t", skiprows=1)
    n = len(data)
    last = FIRST + n - 1

    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = ("Model: y = ReLU(m*u + b)" if relu else "Model: y = m*u + b") + \
               "    Loss: L = (1/N) * sum((y - t)^2)    Update: m <- m - lr*dL/dm,  b <- b - lr*dL/db"
    ws["A3"] = ("dL/dm = (2/N) * sum((y - t) * on * u),  dL/db = (2/N) * sum((y - t) * on),  "
                "on = 1 if m*u + b > 0 else 0" if relu else
                "dL/dm = (2/N) * sum((y - t) * u),  dL/db = (2/N) * sum(y - t)")
    ws["A4"] = "learning rate"
    ws["B4"] = LR
    ws["B4"].fill = INPUT
    ws["C4"] = "N"
    ws["D4"] = n

    # Parameter table: one row per iteration
    top = 6
    for c, h in enumerate(["iteration", "m", "b", "loss", "dL/dm", "dL/db"], start=1):
        ws.cell(top, c, h).font = HEAD
    # Per-point block for each iteration: y, y-t, (on), gradient terms
    per = ["y", "y - t", "on", "(y-t)*on", "(y-t)*on*u"] if relu else ["y", "y - t", "(y-t)*u"]
    width = len(per)
    ws.cell(FIRST - 2, 1, "x").font = HEAD
    ws.cell(FIRST - 2, 2, "output").font = HEAD
    ws.cell(FIRST - 2, 3, "u = x/100").font = HEAD
    ws.cell(FIRST - 2, 4, "t = output/100").font = HEAD
    for i, (x, y) in enumerate(data[:, 1:3]):
        r = FIRST + i
        ws.cell(r, 1, float(x))
        ws.cell(r, 2, float(y))
        ws.cell(r, 3, f"=A{r}/{SCALE:g}")
        ws.cell(r, 4, f"=B{r}/{SCALE:g}")

    for k in range(ITERS + 1):
        pr = top + 1 + k                          # this iteration's parameter row
        c0 = 6 + k * width                        # first column of its per-point block
        ws.cell(FIRST - 3, c0, f"iteration {k}").font = HEAD
        for j, h in enumerate(per):
            ws.cell(FIRST - 2, c0 + j, h).font = HEAD
        L = [col(c0 + j) for j in range(width)]
        for i in range(n):
            r = FIRST + i
            z = f"$B${pr}*C{r}+$C${pr}"
            if relu:
                ws.cell(r, c0, f"=MAX(0,{z})")
                ws.cell(r, c0 + 1, f"={L[0]}{r}-D{r}")
                ws.cell(r, c0 + 2, f"=IF({z}>0,1,0)")
                ws.cell(r, c0 + 3, f"={L[1]}{r}*{L[2]}{r}")
                ws.cell(r, c0 + 4, f"={L[3]}{r}*C{r}")
            else:
                ws.cell(r, c0, f"={z}")
                ws.cell(r, c0 + 1, f"={L[0]}{r}-D{r}")
                ws.cell(r, c0 + 2, f"={L[1]}{r}*C{r}")

        ws.cell(pr, 1, k)
        if k == 0:
            ws.cell(pr, 2, init["m"]).fill = INPUT
            ws.cell(pr, 3, init["b"]).fill = INPUT
        else:
            ws.cell(pr, 2, f"=B{pr - 1}-$B$4*E{pr - 1}")
            ws.cell(pr, 3, f"=C{pr - 1}-$B$4*F{pr - 1}")
        err = f"{L[1]}{FIRST}:{L[1]}{last}"
        ws.cell(pr, 4, f"=SUMPRODUCT({err},{err})/$D$4")
        gm = f"{L[-1]}{FIRST}:{L[-1]}{last}"
        gb = f"{L[3] if relu else L[1]}{FIRST}:{L[3] if relu else L[1]}{last}"
        ws.cell(pr, 5, f"=2*SUM({gm})/$D$4")
        ws.cell(pr, 6, f"=2*SUM({gb})/$D$4")
        for c in range(2, 7):
            ws.cell(pr, c).number_format = "0.00000"

    # Chart: the data and the fit after the last iteration
    chart = ScatterChart()
    chart.title = f"Data and fit after {ITERS} iterations"
    chart.x_axis.title = "u = x/100"
    chart.y_axis.title = "t = output/100"
    chart.style = 13
    xs = Reference(ws, min_col=3, min_row=FIRST, max_row=last)
    pts = Series(Reference(ws, min_col=4, min_row=FIRST, max_row=last), xs, title="data")
    pts.marker.symbol = "circle"
    pts.graphicalProperties.line.noFill = True
    fit = Series(Reference(ws, min_col=6 + ITERS * width, min_row=FIRST, max_row=last), xs,
                 title=f"fit (iteration {ITERS})")
    fit.marker.symbol = "dash"
    fit.graphicalProperties.line.noFill = True
    chart.series += [pts, fit]
    chart.height, chart.width = 8, 14
    ws.add_chart(chart, "H2")

    loss = LineChart()
    loss.title = "Loss vs iteration"
    loss.x_axis.title = "iteration"
    loss.y_axis.title = "loss"
    loss.add_data(Reference(ws, min_col=4, min_row=top, max_row=top + 1 + ITERS), titles_from_data=True)
    loss.set_categories(Reference(ws, min_col=1, min_row=top + 1, max_row=top + 1 + ITERS))
    loss.height, loss.width = 8, 12
    ws.add_chart(loss, "Q2")

    ws.column_dimensions["A"].width = 12
    ws.freeze_panes = ws.cell(FIRST, 1)


def main():
    wb = Workbook()
    build_sheet(wb.active, "Gradient descent on one linear neuron", False, LINEAR_INIT)
    wb.active.title = "Linear neuron"
    build_sheet(wb.create_sheet("ReLU neuron"), "Gradient descent on one ReLU neuron", True, RELU_INIT)
    out = HERE / "v_gradient_descent.xlsx"
    wb.save(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
