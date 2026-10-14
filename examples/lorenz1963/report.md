# Review of: Deterministic Nonperiodic Flow

This report does what a referee does. First it reads the paper: what it claims, whether its numbers agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what it gives. Then it tries to recompute the results that can be recomputed.

## Key findings

- **Major concern:** The claim that 'all solutions are unstable, and almost all of them are nonperiodic' is based on a single numerical integration from one initial condition (0,1,0) and one parameter set (σ=10, r=28, b=8/3).
- **Numbers consistent:** all 2 cross-checks of the paper's numbers agree.

*Each point is detailed below with its evidence.*

## Summary of the paper

The paper introduces a mathematical framework for deterministic nonperiodic flow using finite systems of ordinary differential equations representing forced dissipative hydrodynamic systems. It proves that bounded nonperiodic central trajectories are unstable, implying that small errors in initial conditions grow over time, making long-range prediction impossible. A three-equation convection model is numerically integrated using a double-approximation scheme, yielding a nonperiodic solution. The author argues that all solutions of this model are unstable and almost all are nonperiodic, and discusses implications for weather forecasting, concluding that precise very-long-range forecasting is impossible due to inevitable observational errors.

## Do the paper's numbers agree with each other?

2 results printed in the paper were checked against other numbers it prints: 2 relations between numbers pointed out by the model. All arithmetic is done by code. **0 do not agree.**

<details>
<summary>The 2 that agree</summary>

| | What is checked | Arithmetic | Result | Paper | Where |
| --- | --- | --- | --- | --- | --- |
| ✓ | Check if the critical Rayleigh number r = 470/19 equals 24.74 as stated in the paper | `470/19` | 24.7368 | 24.74 | "The critical Rayleigh number for instability of steady convection then occurs when r = 470/19 = 24.74." |
| ✓ | Check if the steady convection Z value 270 corresponds to Z = r-1 with r=28, multiplied by 10 | `(28-1)*10` | 270 | 270 | "The states of steady convection would appear as 0084, 0084, 0270 and -0084, -0084, 0270" |

</details>

Each printed input is taken to stand for anything that rounds to it, so rounding is not reported as a mismatch. A mismatch in a check the model set up is reported only when a second model agrees the check compares the right quantities.

## Major concerns

**1. The claim that 'all solutions are unstable, and almost all of them are nonperiodic' is based on a single numerical integration from one initial condition (0,1,0) and one parameter set (σ=10, r=28, b=8/3). The periodic solutions are asserted to exist analytically but their instability is not numerically demonstrated.** (evidence)

> For initial conditions we have chosen a slight departure from the state of no convection, namely (0,1,0). ... All solutions, and in particular the periodic solutions, are found to be unstable. The remaining solutions therefore cannot in general approach the periodic solutions asymptotically, and so are nonperiodic.

Suggested: The authors should either provide numerical evidence for multiple initial conditions and parameter values, or clearly state that the generality of the claim is a conjecture supported only by the single computed trajectory and the theoretical argument for periodic solutions.

## Minor concerns

**1. The paper dismisses the possibility of stable noncentral nonperiodic trajectories as 'not characteristic of real hydrodynamical phenomena' without proof, yet the claim that all nonperiodic trajectories are effectively unstable rests on this dismissal.** (soundness)

> The possibility of a nonperiodic noncentral trajectory which is stable but not uniformly stable still exists. To the writer, at least, such trajectories, although possible on paper, do not seem characteristic of real hydrodynamical phenomena.

Suggested: Either provide a dynamical-systems argument why such trajectories are unlikely in forced dissipative systems, or weaken the conclusion to apply only to central trajectories and to noncentral trajectories that are uniformly stable.

**2. The printed tables multiply values by 10 and truncate to integers, losing precision and making it difficult to verify the numerical solution from the published data.** (clarity)

> In the printed output (but not in the computations) the values of X, Y, and Z are multiplied by ten, and then only those figures to the left of the decimal point are printed.

Suggested: Note that the full-precision values are available upon request, or provide a sample of the untruncated output.

## Concerns raised and withdrawn

Each concern was argued against before being kept. These were withdrawn, either because a passage of the paper answers them or because a second reading found them not to hold:

- ~~The double-approximation procedure uses ambiguous notation: P_((n+1)) in equation (13) could refer to the forward-difference estimate (9) or the centered-difference estimate (10), and the derivation of equation (14) from (9) and (10) is not clearly explained.~~ Two models reading the paper again both found: The concern misidentifies equation (10) as the centered-difference estimate; the paper defines P_((n+1)) using the forward-difference estimate (9) and the centered-difference procedure is given separately in equation (12).
- ~~The time step Δt used in the numerical integration is never specified, making it impossible to assess the accuracy of the integration or to reproduce the results.~~ Two models reading the paper again both found: The paper specifies the dimensionless time step Δτ=0.01, contrary to the referee's claim that it is never specified.

## Strengths

