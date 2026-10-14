# Review of: Observation of Gravitational Waves from a Binary Black Hole Merger

This report does what a referee does. First it reads the paper: what it claims, whether its numbers agree with each other, what is unsound, unclear or missing, and whether it can be reproduced from what it gives. Then it tries to recompute the results that can be recomputed.

## Key findings

- **Found by code:** The abstract quotes 250, 1.0, which are not printed anywhere in the body of the paper, in text or tables.
- **Major concern:** Only two detectors were operating, limiting sky localization to ~600 deg² and preventing polarization measurement;
- **Numbers consistent:** all 8 cross-checks of the paper's numbers agree.

*Each point is detailed below with its evidence.*

## Summary of the paper

The paper reports the first direct detection of gravitational waves, observed by the two Advanced LIGO detectors on September 14, 2015. The signal GW150914 matches the general-relativistic waveform for the inspiral, merger, and ringdown of a binary black hole system with component masses of approximately 36 and 29 solar masses. The detection achieves a matched-filter signal-to-noise ratio of 24 and a false alarm rate below 1 in 203,000 years (>5.1σ). Two independent search pipelines—a matched-filter search using binary templates and a generic transient search—both identify the event with high significance. The observations confirm the existence of stellar-mass binary black holes and provide a strong-field test of general relativity.

## Do the paper's numbers agree with each other?

8 results printed in the paper were checked against other numbers it prints: 5 numbers of the abstract, compared with the body; 3 relations between numbers pointed out by the model. All arithmetic is done by code. **0 do not agree.**

<details>
<summary>The 8 that agree</summary>

| | What is checked | Arithmetic | Result | Paper | Where |
| --- | --- | --- | --- | --- | --- |
| ✓ | 203000, quoted in the abstract, is also printed in the body of the paper | `203000` | 203000 | 203000 | "per bound can be placed on its false alarm rate. Across the three search classes this bound is 1 in 203000 years. This translates to a f" |
| ✓ | 5.1, quoted in the abstract, is also printed in the body of the paper | `5.1` | 5.1 | 5.1 | "eviations based on the corresponding noise background. The significance of GW150914 is greater than 5.1σ and 4.6σ for t" |
| ✓ | 410, quoted in the abstract, is also printed in the body of the paper | `410` | 410 | 410 | "29þ4 -4M⊙ Final black hole mass 62þ4 -4M⊙ Final black hole spin 0.67þ0.05 -0.07 Luminosity distance 410þ160 -180 Mpc Source redshift" |
| ✓ | 0.09, quoted in the abstract, is also printed in the body of the paper | `0.09` | 0.09 | 0.09 | "4 -4M⊙ Final black hole spin 0.67þ0.05 -0.07 Luminosity distance 410þ160 -180 Mpc Source redshift z 0.09þ0.03 -0.04 --- page 7, par" |
| ✓ | 3.0, quoted in the abstract, is also printed in the body of the paper | `3.0` | 3.0 | 3 | "gravitational-wave luminosity [39]. The estimated total energy radiated in gravitational waves is 3.0^(+0.5)_(-0.5)M_odot c^2. Th" |
| ✓ | Mass conservation: initial black hole masses minus final mass equals radiated energy | `36 + 29 - 62` | 3 | 3 | "the initial black hole masses are 36⁺⁵₋⁴M⊙ and 29⁺⁴₋⁴M⊙, and the final black hole mass is 62⁺⁴₋⁴M⊙, with 3.0⁺⁰.⁵₋⁻⁰.⁵M⊙c² radiated in gravitational waves" |
| ✓ | Generic transient search: background equivalent years divided by trials factor equals false alarm rate denominator | `67400 / 3` | 22466.7 | 22500 | "Measured on a background equivalent to over 67400 years of data and including a trials factor of 3... its false alarm rate is lower than 1 in 22500 years" |
| ✓ | Binary coalescence search: background equivalent years divided by three search classes equals false alarm rate denominator | `608000 / 3` | 202667 | 203000 | "Repeating this procedure ~10⁷ times produces a noise background analysis time equivalent to 608000 years... Across the three search classes this bound is 1 in 203000 years" |

</details>

Each printed input is taken to stand for anything that rounds to it, so rounding is not reported as a mismatch. A mismatch in a check the model set up is reported only when a second model agrees the check compares the right quantities.

