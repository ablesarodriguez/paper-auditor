# Review of: Generative Adversarial Nets

This report does what a referee does. First it reads the paper: what it claims, whether its numbers agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what it gives. Then it tries to recompute the results that can be recomputed.

## Key findings

- **Major concern:** The convergence proof for Algorithm 1 assumes the discriminator reaches its optimum given the current generator at each step, but the practical algorithm uses only k=1 step of D per G update, explicitly acknowledging …
- **Major concern:** The quantitative evaluation relies on a Parzen window log-likelihood estimate that the authors themselves describe as having high variance and performing poorly in high-dimensional spaces, casting doubt on the …

*Each point is detailed below with its evidence.*

## Summary of the paper

The paper introduces a generative adversarial network (GAN) framework where a generator network G and a discriminator network D are trained simultaneously in a minimax game. The authors prove that in the non-parametric limit the unique global optimum occurs when the generator's distribution matches the data distribution, and they propose a practical stochastic gradient algorithm that alternates updates of D and G. Experiments on MNIST, the Toronto Face Database, and CIFAR-10 show competitive log-likelihood estimates (using a Parzen window method) and qualitatively sharp samples, demonstrating the potential of the adversarial approach without requiring Markov chains or approximate inference.

## Do the paper's numbers agree with each other?

No reported results were found that can be checked against other numbers the paper prints (an average or total in a table, a number of the abstract in the body, a percentage and its counts, a ratio and its terms).

## Major concerns

**1. The convergence proof for Algorithm 1 assumes the discriminator reaches its optimum given the current generator at each step, but the practical algorithm uses only k=1 step of D per G update, explicitly acknowledging that optimizing D to completion is computationally prohibitive. This gap between the theoretical assumption and the implemented procedure undermines the claimed convergence guarantee.** (soundness)

> Optimizing D to completion in the inner loop of training is computationally prohibitive, and on finite datasets would result in overfitting. Instead, we alternate between k steps of optimizing D and one step of optimizing G.

Suggested: Either provide a convergence analysis for the actual k=1 update scheme, or discuss why the approximation is expected to work in practice despite the theoretical gap.

**2. The quantitative evaluation relies on a Parzen window log-likelihood estimate that the authors themselves describe as having high variance and performing poorly in high-dimensional spaces, casting doubt on the reliability of the reported numbers (e.g., 225 ± 2 on MNIST).** (evidence)

> This method of estimating the likelihood has somewhat high variance and does not perform well in high dimensional spaces but it is the best method available to our knowledge.

Suggested: Acknowledge the limitations of the evaluation metric more prominently, and consider supplementing with other evaluation methods (e.g., visual quality assessments, downstream task performance) to strengthen the evidence.

## Minor concerns

**1. Key hyperparameters (learning rate, momentum value, network architectures, minibatch size m, noise prior details) are not provided in the paper; the reader is referred to an external GitHub repository. This hinders reproducibility without accessing the external link.** (completeness)

> All code and hyperparameters available at http://www.github.com/goodfeli/adversarial

Suggested: Include a table of the main hyperparameters and architectural choices in the paper itself.

**2. The paper mentions a failure mode called the "Helvetica scenario" where the generator collapses diversity, but does not analyze its causes, frequency, or mitigation strategies beyond vague synchronization advice.** (clarity)

> in order to avoid ``the Helvetica scenario'' in which G collapses too many values of z to the same value of x to have enough diversity to model p_data

Suggested: Provide a more thorough discussion of mode collapse, including empirical observations or theoretical insights, and suggest concrete techniques to detect and prevent it.

**3. The paper does not report any control of randomness (random seeds, multiple training runs with different initializations) for the generator training, so the variability of the qualitative samples and the stability of the training process are unknown.** (completeness)

> Samples are fair random draws, not cherry-picked.

Suggested: Report results over multiple random seeds or at least state the seed used, and discuss training stability.

## Strengths

- The paper proposes a novel adversarial framework for generative modeling that avoids intractable probabilistic computations, Markov chains, and approximate inference networks, relying only on backpropagation and forward propagation. ("We propose a new framework for estimating generative models via an adversarial process, in which we simultaneously train two models: a generative model G that c")
- A theoretical analysis proves that the minimax game has a unique global optimum where the generator perfectly recovers the data distribution, and the discriminator outputs 1/2 everywhere. ("The global minimum of the virtual training criterion C(G) is achieved if and only if p_g=p_data. At that point, C(G) achieves the value -log 4.")
- The practical training algorithm (Algorithm 1) is clearly specified, using minibatch stochastic gradient descent with a simple alternating update scheme (k steps of D per step of G) and leverages piecewise linear units and dropout. ("The number of steps to apply to the discriminator, k, is a hyperparameter. We used k=1, the least expensive option, in our experiments.")