- A key theoretical result shows that any stable central trajectory must be quasi-periodic; therefore a nonperiodic central trajectory is necessarily unstable, linking nonperiodicity directly to practical unpredictability. ("It follows immediately that a stable central trajectory is quasi-periodic, or, equivalently, that a nonperiodic central trajectory is unstable.")
- The double-approximation numerical procedure is presented as an improvement over forward and centered differences, preserving the deterministic nature of the equations while providing a practical integration scheme. ("A procedure which largely overcomes the disadvantages of both the forward-difference and centered-difference procedures is the double-approximation procedure, d")
- The paper explicitly connects the mathematical instability result to the real-world problem of weather prediction, acknowledging that observational errors make precise long-range forecasting impossible. ("If, then, there is any error whatever in observing the present state—and in any real system such errors seem inevitable—an acceptable prediction of an instantan")
- The conclusion honestly discusses the limitations of applying the idealized model to the atmosphere, noting that the atmosphere may not be deterministic or finite and that 'very-long-range' is not quantified. ("One does not usually regard the atmosphere as either deterministic or finite, and the lack of periodicity is not a mathematical certainty, since the atmosphere ")

## Can it be reproduced from what the paper gives?

| | Requirement | Evidence in the paper |
| --- | --- | --- |
| Partly | Data available or fully described | Tables 1 and 2 are provided but with truncated precision; full computational data not published. ("In the printed output (but not in the computations) the values of X, Y, and Z are multiplied by ten, and then only those figures to the left") |
| No | Code available | No code is provided; the paper describes the algorithm in prose and equations only. |
| Partly | Method described fully enough to implement | The double-approximation scheme is described but the notation for intermediate steps is ambiguous, hindering exact implementation. ("A procedure which largely overcomes the disadvantages of both the forward-difference and centered-difference procedures is the double-approx") |
| Partly | Parameters and settings given | Model parameters and initial condition are given, but the integration time step Δt is not specified. ("Following Saltzman (1962), we shall let σ = 10 and a^2 = 1/2, so that b = 8/3. The critical Rayleigh number for instability of steady convec") |
| Yes | Hardware and software environment given | The computer used is identified. ("The computations have been performed on a Royal McBee LGP-30 electronic computing machine.") |
| Not applicable | Randomness controlled (seeds, repetitions) | The system is deterministic; no random numbers are used. ("finite systems of deterministic ordinary differential equations") |
| No | Variability reported (error bars, repeated runs) | Only a single trajectory is shown; no variation over initial conditions, parameters, or step sizes is reported. ("For initial conditions we have chosen a slight departure from the state of no convection, namely (0,1,0).") |
| No | Comparisons or baselines adequate | No comparison with other numerical methods, analytic solutions, or alternative models is presented. |
| Partly | Metrics defined | Stability is defined qualitatively; no quantitative metric (e.g., Lyapunov exponent) is introduced. ("A trajectory P(t) will be called stable at a point P(t_1) if any other trajectory passing sufficiently close to P(t_1) at time t_1 remains c") |
| Yes | Limitations discussed | The conclusion explicitly addresses the idealizations and their relevance to the real atmosphere. ("One does not usually regard the atmosphere as either deterministic or finite, and the lack of periodicity is not a mathematical certainty, s") |

## How it stands against related work

The paper's core contribution—proving instability of bounded nonperiodic trajectories in a deterministic hydrodynamic ODE system and linking it to weather predictability limits—appears distinct from these results, which focus on numerical methods for convection rather than dynamical systems theory. The 1986 Knobloch et al. work is the closest conceptually but addresses double-diffusive convection specifically, not the general framework or prediction impossibility argument. The novelty of the 'deterministic nonperiodic flow' framework and its philosophical implication for forecasting cannot be fully judged without comparing the full mathematical proofs and the specific three-equation model against the cited convection literature.