## Major concerns

**1. Only two detectors were operating, limiting sky localization to ~600 deg² and preventing polarization measurement; the paper acknowledges this but does not quantify the impact on parameter estimation.** (completeness)

> Only the LIGO detectors were observing at the time of GW150914. The Virgo detector was being upgraded, and GEO 600, though not sufficiently sensitive to detect this event, was operating but not in observational mode. With only two detectors the source position is primarily determined by the relative arrival time and localized to an area of approximately 600 deg^2 (90% credible region) [39,46].

Suggested: Discuss how the two-detector limitation affects the credible intervals for masses, distance, and inclination, and note what additional constraints a third detector would provide.

## Minor concerns

**1. The background estimation uses a time-shift method that the authors acknowledge overestimates the noise background by allowing signal-plus-noise coincidences, making the significance conservative but the exact false-alarm rate uncertain.** (soundness)

> In this process a gravitational-wave signal in one detector may coincide with time-shifted noise transients in the other detector, thereby contributing to the background estimate. This leads to an overestimate of the noise background and therefore to a more conservative assessment of the significance of candidate events.

Suggested: Clarify whether the quoted false-alarm rate of <1 per 203,000 years already accounts for this overestimation or is a raw output of the time-shift procedure.

**2. The merger rate estimate spans 2–400 Gpc⁻³ yr⁻¹, a factor of 200, and only the lowest rates are excluded; the paper does not explain which astrophysical assumptions drive this spread.** (evidence)

> Using several different models of the underlying binary black hole mass distribution, we obtain rate estimates ranging from 2–400 Gpc-3 yr-1 in the comoving frame [111–113]. This is consistent with a broad range of rate predictions as reviewed in [114], with only the lowest event rates being excluded.

Suggested: Summarize the key model differences (e.g., mass distribution, formation channel) that produce the rate range, so readers can assess the astrophysical constraints.

**3. The paper states that 16 days of coincident data were analyzed from September 12 to October 20, 2015, but does not explicitly give the duty cycle or live-time fraction for that period.** (clarity)

> We present the analysis of 16 days of coincident observations between the two LIGO detectors from September 12 to October 20, 2015. This is a subset of the data from Advanced LIGO's first observational period that ended on January 12, 2016.

Suggested: Report the coincident duty cycle (or effective observing time) for the 16-day subset to allow rate calculations to be reproduced.

**4. The abstract quotes 250, 1.0, which are not printed anywhere in the body of the paper, in text or tables. A reader cannot see where these results come from, unless they are read off a figure.** (evidence)

> The signal sweeps upwards in frequency from 35 to 250 Hz with a peak gravitational-wave strain of 1.0 × 10-21.

Suggested: Report each number of the abstract in the results, in a table or the text.

## Strengths

- The detection significance is exceptionally high, with a matched-filter SNR of 24 and a false alarm rate below 1 per 203,000 years, corresponding to >5.1σ. ("The signal was observed with a matched-filter signal-to-noise ratio of 24 and a false alarm rate estimated to be less than 1 event per 203 000 years, equivalent")
- Two independent analysis pipelines with uncorrelated noise responses both detect the event, greatly reducing the chance of a systematic artifact. ("GW150914 is confidently detected by two different types of searches. One aims to recover signals from the coalescence of compact objects, using optimal matched ")
- Extensive instrumental and environmental vetoes were performed, with no evidence that the signal could be an artifact. ("Exhaustive investigations of instrumental and environmental disturbances were performed, giving no evidence to suggest that GW150914 could be an instrumental ar")
- The remnant black hole mass and spin inferred from the early inspiral and late ringdown phases are mutually consistent, providing a strong internal check of general relativity. ("Using fitting formulas calibrated to numerical relativity simulations [92], we verified that the remnant mass and spin deduced from the early stage of the coale")
- The detector strain calibration is quantified to <10% amplitude and <10° phase uncertainty (1σ) and is continuously monitored. ("The calibration is established to an uncertainty (1σ) of less than 10% in amplitude and 10 degrees in phase, and is continuously monitored with calibration lase")

## Can it be reproduced from what the paper gives?

