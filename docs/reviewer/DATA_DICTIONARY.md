# Reviewer statistics: definitions and units

Generated from the statistics implementation. Log ratios retain a numerator and denominator in JSON; rule fractions have separate count fields and the denominators defined below. Descriptive decimal displays are rounded, while observation exports preserve the original score strings.

## Cohort

- **Calculation:** All rows in cases.csv; raw case roster comes from recorded source audit.

- **Scope:** The 817 removed NA segments concern the 116 retained cases only. The excluded all-NA case has no segment inventory here.

## Intervals

- **Unit:** frames

- **Calculation:** Half-open [start_frame,end_frame_exclusive); duration=end-start; seconds=frames/recorded frame rate.

## Case durations

- **Calculation:** recording=whole case; retained_event=sum of non-NA durations; retained_span=last retained end minus first retained start. These are different durations.

## Repetition

- **Calculation:** repeat_events_after_first_occurrence=trace length minus number of distinct labels; adjacent_equal_activity_pairs counts neighboring equal labels in the retained trace.

## Variants

- **Calculation:** Exact ordered GT activity tuples after NA removal, ordered by start/end/event ID; adjacent equal labels are never collapsed. Frequencies sort descending, ties by lexicographic tuple.

- **Denominator:** retained cases

## Direct follows

- **Calculation:** One occurrence for each adjacent pair in a retained case; pairs may cross removed NA gaps. Same-label pairs remain included.

## Distributions

- **Calculation:** Quartile p uses linear interpolation at sorted zero-based position (n-1)*p (Hyndman-Fan type 7). Population SD=sqrt(sum((x-mean)^2)/n), not sample SD. Empty samples yield count0 and null summaries; singleton SD0.

- **Unit:** Named by each metric; derived statistics are floats, never replacement input scores.

## Scores

- **Calculation:** Original decimal score tokens are parsed as exact fractions. No rescaling, normalization or entropy is computed. observations.csv preserves the original scores JSON and input score strings.

## Score mass

- **Calculation:** Retained mass=sum of three original scores. Discarded non-NA and removed-NA mass are recorded input fields. Residual=abs(retained+removedNA+discarded-1), not forcibly set to zero.

- **Validation tolerances:** 1e-6 for unit-mass residual;1e-12 for recorded retained mass versus exact sum. Descriptive input checks only; unrelated to exact solver certification.

## Original top3

- **Calculation:** For each replacement, remove inserted GT and restore the recorded third label/score. Unreplaced records are already the original top3. Full original GT ranks beyond3 are recorded replacement provenance, not recoverable from three retained scores alone.

## Highest-score segment agreement with GT

- **Calculation:** Highest original non-NA score per retained observation, with lexicographic activity tie-break; compare label with GT.

- **Denominator:** retained observations

- **Scope:** Direct recomputation on GT-aligned segments; GT insertion does not alter top1.

## Duration-weighted segment agreement with GT

- **Calculation:** Sum duration of segments whose single top1 label equals GT, divided by total retained segment duration.

- **Denominator:** frames in retained non-NA GT segments

- **Scope:** This labels each entire segment with one prediction; it is NOT raw frame-prediction accuracy.

## Upstream frame accuracy

- **Calculation:** Ratios recomputed from recorded correct-frame/total-frame counts in model_selection.json. Per-case subtotals are verified.

- **Scope:** Recorded upstream predictions on117 raw cases; raw frame predictions are not included or re-evaluated by this module.

## Ratios

- **Calculation:** Numerator, denominator, exact fraction, decimal value and percent are reported; denominator0 produces null derived ratios.

## Groups

- **Calculation:** process_group is copied from each retained case record; event and frame shares are based on this retained cohort.

## Rule-statistic units

Prerequisite case support counts cases with at least one trigger; event support counts trigger events. Vacuous cases have no trigger. Bound support counts positive-count cases and occurrences of the bounded activity. Case fractions divide by 116 retained cases; trigger-event fractions divide by 1,856 retained GT events; within-group case fractions divide by that furniture group's retained case count. Candidate-potential violations describe combinations allowed by candidate availability alone, not a returned matching or simultaneous feasibility under all constraints.