## Can it be reproduced from what the paper gives?

| | Requirement | Evidence in the paper |
| --- | --- | --- |
| Partly | Data available or fully described | Standard datasets are named but preprocessing details (e.g., normalization, splits) are not described. |
| Yes | Code available | A URL is provided in a footnote. ("All code and hyperparameters available at http://www.github.com/goodfeli/adversarial") |
| Partly | Method described fully enough to implement | Algorithm 1 gives the update structure, but network architectures, activation choices per layer, learning rate, momentum, and minibatch size m are not fully specified in the text. ("The number of steps to apply to the discriminator, k, is a hyperparameter. We used k=1, the least expensive option, in our experiments.") |
| Partly | Parameters and settings given | Some settings are mentioned, but many key hyperparameters are omitted and deferred to the external repository. ("The generator nets used a mixture of rectifier linear activations and sigmoid activations, while the discriminator net used maxout activatio") |
| No | Hardware and software environment given | No information about hardware, software frameworks, or runtime is provided. |
| No | Randomness controlled (seeds, repetitions) | No mention of random seeds, multiple runs, or averaging over initializations. |
| Partly | Variability reported (error bars, repeated runs) | Standard errors are reported for the Parzen log-likelihood estimates, but no variability is reported for the qualitative samples or for the training process itself. ("Adversarial nets \| 225 ± 2 \| 2057 ± 26") |
| Partly | Comparisons or baselines adequate | Comparisons are made to three prior models on two datasets, but the table is limited and the evaluation metric is acknowledged as flawed. ("DBN \| 138 ± 2 \| 1909 ± 66 \|") |
| Yes | Metrics defined | The Parzen window log-likelihood estimation procedure is described and referenced. ("We estimate probability of the test set data under p_g by fitting a Gaussian Parzen window to the samples generated with G and reporting the") |
| Yes | Limitations discussed | An explicit 'Advantages and disadvantages' section discusses limitations including lack of explicit density, synchronization requirements, and mode collapse. ("The disadvantages are primarily that there is no explicit representation of p_g(bmx), and that D must be synchronized well with G during tra") |

## How it stands against related work

The paper appears to be the foundational work introducing the GAN framework, its minimax game formulation, and the alternating stochastic gradient algorithm. The search results consist entirely of later extensions, theoretical analyses (game theory, SDE modeling), and stabilization techniques that explicitly build upon or formalize this original framework. No earlier works proposing the same adversarial generative approach were found in the snippets. The exact novelty of the log-likelihood evaluation method (Parzen window) and the specific non-parametric convergence proof could not be fully judged from the snippets alone.

