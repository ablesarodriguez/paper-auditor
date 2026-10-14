# Review of: ADAM: A METHOD FOR STOCHASTIC OPTIMIZATION

This report does what a referee does. First it reads the paper: what it claims, whether its numbers agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what it gives. Then it tries to recompute the results that can be recomputed.

## Key findings

- **Major concern:** The theoretical analysis (Theorem 4.1) assumes a decaying learning rate α_t ∝ t^{-1/2} and a decaying first-moment coefficient β_{1,t} = β₁ λ^{t-1}, but the presented algorithm (Algorithm 1) uses constant β₁, β₂ and …
- **Major concern:** The derivation of the expected second moment (Equation 3–4) introduces an undefined term ζ and uses β₁ in the explanation of the second-moment bias, creating confusion between the two decay rates.

*Each point is detailed below with its evidence.*

## Summary of the paper

The paper introduces Adam, a first-order stochastic optimization algorithm that maintains exponential moving averages of the gradient (first moment) and the squared gradient (second raw moment) with bias correction for initialization. It combines the advantages of AdaGrad (handling sparse gradients) and RMSProp (handling non-stationary objectives), is invariant to diagonal rescaling of gradients, and has low memory requirements. The authors provide a theoretical regret bound of O(√T) in the online convex optimization framework, comparable to the best known results. Empirical evaluations on logistic regression, multilayer perceptrons, and convolutional networks show Adam performs favorably against several baselines. An extension, AdaMax, based on the infinity norm, is also derived.

## Do the paper's numbers agree with each other?

No reported results were found that can be checked against other numbers the paper prints (an average or total in a table, a number of the abstract in the body, a percentage and its counts, a ratio and its terms).

## Major concerns

**1. The theoretical analysis (Theorem 4.1) assumes a decaying learning rate α_t ∝ t^{-1/2} and a decaying first-moment coefficient β_{1,t} = β₁ λ^{t-1}, but the presented algorithm (Algorithm 1) uses constant β₁, β₂ and constant α. The theorem therefore does not directly apply to the algorithm as written.** (soundness)

> Our following theorem holds when the learning rate α_t is decaying at a rate of t^-frac12 and first moment running average coefficient β_1,t decay exponentially with λ, that is typically close to 1, e.g. 1 - 10^-8.

Suggested: Either modify the algorithm to match the theoretical assumptions (e.g., schedule β₁ and α) or re-state the theorem for the constant-parameter version used in experiments.

**2. The derivation of the expected second moment (Equation 3–4) introduces an undefined term ζ and uses β₁ in the explanation of the second-moment bias, creating confusion between the two decay rates.** (clarity)

> where zeta = 0 if the true second moment E[g_i^2] is stationary; otherwise zeta can be kept small since the exponential decay rate β_1 can (and should) be chosen such that the exponential moving average assigns small weights to gradients too far in the past.

Suggested: Clarify the role of ζ, use β₂ consistently for the second moment, and ensure the bias-correction derivation is self-contained and notationally clean.

## Minor concerns

**1. The experimental section reports only single-run curves without error bars, random seeds, or number of repetitions, making it impossible to assess variability or statistical significance of the claimed improvements.** (evidence)

> Experiments in this work were partly carried out on the Dutch national e-infrastructure with the support of SURF Foundation.

Suggested: Report results over multiple random seeds with error bars or confidence intervals, and specify the software/hardware environment precisely.

**2. The paper claims hyperparameters 'typically require little tuning' but also states that they are 'searched over a dense grid and the results are reported using the best hyper-parameter setting', which contradicts the claim of little tuning.** (consistency)

> The hyper-parameters have intuitive interpretations and typically require little tuning.

Suggested: Either demonstrate robustness by showing performance across a range of hyperparameters without extensive search, or temper the claim about little tuning.

**3. The paper does not discuss limitations of the method (e.g., sensitivity to hyperparameters in non-convex settings, lack of convergence guarantees for non-convex objectives, or comparison with more recent adaptive methods).** (completeness)

