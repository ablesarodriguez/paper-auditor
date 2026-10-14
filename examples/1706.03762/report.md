# Review of: Attention Is All You Need

This report does what a referee does. First it reads the paper: what it claims, whether its numbers agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what it gives. Then it tries to recompute the results that can be recomputed.

## Key findings

- **Numbers that disagree:** 41.8 in the abstract and 41.0 in the body, both after "score of" in passages about the same thing (bleu, english, french, model, score).
- **Major concern:** No random seeds are reported, and no variance across multiple training runs is shown.

*Each point is detailed below with its evidence.*

## Summary of the paper

The paper proposes the Transformer, a sequence transduction architecture based entirely on self-attention mechanisms without recurrence or convolution. It employs an encoder-decoder stack of multi-head attention and position-wise feed-forward layers, with sinusoidal positional encodings. On WMT 2014 English-German and English-French translation, the Transformer achieves state-of-the-art BLEU scores (28.4 and 41.8) with substantially lower training cost than prior models. The authors also demonstrate generalization to English constituency parsing with both large and limited training data.

## Do the paper's numbers agree with each other?

6 results printed in the paper were checked against other numbers it prints: 4 numbers of the abstract, compared with the body; 2 relations between numbers pointed out by the model. All arithmetic is done by code. **1 does not agree.**

| | What is checked | Arithmetic | Result | Paper | Where |
| --- | --- | --- | --- | --- | --- |
| **✗** | 41.8 in the abstract and 41.0 in the body, both after "score of" in passages about the same thing (bleu, english, french, model, score) | `41.0` | 41.0 | 41.8 | "petitive models. On the WMT 2014 English-to-French translation task, our big model achieves a BLEU score of 41.0, outperforming all of the pr" |

<details>
<summary>The 5 that agree</summary>

| | What is checked | Arithmetic | Result | Paper | Where |
| --- | --- | --- | --- | --- | --- |
| ✓ | 28.4, quoted in the abstract, is also printed in the body of the paper | `28.4` | 28.4 | 28.4 | "\| 27.3 \| 38.1 \| \| 3.3·10^(18) \| Transformer (big) \| 28.4 \| 41.8 \| \|" |
| ✓ | 41.8, quoted in the abstract, is also printed in the body of the paper | `41.8` | 41.8 | 41.8 | "\| 38.1 \| \| 3.3·10^(18) \| Transformer (big) \| 28.4 \| 41.8 \| \| 2.3\" |
| ✓ | 3.5, quoted in the abstract, is also printed in the body of the paper | `3.5` | 3.5 | 3.5 | "e (ref.)), step time was 1.0 seconds. The big models were trained for 300,000 steps (3.5 days)." |
| ✓ | Text says base models trained for 100,000 steps or 12 hours with step time 0.4 seconds on 8 GPUs | `100000*0.4/3600` | 11.1111 | 12 | "each training step took about 0.4 seconds. We trained the base models for a total of 100,000 steps or 12 hours." |
| ✓ | Text says big model uses h=16 attention heads with d_k=d_v=d_model/h=64, Table 3 shows h=16, d_k=64, d_v=64 for big model | `1024/16` | 64 | 64 | "In this work we employ h=8 parallel attention layers, or heads. For each of these we use d_k=d_v=dmodel/h=64." |

</details>

Each printed input is taken to stand for anything that rounds to it, so rounding is not reported as a mismatch. A mismatch in a check the model set up is reported only when a second model agrees the check compares the right quantities.

## Major concerns

**1. No random seeds are reported, and no variance across multiple training runs is shown. Results rely on single runs with checkpoint averaging, making it impossible to assess result stability.** (completeness)

> For the base models, we used a single model obtained by averaging the last 5 checkpoints... For the big models, we averaged the last 20 checkpoints.

Suggested: Report results over multiple random seeds (at least 3) with mean and standard deviation, or at minimum state the random seed used for reproducibility.

## Minor concerns

**1. The claim that label smoothing 'hurts perplexity... but improves accuracy and BLEU score' is presented without supporting data (e.g., perplexity curves or ablation).** (evidence)

> This hurts perplexity, as the model learns to be more unsure, but improves accuracy and BLEU score.

Suggested: Provide a small ablation showing perplexity and BLEU with and without label smoothing, or cite a source that demonstrates this trade-off for the Transformer.

**2. The parsing experiment uses a 4-layer, d_model=1024 Transformer, differing from both the base (6-layer, 512) and big (6-layer, 1024) translation models, without justification for the architecture change.** (clarity)

> We trained a 4-layer transformer with d_(model) = 1024 on the Wall Street Journal (WSJ) portion of the Penn Treebank... about 40K training sentences.

Suggested: Explain why a 4-layer model was chosen for parsing, or show that the standard 6-layer base model performs similarly.