| | Requirement | Evidence in the paper |
| --- | --- | --- |
| Partly | Data available or fully described | A data release is referenced (LOSC) but the paper itself does not provide the strain time series or posterior samples. ("Further details about these results and associated data releases are available at [116]. Analysis results for the entire first observational") |
| No | Code available | No code repository or analysis software is cited in the paper. |
| Partly | Method described fully enough to implement | The matched-filter and generic transient search methods are outlined, but key details (template bank construction, wavelet reconstruction, χ² reweighting) are only referenced to other documents. ("The specific procedure used to estimate the background is slightly different for the two searches, but both use a time-shift technique: the ") |
| Partly | Parameters and settings given | Template bank size and mass/spin ranges are given, but not the grid spacing, minimal match, or prior choices for Bayesian parameter estimation. ("Approximately 250 000 template waveforms are used to cover this parameter space.") |
| Yes | Hardware and software environment given | The detector hardware, calibration, and timing infrastructure are described in detail. ("Data collection is synchronized to Global Positioning System (GPS) time to better than 10 μs [66]. Timing accuracy is verified with an atomi") |
| No | Randomness controlled (seeds, repetitions) | No mention of random seeds, Monte Carlo repetitions, or stochastic algorithm controls. |
| Yes | Variability reported (error bars, repeated runs) | Parameter uncertainties are reported as 90% credible intervals; the background estimation uses ∼10⁷ time-shift trials. ("All uncertainties define 90% credible intervals.") |
| Yes | Comparisons or baselines adequate | Two independent search pipelines serve as mutual baselines; previous upper limits are cited for rate comparison. ("These searches use independent methods, and their response to detector noise consists of different, uncorrelated, events. However, strong si") |
| Yes | Metrics defined | Detection statistic (η_c, ρ̂_c), SNR, false-alarm rate, and Gaussian-equivalent significance are all defined. ("Events are assigned a detection-statistic value that ranks their likelihood of being a gravitational-wave signal. The significance of a cand") |
| Yes | Limitations discussed | The paper explicitly discusses the two-detector limitation, the conservative background estimation, and the large rate uncertainty. ("With only two detectors the source position is primarily determined by the relative arrival time and localized to an area of approximately 6") |

## How it stands against related work

The paper reports the landmark first direct detection of gravitational waves (GW150914), a singular historical event that cannot be replicated or superseded by later methodological papers. The search results exclusively cover subsequent advances in search algorithms—template banks, eccentricity, machine learning, quantum computing, and pipeline optimizations—that build upon or offer alternatives to the matched-filtering framework validated by this detection. None of the results describe a prior or competing claim of first detection. The snippets do not reveal the specific astrophysical inference pipelines (e.g., parameter estimation, tests of general relativity) used to derive the source properties from the signal, which constitute a major portion of the paper's contribution beyond the detection itself.