> Overall, we found Adam to be robust and well-suited to a wide range of non-convex optimization problems in the field machine learning.

Suggested: Add a dedicated limitations section acknowledging where Adam may underperform or where theoretical guarantees do not extend.

## Concerns raised and withdrawn

Each concern was argued against before being kept. These were withdrawn, either because a passage of the paper answers them or because a second reading found them not to hold:

- ~~The AdaMax derivation parameterizes the decay as β₂^p and then takes p → ∞, but β₂^p → 0 for any β₂ ∈ [0,1), making the limit degenerate and the connection to the original β₂ unclear.~~ Two models reading the paper again both found: The referee claims the limit pto∞ is degenerate because β_2^pto0, but the paper derives a well-defined, non-degenerate limit (Equation 11) that yields the simple recursive formula u_t = max(β_2 u_t-1, |g_t|).

## Strengths

- The initialization bias correction for the exponential moving averages is well motivated and derived, addressing a known issue when decay rates are close to 1. ("In algorithm 1 we therefore divide by this term to correct the initialization bias.")
- The update rule is invariant to the scale of the gradients, which is a desirable property for optimization across different parameterizations. ("Δ_t is also invariant to the scale of the gradients; rescaling the gradients g with factor c will scale m̂_t with a factor c and v̂_t with a factor c², which ca")
- A theoretical regret bound is provided for the online convex setting, showing average regret converges to zero at rate O(1/√T). ("Adam achieves the following guarantee, for all T ≥ 1. R(T)/T = O(1/√T)")
- The AdaMax variant yields a simple and stable algorithm using the infinity norm, with a particularly clean recursive update. ("In the special case where we let p → ∞, a surprisingly simple and stable algorithm emerges; see algorithm 2.")

## Can it be reproduced from what the paper gives?

| | Requirement | Evidence in the paper |
| --- | --- | --- |
| No | Data available or fully described | No mention of data availability or detailed dataset descriptions beyond names (MNIST, IMDB, CIFAR-10). |
| No | Code available | No code repository or supplementary material is referenced. |
| Yes | Method described fully enough to implement | Pseudocode for both Adam and AdaMax is complete and unambiguous. ("Algorithm 1: Adam, our proposed algorithm for stochastic optimization. See section 2 for details...") |
| Yes | Parameters and settings given | Default hyperparameters are explicitly stated for both algorithms. |
| Partly | Hardware and software environment given | Only a high-level compute infrastructure is mentioned; no software frameworks, GPU models, or library versions. ("Experiments in this work were partly carried out on the Dutch national e-infrastructure with the support of SURF Foundation.") |
| No | Randomness controlled (seeds, repetitions) | No random seeds, number of runs, or variance control mentioned. |
| No | Variability reported (error bars, repeated runs) | Figures show single curves per method; no error bars or statistical measures. |
| Partly | Comparisons or baselines adequate | Several relevant baselines are included, but no statistical comparison and some baselines (e.g., SFO) are not standard for the settings tested. ("We compare Adam to accelerated SGD with Nesterov momentum and Adagrad... RMSProp... AdaDelta... SFO") |
| Yes | Metrics defined | Training cost and regret are clearly defined. |
| No | Limitations discussed | No explicit limitations section; conclusion only states robustness. |

## How it stands against related work

The paper introduces the foundational Adam algorithm, which is now a standard baseline in deep learning optimization. The first result shows direct algorithmic extensions, while the second confirms its established position in the literature. The snippets do not reveal the specific theoretical contributions (e.g., the O(√T) regret bound or the AdaMax variant), so the novelty of the analysis components cannot be fully judged from these results alone.