| Related work found | Year | How it relates | Cited by the paper |
| --- | --- | --- | --- |
| [Transitions to chaos in two-dimensional double-diffusive ...](https://lcd-www.colorado.edu/~axbr9098/teach/ASTR_5410/material/Knobloch_etal86.pdf) |  | same problem: Studies transitions to chaos in double-diffusive convection using ODE models derived from fluid dynamics, directly addressing deterministic nonperiodic flow in hydrodynamic systems. | Cannot tell from the title |
| [DStreaM: A Convective Term Approximation Approach ...](https://www.mdpi.com/2227-7390/14/3/389) |  | same method: Proposes a convective term approximation scheme (DStreaM) for numerical integration of convection problems, sharing the paper's focus on approximation methods for convective flow. | Cannot tell from the title |
| [Effect of time integration scheme in the numerical ...](https://www.sciencedirect.com/science/article/pii/S0898122121003096) |  | same method: Compares time integration schemes for mixed heat convection in 2D and 3D, relevant to the paper's use of a double-approximation scheme for a three-equation convection model. | Cannot tell from the title |
| [Convergence of numerical schemes for convection ...](https://www.sciencedirect.com/science/article/pii/S2590037423000250) |  | same method: Analyzes convergence of numerical schemes for convection-diffusion models using gradient discretization, pertinent to the paper's numerical integration of a dissipative hydrodynamic system. | Cannot tell from the title |

Found by web search for: *deterministic nonperiodic flow bounded trajectories instability*; *double approximation scheme numerical integration convection model*; *double approximation scheme applied to convection model nonperiodic solutions*; *Lorenz system three equation convection model*. The works were judged from their titles and search snippets, not read. A year is given only when the work's address carries it; a work with no year may also be later than the paper (1963). "Not found" means the work's full title does not appear in the paper's text.

## The figures, as read from the images

Each figure was cut out of the PDF and described by a vision model, so that the review is not limited to captions. These are descriptions, not measurements: values read off a plot are approximate.

<details>
<summary>5 figure(s) described</summary>

- **Figure 1.** Figure 1 is a line graph showing the numerical solution of the convection equations. The x-axis is labeled "t" (time) and ranges from 0 to 2000. The y-axis is labeled "Y" and ranges from -0.000 to 0.000. There are three curves: the upper curve shows the first 1000 iterations, the middle curve shows the second 1000 iterations, and the lower curve shows the third 1000 iterations. The curves display irregular, wavy oscillations with varying amplitude and frequency, indicating the evolution of the convection variable Y over time.
- **Figure 2.** Figure 2 is a 3D phase space projection of a trajectory from the convection equations, showing the X-Y and Y-Z planes. It consists of two main panels: the upper panel displays a 3D plot with axes labeled X, Y, and Z, and the lower panel shows a 2D projection onto the Y-Z plane. In the upper panel, the trajectory forms a spiral pattern that loops around a central point labeled "C" (a state of steady convection). The spiral starts at a point labeled "C'" (a transient state) and winds around the central point, with several numbered loops (e.g., 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96
- **Figure 3.** This is a 3D plot of a spherical surface, likely representing a portion of a sphere (possibly a hemisphere), with contour lines and trajectories drawn on it. ### Axes and Labels: - The vertical axis is labeled **Z**, with tick marks at 200, 400, and a dashed line at 600 (though the topmost point is unlabeled). - The horizontal plane (the "equatorial" plane of the sphere) is labeled with **X** and **Y** axes. The X-axis ranges from -200 to 200, with tick marks at -200, -120, -80, -40, 0, 40, 80, 120, 160, 200. The Y-axis ranges from -200 to 200, with tick marks at -200, -120, -80, -40, 0, 40, 80, 120, 160, 200. ### Contour Lines and Trajectories: - **Solid curves**: These are isopleths of **X** as a function of **Y** and **Z** (within solid curves), representing the lower of two values of **X** where two values of **X** exist. They form a grid of concentric curves around the sphere, with labels at key points: -160, -120, -80, -40 (on the left side of the sphere, near the bottom), and 160 (on the right side, near the top). - **Dashed curves**: These are limiting trajectories, forming approximate surfaces for points on these trajectories. They appear as dotted lines, indicating natural boundaries of surfaces. ### Key Features: - The sphere is divided into two hemispheres by a vertical dashed line (likely the Z=0 plane). - Two small circles are drawn on the sphere: one near the bottom-left (labeled with a dashed line and a small dot), and one
- **Figure 4.** Figure 4 is a scatter plot with a single data series. The x-axis is labeled "M_n" (abscissa) and ranges from 0 to 0.5. The y-axis is labeled "M_n+1" (ordinate) and ranges from 300 to 450. The plot shows a sharp, triangular peak centered around M_n ≈ 0.25, with M_n+1 reaching a maximum of approximately 450 at this point. The data points form a dense cluster forming the peak, with values decreasing symmetrically on either side as M_n moves away from 0.25. The caption states that these are "Corresponding values of relative maximum of Z (abscissa) and subsequent relative maximum of Z (ordinate) occurring during the first 6000 iterations."
- **Figure 5.** Figure 5 is a line graph with the title "The function $M_{n+1} = 2M_n$ if $M_n < \frac{1}{2}$, $M_{n+1} = 2 - 2M_n$ if $M_n > \frac{1}{2}$, serving as an idealization of the locus of points in Fig. 4." The graph has two axes: the horizontal axis (abscissa) is labeled "0" at the left and "1" at the right, with a tick mark at "0.5" in the middle. The vertical axis (ordinate) is labeled "0" at the bottom and "1" at the top, with tick marks at "0" and "1". The graph shows a single triangular shape: it starts at the point (0, 0), rises sharply to a peak at (0.5, 1), and then falls sharply back to (1, 0). The line forming the triangle is straight and continuous. There are no additional labels, data points, or annotations visible on the graph itself, only the axes and the triangular shape.

</details>

## Questions for the authors

1. What is the time step Δt used in the numerical integration, and how was it chosen?
2. Were any other initial conditions or parameter values explored to support the claim that 'all solutions are unstable'?
3. Can the double-approximation procedure be clarified: does P_((n+1)) in equation (13) refer to the forward-difference estimate (9) or the centered-difference estimate (10)?
4. The paper dismisses noncentral stable nonperiodic trajectories as not characteristic of real hydrodynamical phenomena. What is the basis for this physical intuition?
5. How does the truncation of output values (multiplying by 10 and taking integer part) affect the interpretation of the numerical results, especially for small values?

> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept only when the passage it quotes is in the paper and no other passage of the paper answers it. The number checks are computed.