**3. The claim 'Convolutional layers are generally more expensive than recurrent layers, by a factor of k' is a broad generalization without citation or qualification (e.g., kernel size, separable convolutions).** (soundness)

> Convolutional layers are generally more expensive than recurrent layers, by a factor of k.

Suggested: Qualify the statement (e.g., 'for standard convolutions with kernel width k') and cite a complexity analysis, or remove the unqualified comparison.

## Concerns raised and withdrawn

Each concern was argued against before being kept. These were withdrawn, either because a passage of the paper answers them or because a second reading found them not to hold:

- ~~The abstract states the 28.4 BLEU result was achieved 'after training for 3.5 days on eight GPUs', but the body clarifies that the base model (which also surpasses prior work) trains in 12 hours, while the big model takes 3.5 days. The abstract conflates the two configurations.~~ Two models reading the paper again both found: The abstract attributes the 3.5-day training time to the 41.8 BLEU English-to-French result, not to the 28.4 BLEU English-to-German result; the referee's quoted conflation does not appear in the paper.

## Strengths

- The architecture is described with sufficient detail to implement, including exact dimensions, residual connections, layer normalization, and the scaled dot-product and multi-head attention formulations. ("Each layer has two sub-layers. The first is a multi-head self-attention mechanism, and the second is a simple, position-wise fully connected feed-forward networ")
- A clear computational complexity analysis compares self-attention to recurrent and convolutional layers, showing constant sequential operations for self-attention versus linear for recurrence. ("As noted in Table (ref.), a self-attention layer connects all positions with a constant number of sequentially executed operations, whereas a recurrent layer re")
- Strong empirical results on standard benchmarks with explicit training cost comparisons (FLOPs) against multiple strong baselines including ensembles. ("On the WMT 2014 English-to-German translation task, the big transformer model outperforms the best previously reported models (including ensembles) by more than")
- Ablation studies in Table 3 (variations) systematically test component choices such as number of heads, key/value dimensions, feed-forward size, dropout, and learned vs. sinusoidal positional encodings. ("We also experimented with using learned positional embeddings instead, and found that the two versions produced nearly identical results (see Table (ref.) row (")
- The paper includes attention visualizations and notes that individual heads learn distinct, linguistically interpretable behaviors, suggesting a side benefit of interpretability. ("Not only do individual attention heads clearly learn to perform different tasks, many appear to exhibit behavior related to the syntactic and semantic structure")

## Can it be reproduced from what the paper gives?

| | Requirement | Evidence in the paper |
| --- | --- | --- |
| Partly | Data available or fully described | Standard public datasets are named and sized, but not released with the paper. ("We trained on the standard WMT 2014 English-German dataset consisting of about 4.5 million sentence pairs... For English-French, we used the") |
| Yes | Code available | Code repository explicitly provided. ("The code we used to train and evaluate our models is available at https://github.com/tensorflow/tensor2tensor") |
| Yes | Method described fully enough to implement | Architecture, attention formulas, positional encoding, optimizer, regularization, and hyperparameters are all specified. ("The Transformer follows this overall architecture using stacked self-attention and point-wise, fully connected layers for both the encoder a") |
| Yes | Parameters and settings given | All key hyperparameters are listed. |
| Yes | Hardware and software environment given | Hardware specified; software implied by tensor2tensor/TensorFlow reference. ("We trained our models on one machine with 8 NVIDIA P100 GPUs.") |
| No | Randomness controlled (seeds, repetitions) | No random seeds reported; no multiple runs described. |
| No | Variability reported (error bars, repeated runs) | Single training runs with checkpoint averaging; no variance estimates. |
| Yes | Comparisons or baselines adequate | Compares against a range of strong contemporary models including ensembles. ("ByteNet... Deep-Att + PosUnk... GNMT + RL... MoE... ConvS2S Ensemble... Transformer (base model)... Transformer (big)") |
| Yes | Metrics defined | BLEU, FLOPs, and parsing F1 are clearly used. ("BLEU score... Training Cost (FLOPs)... WSJ 23 F1") |
| Partly | Limitations discussed | Acknowledges quadratic complexity for long sequences as a limitation and proposes a direction, but does not discuss other limitations (e.g., data efficiency, generalization beyond tested tasks). ("To improve computational performance for tasks involving very long sequences, self-attention could be restricted to considering only a neigh") |

## How it stands against related work

The single retrieved result is a later variant that explicitly targets the Transformer's translation benchmarks, confirming the paper's results as a standard reference point. No other retrieved works address the core architecture, the multi-head attention design, or the parsing generalization, so the breadth of the contribution cannot be judged from these snippets alone.