| Related work found | Year | How it relates | Cited by the paper |
| --- | --- | --- | --- |
| [A modification of adaptive moment estimation (adam) for machine learning](https://www.aimsciences.org/article/doi/10.3934/jimo.2024014) |  | builds on it: This work proposes a modification of the Adam optimizer for machine learning, directly extending the algorithm introduced in the paper under review. | **Not found in the paper** |
| [TOWARDS GUIDED DESCENT: OPTIMIZATION ALGORITHMS FOR TRAINING NEURAL NETWORKS AT SCALE](https://arxiv.org/html/2512.18373v1) | 2025 | same problem: This work discusses the same problem of stochastic optimization for neural networks and explicitly describes Adam as the combination of AdaGrad and RMSProp, confirming the paper's central motivation. | Later than the paper |

Found by web search for: *adaptive learning rate stochastic gradient descent first second moment estimation bias correction*; *exponential moving average gradient squared gradient bias correction stochastic optimization*; *adam optimizer adaptive moment estimation stochastic gradient descent*; *adagrad rmsprop combination adaptive learning rate diagonal rescaling invariance*. The works were judged from their titles and search snippets, not read. A year is given only when the work's address carries it; a work with no year may also be later than the paper (2014). "Not found" means the work's full title does not appear in the paper's text.

## The figures, as read from the images

Each figure was cut out of the PDF and described by a vision model, so that the review is not limited to captions. These are descriptions, not measurements: values read off a plot are approximate.

<details>
<summary>4 figure(s) described</summary>

- **Figure 1.** This figure contains two line graphs side by side, each showing the training cost (negative log likelihood) over iterations for logistic regression on different datasets. ### Left Panel: MNIST Logistic Regression - **Title**: "MNIST Logistic Regression" - **X-axis**: "iterations over entire dataset" with tick marks at 0, 5, 10, 15, 20, 25, 30, 35, 40, 45. - **Y-axis**: "training cost" with tick marks at 0.2, 0.3, 0.4, 0.5, 0.6, 0.7. - **Legend**: Three lines labeled "AdaGrad" (blue), "SGDNesterov" (green), and "Adam" (red). - **Trend**: All three lines start near 0.7 and decrease over iterations. AdaGrad (blue) drops fastest initially, followed by Adam (red), then SGDNesterov (green), with all converging to a low cost (~0.2) by iteration 45. ### Right Panel: IMDB BoW feature Logistic Regression - **Title**: "IMDB BoW feature Logistic Regression" - **X-axis**: "iterations over entire dataset" with tick marks at 0, 20, 40, 60, 80, 100, 120, 140, 160. - **Y-axis**: "training cost" with tick marks at 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50. - **Legend**: Four lines labeled "Adagrad+dropout" (blue), "RMSProp+dropout" (red), "SGDNesterov+dropout" (green), and "Adam+dropout" (cyan). - **Trend**: All lines start near 0.5 and decrease over iterations. RMSProp+dropout (red
- **Figure 2.** This figure consists of two panels labeled (a) and (b), both showing training cost curves for different optimization algorithms applied to multilayer neural networks on MNIST images. Panel (a) is titled "MNIST Multilayer Neural Network + dropout" and plots "training cost" on the y-axis (logarithmic scale, ranging from 10^-2 to 10^1) against "iterations over entire dataset" on the x-axis (ranging from 0 to 200). The legend lists six algorithms: AdaGrad (blue line), RMSProp (green line), SGDNesterov (red line), AdaDelta (cyan line), Adam (pink line). The curves show training cost decreasing over iterations, with all algorithms converging to similar low costs by 200 iterations. Panel (b) is titled "MNIST Multilayer Neural Networks" and has two subplots. The top subplot is labeled "MNIST Multilayer Neural Networks" and plots "training cost" on the y-axis (logarithmic scale, ranging from 10^-2 to 10^1) against "iterations over entire dataset" on the x-axis (ranging from 0 to 20). The legend shows SFO (blue line) and Adam (green line). The bottom subplot is also labeled "MNIST Multilayer Neural Networks" and plots "training cost" on the y-axis (logarithmic scale, ranging from 10^-2 to 10^1) against "normalized weight" on the x-axis (ranging from 0 to 1). The legend again shows SFO (blue line) and Adam (green line). In both subplots of (b), the SFO and Adam curves show training cost decreasing over iterations/normalized weight, with SFO starting higher but converging similarly to Adam. The main text below the figure reads: "Figure 2: Training of multilayer neural networks on MNIST images. (a) Neural networks using dropout stochastic regularization. (b) Neural networks with deterministic cost function. We compare with the sum-of-functions (SFO) optimizer (Sohl-Dickstein et al
- **Figure 3.** This figure consists of two line graphs side by side, both titled "CIFAR10 ConvNet." ### Left Panel: - **Title**: "CIFAR10 ConvNet First 3 Epoches" (note: "Epoches" is likely a typo for "Epochs"). - **X-axis**: "iterations over entire dataset" with tick marks at 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0. - **Y-axis**: "training cost" with tick marks at 2.0, 3.0 (no explicit lower limit shown, but the lines start above 2.0). - **Legend**: Lists six optimization methods: - AdaGrad (blue line) - AdaGrad+dropout (green line) - SGDNesterov (red line) - SGDNesterov+dropout (pink line) - Adam (yellow line) - Adam+dropout (purple line) - **Trend**: All six lines start at similar high training costs (around 2.5–3.0) and decrease as iterations increase, with all methods converging toward lower costs (approaching 1.0 by the end of 3 epochs). ### Right Panel: - **Title**: "CIFAR10 ConvNet" (no "First 3 Epoches" here). - **X-axis**: "iterations over entire dataset" with tick marks at 0, 5, 10, 15, 20, 25, 30, 35, 40, 45. - **Y-axis**: "training cost" with a logarithmic scale, tick marks labeled as 10⁻⁴, 10⁻³, 10⁻², 10⁻¹, 10⁰, 10¹, 10² (note: the axis label is "training cost," but the values are in scientific notation). - **Legend**: Same six
- **Figure 4.** This figure consists of two main panels labeled (a) and (b), each containing four subplots arranged in a 2x2 grid. ### Panel (a): after 10 epochs - **Top row (β₁=0)**: Left subplot (β₂=0.99) and right subplot (β₂=0.9999) show loss curves. The x-axis is labeled "log₁₀(α)" (stepsize α on a logarithmic scale), and the y-axis is "Loss". The red line (bias-correction terms) and green line (no bias correction) are plotted. - **Bottom row (β₁=0.9)**: Left subplot (β₂=0.99) and right subplot (β₂=0.9999) also show loss curves with the same axes and line colors. ### Panel (b): after 100 epochs - **Top row (β₁=0)**: Left subplot (β₂=0.99) and right subplot (β₂=0.9999) show loss curves with the same axes and line colors. - **Bottom row (β₁=0.9)**: Left subplot (β₂=0.99) and right subplot (β₂=0.9999) show loss curves with the same axes and line colors. ### Labels and Values: - Subplot titles: "β₁=0" (top row), "β₁=0.9" (bottom row); "β₂=0.99", "β₂=0.999", "β₂=0.9999" (column labels for β₂). - X-axis label: "log₁₀(α)" (across all subplots). - Y-axis label: "Loss" (across all subplots). - Figure caption: "Figure 4: Effect of bias-correction terms (red line) versus no bias correction terms (green line) after 10 epochs (left) and 100 epochs (right) on the loss (y

</details>

## Questions for the authors

1. The theoretical regret bound assumes decaying β_{1,t} and α_t, but the algorithm uses constant values. How should practitioners reconcile this discrepancy, and does the bound hold for the constant-parameter version?
2. In the AdaMax derivation, the decay term is written as β₂^p and then p → ∞ is taken. Since β₂^p → 0, the effective memory horizon collapses; can you clarify the intended parameterization and the limit?
3. The experiments report only single-run trajectories. Can you provide results averaged over multiple random seeds with error bars to support the claim that Adam 'consistently outperforms other methods'?
4. The paper states hyperparameters 'typically require little tuning' but also describes a dense grid search. Can you show performance across a reasonable hyperparameter range without per-dataset tuning?
5. The proof in the appendix contains several undefined symbols (e.g., ζ, γ, λ in the regret bound) and apparent typographical errors. Can you provide a corrected, self-contained version of the theoretical analysis?

> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept only when the passage it quotes is in the paper and no other passage of the paper answers it. The number checks are computed.