| Related work found | Year | How it relates | Cited by the paper |
| --- | --- | --- | --- |
| [A Multi-Player Minimax Game for Generative Adversarial Networks](http://ieeexplore.ieee.org/document/9102779) |  | builds on it: Extends the original two-player minimax GAN framework to a multi-player game with multiple discriminators to improve diversity and decision boundaries. | **Not found in the paper** |
| [Game of GANs: Game-Theoretical Models for Generative ...](https://arxiv.org/abs/2106.06976) | 2021 | same method: Models GAN training as a game-theoretic zero-sum game between two networks seeking a Nash equilibrium, formalizing the adversarial minimax structure. | Later than the paper |
| [game-theoretical models for generative adversarial networks](https://dl.acm.org/doi/abs/10.1007/s10462-023-10395-6) |  | same method: Reviews game-theoretic models for GANs, analyzing how the minimax game formulation addresses training challenges like mode collapse and instability. | **Not found in the paper** |
| [Adaptive Weighted Discriminator for Training Generative Adversarial Networks](https://pmc.ncbi.nlm.nih.gov/articles/PMC8963430) |  | builds on it: Proposes an adaptive weighted discriminator to stabilize GAN training, addressing instability and mode collapse inherent in the original adversarial framework. | **Not found in the paper** |
| [Enhance Diffusion to Improve Robust Generalization](https://jsycsjh.github.io/assets/publications/2023_diffusion/kdd_adversarial_training.pdf) |  | same method: Models GAN training dynamics via stochastic differential equations (SDEs), treating the alternating gradient updates as a continuous-time min-max game. | **Not found in the paper** |

Found by web search for: *generative adversarial network minimax game generator discriminator*; *adversarial training generative model stochastic gradient alternating updates*; *generative adversarial network image generation MNIST CIFAR-10*; *adversarial learning generative models game theory*. The works were judged from their titles and search snippets, not read. A year is given only when the work's address carries it; a work with no year may also be later than the paper (2014). "Not found" means the work's full title does not appear in the paper's text.

## The figures, as read from the images

Each figure was cut out of the PDF and described by a vision model, so that the review is not limited to captions. These are descriptions, not measurements: values read off a plot are approximate.

<details>
<summary>3 figure(s) described</summary>

- **Figure 1.** This is a scientific figure consisting of four panels labeled (a), (b), (c), and (d), arranged horizontally. The figure illustrates the training process of generative adversarial networks (GANs), focusing on the discriminative distribution (D) and generative distribution (G). ### Axes and Domains: - **Vertical axis**: Represents probability density (implied, as the curves are probability distributions). - **Horizontal axis**: Labeled "x" (data space) and "z" (latent space, lower horizontal line). The lower horizontal line is the domain of z (uniformly sampled), and the upper horizontal line is part of the domain of x (data space). ### Panels and Curves: - **Panel (a)**: - Black dotted line: Data generating distribution \( p_x \) (data samples). - Green solid line: Generative distribution \( p_g \) (G’s output, non-uniform). - Blue dashed line: Discriminative distribution \( D \) (initially similar to \( p_g \), labeled as a "partially accurate classifier"). - Upward arrows: Indicate the mapping \( x = G(z) \), showing how G transforms z into x, imposing \( p_g \) on samples. - **Panel (b)**: - Black dotted line: \( p_x \) (data distribution). - Green solid line: \( p_g \) (G’s output, now closer to \( p_x \)). - Blue dashed line: \( D \) (updated to better discriminate between \( p_x \) and \( p_g \)). - **Panel (c)**: - Black dotted line: \( p_x \) (data distribution). - Green solid line: \( p_g \) (G’s output, further aligned with \( p_x \)). - Blue dashed line: \( D \) (continues to adjust). - **Panel (d)**: - Black dotted line: \( p_x \) (data distribution). - Green solid line: \( p_g \) (
- **Figure 2.** This figure is a 2x2 grid of panels (a), (b), (c), and (d), each showing visualizations of samples generated by a model, with the rightmost column in each panel displaying the nearest training example to the generated sample. ### Panel (a): - **Content**: A 4x4 grid of handwritten digits (0-9) on black backgrounds. - **Labels**: The top row has digits "7", "3", "9", "3", "9", "9"; the second row "1", "1", "0", "6", "0", "0"; the third row "0", "1", "9", "1", "2", "2"; the fourth row "6", "8", "2", "0", "8", "8". - **Structure**: Each cell contains a single digit, with some digits (e.g., the last digit in the top row, last digit in the fourth row) highlighted with a yellow border. ### Panel (b): - **Content**: A 5x4 grid of grayscale facial images (neutral expressions, varying lighting). - **Labels**: No explicit numerical labels, but the rightmost column (yellow-bordered) shows the nearest training example to the generated sample in the same row. ### Panel (c): - **Content**: A 6x6 grid of small, colorful, abstract or natural scenes (e.g., landscapes, animals, textures). - **Labels**: The rightmost column (yellow-bordered) shows the nearest training example to the generated sample in the same row. ### Panel (d): - **Content**: A 6x6 grid of small, colorful, natural scenes (e.g., animals, landscapes, textures). - **Labels**: The rightmost column (yellow-bordered) shows the nearest training example to the generated sample in the same row. ### Figure Caption: "Figure 2: Visualization of samples from the model. Rightmost column shows the nearest training example of the neighboring sample, in order to demonstrate that the model has not memorized the training set. Samples are fair random draws,
- **Figure 3.** This is a figure consisting of two horizontal panels, each containing a sequence of black-and-white digit images on a dark background. **Left panel**: Displays digits "1", "1", "1", "5", "5", "5", "5", "5" (from left to right). **Right panel**: Displays digits "7", "7", "9", "9", "9", "9", "1", "1", "1", "1" (from left to right). Below the panels, the caption reads: "Figure 3: Digits obtained by linearly interpolating between coordinates in z space of the full model." The main structure is two side-by-side rows of digit images, with the left row showing a progression from "1" to "5" and the right row from "7" to "1". The digits are stylized, resembling handwritten or machine-generated characters. No numerical values or axes labels are present other than the caption.

</details>

## Questions for the authors

1. How sensitive are the reported log-likelihood numbers to the choice of Parzen window bandwidth σ, and would the ranking of models change with a different evaluation method?
2. Have you observed the 'Helvetica scenario' (mode collapse) in practice, and if so, what practical heuristics (beyond adjusting k) have you found effective to prevent it?
3. Would the theoretical convergence guarantee hold if the discriminator is updated with a fixed number of gradient steps (k=1) rather than to optimality, and can you provide a bound on the deviation from the optimal discriminator?

> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept only when the passage it quotes is in the paper and no other passage of the paper answers it. The number checks are computed.