| Related work found | Year | How it relates | Cited by the paper |
| --- | --- | --- | --- |
| [A template bank for gravitational waveforms from coalescing ...](https://dcc.ligo.org/public/0007/P070111/000/P070111-00.pdf) |  | builds on it: Proposes a phenomenological template family covering inspiral, merger, and ringdown coherently, directly enabling the matched-filter search that identified GW150914. | Cannot tell from the title |
| [Matched Filtering of Numerical Relativity Templates ...](https://arxiv.org/html/0705.3829v2) | 2007 | same method: Describes the matched-filtering technique using numerical relativity templates for compact binary mergers, the core method used to detect and characterize GW150914. | Cannot tell from the title |
| [Detectability of eccentric binary black holes with matched ...](https://research-portal.uu.nl/ws/files/238068707/PhysRevD.110.044013.pdf) |  | alternative approach: Extends matched-filter pipelines (PyCBC) to eccentric binaries using inspiral-only models, contrasting with the quasi-circular, full-coalescence templates used for GW150914. | Cannot tell from the title |
| [Hybrid algorithm combining matched filtering and ...](https://link.aps.org/doi/10.1103/5x62-9ldh) |  | alternative approach: Develops a hybrid matched-filtering and convolutional neural network algorithm for BBH searches, representing a later methodological evolution from the standard matched filtering used in the detection. | Cannot tell from the title |
| [Deep Learning Search for Gravitational Waves from ...](https://arxiv.org/html/2603.09386v2) | 2026 | alternative approach: Surveys machine-learning-based gravitational wave searches as a complement to the matched-filtering and coherent analyses that constituted the GW150914 detection pipelines. | Later than the paper |
| [Beyond FINDCHIRP for gravitational-wave matched-filter ...](https://link.aps.org/doi/10.1103/k21q-wp8f) |  | same method: Analyzes the FINDCHIRP algorithm (FFT-based matched filtering) foundational to the low-latency search pipelines that contributed to the GW150914 detection. | Cannot tell from the title |
| [Quantum search for gravitational wave of massive black hole ...](https://link.aps.org/doi/10.1103/3n8r-7dm7) |  | alternative approach: Explores a quantum matched-filtering algorithm for massive black hole binaries, offering a fundamentally different computational paradigm from the classical matched filtering used in the paper. | Cannot tell from the title |

Found by web search for: *first direct detection gravitational waves binary black hole merger*; *matched filter search binary black hole templates gravitational waves*; *matched filtering gravitational wave search binary black hole coalescence*; *matched filtering template bank gravitational wave data analysis*. The works were judged from their titles and search snippets, not read. A year is given only when the work's address carries it; a work with no year may also be later than the paper (2016). "Not found" means the work's full title does not appear in the paper's text.

## The figures, as read from the images

Each figure was cut out of the PDF and described by a vision model, so that the review is not limited to captions. These are descriptions, not measurements: values read off a plot are approximate.

<details>
<summary>4 figure(s) described</summary>

- **Figure 1.** This is a scientific figure (FIG. 1) showing data from the LIGO Hanford (H1) and Livingston (L1) detectors during the gravitational-wave event GW150914. The figure is divided into six panels arranged in two columns (left for Hanford, right for Livingston) and three rows. **Top Row (Strain):** - Left panel (Hanford, H1): Red line labeled "H1 observed" shows the strain signal over time (x-axis: Time (s), ranging from ~0.30 to 0.45 seconds; y-axis: Strain (10^-21), ranging from -1.0 to 1.0). - Right panel (Livingston, L1): Blue line labeled "L1 observed" and orange line labeled "H1 observed (shifted, inverted)" show the strain signals over time (x-axis: Time (s), same range; y-axis: Strain (10^-21), same range). **Middle Row (Comparison with Numerical Relativity):** - Left panel (Hanford, H1): Gray lines labeled "Reconstructed (wavelet)" and "Reconstructed (template)" are compared to a red line labeled "Numerical relativity." - Right panel (Livingston, L1): Gray lines labeled "Reconstructed (wavelet)" and "Reconstructed (template)" are compared to a blue line labeled "Numerical relativity." **Bottom Row (Residuals):** - Left panel (Hanford, H1): Red line labeled "Residual" shows the difference between observed and reconstructed signals. - Right panel (Livingston, L1): Blue line labeled "Residual" shows the difference between observed and reconstructed signals. **Bottom Row (Frequency Spectrum):** - Left panel (Hanford, H1): Color scale (green to yellow) shows frequency (y-axis: Frequency (Hz), ranging from 32 to 512 Hz) and normalized amplitude (color bar, 0 to 8) over time (x-axis: Time (s), same range). - Right panel (Livingston, L1): Color scale (
- **Figure 2.** This is a scientific figure (FIG. 2) with two main panels, showing data related to the gravitational wave event GW150914. ### Top Panel: - **Title/Description**: "Estimated gravitational-wave strain amplitude from GW150914 projected onto H1. This shows the full bandwidth of the waveforms, without the filtering used for Fig. 1." - **Axes**: - **X-axis**: Time (s), ranging from 0 to 4.3 seconds. - **Y-axis**: Strain (10^-21), ranging from -1.0 to 1.0. - **Data**: Two curves: - Red line: "Numerical relativity" (labeled with a red square marker). - Gray line: "Reconstructed (template)" (labeled with a gray square marker). - **Structure**: The strain oscillates with increasing amplitude as time progresses, peaking sharply near the end of the time window. Above the main plot, there are three inset images labeled "Inspiral," "Merger," and "Ring-down," showing black hole horizons during these phases. ### Bottom Panel: - **Title/Description**: "The Keplerian effective black hole separation in units of Schwarzschild radii (RS = 2GM/c²) and the effective relative velocity given by the post-Newtonian parameter v/c = (GMπf/c³)^1/3, where f is the gravitational-wave frequency calculated with numerical relativity and M is the total mass (value from Table I)." - **Axes**: - **X-axis**: Time (s), same as the top panel (0 to 4.3 seconds). - **Left Y-axis**: Velocity (c), ranging from 0 to 0.6. - **Right Y-axis**: Separation (RS), ranging from 3 to 5. - **Data**: Two curves: - Black line with square markers: "Black hole separation" (labeled with a black square marker). - Black line with circle markers: "
- **Figure 3.** This is a figure from a scientific paper, labeled "FIG. 3." It consists of two main panels: (a) and (b). Panel (a) is a simplified diagram of an Advanced LIGO detector. It shows a schematic of the detector's layout, including: - A map of the United States with two points labeled "H1" and "L1," connected by a dashed line indicating a "10 ms light travel time." - A vertical structure representing the detector's optical path, with "Test Mass" blocks at the top and bottom, and a "Beam Splitter" in the middle. - Labels such as "Laser Source" (20 W), "Power Recycling," "Signal Recycling," "Photodetector," and "100 kW Circulating Power." - The distance between the top and bottom Test Masses is labeled "L_y = 4 km," and the distance between the two arms (H1 and L1) is labeled "L_x = 4 km." Panel (b) is a graph showing "Strain noise (Hz^-1/2)" on the y-axis and "Frequency (Hz)" on the x-axis. The graph has two data series: one labeled "H1" (red) and one labeled "L1" (blue). The x-axis ranges from 20 Hz to 1000 Hz, and the y-axis ranges from 10^-23 to 10^-21. The graph shows fluctuations in strain noise across different frequencies, with some peaks and valleys. The main trend in panel (b) is that strain noise is generally lower at higher frequencies (right side of the graph) and higher at lower frequencies (left side), with some notable peaks and dips across the frequency range.
- **Figure 4.** This is a scientific figure (FIG. 4) consisting of two adjacent histograms, each with its own panel, comparing search results from two different gravitational wave (GW) detection methods: "Generic transient search" (left panel) and "Binary coalescence search" (right panel). ### Axes: - **X-axis**: Both panels share a common x-axis labeled "Detection statistic" with two sub-labels: for the left panel, it is "η_c" (detection statistic for generic transients), and for the right panel, "ρ̂_c" (detection statistic for binary coalescence). The x-axis ranges from 8 to 24 (left panel) and 8 to 24 (right panel), with tick marks at 8, 10, 12, 14, 16, 18, 20, 22, 24. - **Y-axis**: Both panels have a y-axis labeled "Number of events," ranging from 10⁻⁸ to 10², with tick marks at 10⁻⁸, 10⁻⁷, 10⁻⁶, 10⁻⁵, 10⁻⁴, 10⁻³, 10⁻², 10⁻¹, 10². ### Panels and Labels: #### Left Panel ("Generic transient search"): - Title: "Generic transient search" (top left). - Top gray bar labels: "2σ 3σ 4σ 4.4σ 4.4σ > 4.6σ" (significance levels in Gaussian standard deviations). - Legend (bottom left): - Orange squares: "Search Result (C3)" - Black line: "Search Background (C3)" - Blue diamonds: "Search Result (C2+C3)" - Green line: "Search Background (C2+C3)" - A vertical black arrow labeled "GW150914" points to the x-axis value ~20 (left panel).

</details>

## Questions for the authors

1. What is the coincident duty cycle (live-time fraction) for the 16-day analysis period, and how does it affect the merger rate density calculation?
2. Does the quoted false-alarm rate of <1 per 203,000 years already incorporate the conservative bias from the time-shift background method, or is it a raw output that would become even lower after correction?
3. Which specific astrophysical model assumptions (e.g., common-envelope efficiency, metallicity distribution, dynamical formation fraction) are responsible for the factor-of-200 spread in the rate estimate 2–400 Gpc⁻³ yr⁻¹?

> The summary, the concerns, the strengths and the questions are a model's judgement. A concern is kept only when the passage it quotes is in the paper and no other passage of the paper answers it. The number checks are computed.