| Related work found | Year | How it relates | Cited by the paper |
| --- | --- | --- | --- |
| [Re-Transformer: A Self-Attention Based Model for Machine Translation](https://www.sciencedirect.com/science/article/pii/S1877050921011509) |  | alternative approach: Re-Transformer modifies the Transformer architecture for machine translation, reporting BLEU improvements of 4 and 17 points over the original on WMT 2014 En-De and En-Fr, directly benchmarking against this paper's results. | **Not found in the paper** |

Found by web search for: *sequence transduction self-attention without recurrence convolution*; *multi-head attention encoder-decoder positional encoding*; *self-attention machine translation WMT English German French*; *scaled dot-product attention*. The works were judged from their titles and search snippets, not read. A year is given only when the work's address carries it; a work with no year may also be later than the paper (2017). "Not found" means the work's full title does not appear in the paper's text.

## The figures, as read from the images

Each figure was cut out of the PDF and described by a vision model, so that the review is not limited to captions. These are descriptions, not measurements: values read off a plot are approximate.

<details>
<summary>5 figure(s) described</summary>

- **Figure 1.** This is a block diagram illustrating the architecture of the Transformer model. The diagram is organized vertically, showing the flow of data from inputs to outputs. ### Key Components and Labels: - **Bottom Left**: "Inputs" enter the model. - **Input Embedding**: A block where inputs are embedded. - **Positional Encoding**: Added to the input embedding (indicated by a "+" symbol). - **Multi-Head Attention**: A block labeled "Multi-Head Attention" with "Add & Norm" above it. - **Feed Forward**: A block labeled "Feed Forward" with "Add & Norm" above it. - **Middle**: The structure repeats "Nx" times (a vertical stack of the same blocks: "Multi-Head Attention" → "Add & Norm" → "Feed Forward" → "Add & Norm"). - **Bottom Right**: "Outputs (shifted right)" enter the model. - **Output Embedding**: A block where outputs are embedded. - **Positional Encoding**: Added to the output embedding (indicated by a "+" symbol). - **Masked Multi-Head Attention**: A block labeled "Masked Multi-Head Attention" with "Add & Norm" above it. - **Multi-Head Attention**: Another "Multi-Head Attention" block with "Add & Norm" above it. - **Feed Forward**: A "Feed Forward" block with "Add & Norm" above it. - **Top Right**: The sequence continues "Nx" times (same stacked blocks as the left side). - **Output Processing**: At the very top, the flow ends with "Linear" → "Softmax" → "Output Probabilities". ### Structure: The diagram is split into two parallel streams (left and right) that run through "Nx" identical layers (each containing "Multi-Head Attention" + "Add & Norm" + "Feed Forward" + "Add & Norm"). The left stream processes inputs (with positional encoding added first), while the right stream processes outputs (with positional encoding added last, and "Masked Multi-Head Attention" in the first layer of the right stream). The final
- **Figure 2.** This is a figure from a scientific paper showing two diagrams side by side, labeled "Scaled Dot-Product Attention" (left) and "Multi-Head Attention" (right). ### Left Panel (Scaled Dot-Product Attention): - **Structure**: A vertical flowchart with sequential blocks connected by arrows. - **Blocks (top to bottom)**: - "MatMul" (purple box, topmost). - "SoftMax" (green box). - "Mask (opt.)" (yellow box with "Scale" below it, connected by an arrow). - "MatMul" (purple box, bottommost). - **Inputs/Outputs**: "Q" (input to bottom MatMul), "K" (input to bottom MatMul), "V" (input to bottom MatMul). The output of the top MatMul points to the SoftMax block. ### Right Panel (Multi-Head Attention): - **Structure**: A horizontal flowchart with parallel layers and a central "Scaled Dot-Product Attention" block. - **Central Block**: "Scaled Dot-Product Attention" (purple box, labeled with "h" on the right side, indicating the number of heads). - **Inputs to Central Block**: Three "Linear" blocks (white boxes) connected to "V", "K", and "Q" respectively. - **Outputs from Central Block**: The output of "Scaled Dot-Product Attention" is split into three "Linear" blocks (white boxes), which then combine via a "Concat" (yellow box) and a "Linear" (white box) to produce the final output. ### Labels and Text: - Title above left panel: "Scaled Dot-Product Attention". - Title above right panel: "Multi-Head Attention". - Caption below the figure: "Figure 2: (left) Scaled Dot-Product Attention. (right) Multi-Head Attention consists of several attention layers running in parallel." - Labels on left panel blocks: "MatMul", "SoftMax", "Mask (opt.)", "Scale", "MatMul". - Labels on right panel blocks:
- **Figure 3.** This figure is titled "Attention Visualizations" and is labeled as Figure 3 in the accompanying text. It consists of two identical horizontal panels stacked vertically, each displaying a sequence of words from a sentence. ### Axes and Structure: - **Horizontal axis**: Represents the sequence of words in the sentence. The words are: "It is in this spirit that a majority of American governments have passed new laws since 2009 making the registration or voting process more difficult . <EOS> <pad> <pad> <pad> <pad> <pad> <pad>". The sequence is repeated identically in both panels. - **Vertical axis**: Implied to represent the attention mechanism (not explicitly labeled with numerical values, but the structure shows attention "heads" as colored lines connecting words). ### Panels and Labels: Each panel contains the same sentence repeated twice (top and bottom rows of words). The words are aligned horizontally, with spaces between them. The sentence ends with "<EOS>" (End of Sentence) followed by six "<pad>" (Padding) tokens. ### Visual Elements: - **Colored lines (attention heads)**: Multiple colored lines connect the word "making" (purple line) to the phrase "more difficult" (pink lines), indicating attention from "making" to this distant dependency. Other words like "process" and "registration" also have lines connecting to "making" (e.g., brown and gray lines). The lines are color-coded, with different colors representing different attention heads (as noted in the figure caption: "Different colors represent different heads"). ### Main Trend: The figure illustrates how attention heads in the encoder self-attention mechanism (layer 5 of 6) focus on long-distance dependencies. Specifically, many attention heads attend to the verb "making" and its distant dependency on the phrase "more difficult," completing the phrase "making...more difficult." The colored lines visually highlight these connections. ### Text in the Figure: - Sentence text (top row): "It is in this spirit that a majority of American governments have passed new laws since 2009 making the registration or voting process more difficult . <EOS> <pad
- **Figure 4.** This figure is a visualization of attention heads in a neural network, specifically for anaphora resolution. It consists of two panels (top and bottom), each showing attention connections between words in a sentence. **Top Panel (Full attentions for head 5):** - The x-axis and y-axis both display the same sequence of words: "The Law will never be perfect , but its application should be just - this is what we are missing , in my opinion . <EOS> <pad>" - The words are arranged in a grid, with each word connected by purple lines to other words, indicating attention weights. - The connections are dense and spread across the entire sequence, with some words (like "its" and "application") having many connections. **Bottom Panel (Isolated attentions from just the word ‘its’ for attention heads 5 and 6):** - The x-axis and y-axis display the same sequence of words as the top panel. - Only two attention lines are shown: one from "its" to "Law" (purple line), and one from "its" to "application" (brown line). - The rest of the sequence has no connections from "its." **Labels and values:** - The x-axis and y-axis labels are the words from the sentence. - The figure has no numerical values; the attention is visualized by line thickness and presence. - The caption below the figure reads: "Figure 4: Two attention heads, also in layer 5 of 6, apparently involved in anaphora resolution. Top: Full attentions for head 5. Bottom: Isolated attentions from just the word ‘its’ for attention heads 5 and 6. Note that the attentions are very sharp for this word." **Main trend or structure:** - The top panel shows broad, widespread attention across the entire sentence for attention head 5. - The bottom panel shows focused attention from the word "its" to "Law" and "application," indicating specific relationships being highlighted by the attention mechanism.
- **Figure 5.** This figure consists of two stacked panels (top and bottom), each displaying a matrix-like visualization of attention heads from a neural network model. ### Axes and Structure: - **Horizontal axis (bottom row of each panel):** Words from the input sentence: "The Law will never be perfect , but its application should be just - this is what we are missing , in my opinion . <EOS> <pad>" (repeated across both panels). - **Vertical axis (left column of each panel):** The same sequence of words, serving as the "query" or "target" positions for attention. - **Lines connecting points:** Each line represents an attention "head" (a specific focus of the model's attention). Green lines in the top panel and red lines in the bottom panel show the attention patterns for different heads. ### Labels and Values: - The sentence words are labeled along both axes (e.g., "The", "Law", "will", "never", "be", "perfect", "but", "its", "application", "should", "be", "just", "-", "this", "is", "what", "we", "are", "missing", ",", "in", "my", "opinion", ".", "<EOS>", "<pad>"), with punctuation and special tokens included. - No numerical values are explicitly labeled on the axes or lines; the lines’ thickness or presence indicates the strength or existence of attention between word pairs. ### Main Trend/Structure: - **Top panel (green lines):** Attention heads show widespread connections across the sentence, with some words (e.g., "perfect", "missing", "opinion") having multiple outgoing lines, suggesting they attend to many other words. - **Bottom panel (red lines):** Attention heads show more focused, sparse connections, with some words (e.g., "never", "just", "what") having fewer or more directed lines, indicating different attention patterns than the top panel. - Both panels illustrate how different attention heads (green vs. red) focus on different parts of the sentence structure, with lines forming a web-like pattern in the top panel and a more linear or clustered

</details>

## Questions for the authors

1. Would the base model (6-layer, 512-dim) achieve comparable parsing results to the 4-layer, 1024-dim model used in the constituency parsing experiment, and if not, why was the architecture changed for that task?

> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept only when the passage it quotes is in the paper and no other passage of the paper answers it. The number checks are computed.

