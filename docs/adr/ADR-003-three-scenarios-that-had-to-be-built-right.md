# ADR-003: Three things that were measured wrong first

**Status.** Accepted. The corrections are the most useful thing here, so they are written
down rather than quietly fixed.

## The first: dividing by an assumed number of expiries

The stampede was originally computed as total origin calls divided by the duration over the
time to live. Every figure came out about a fifth below the derivation, consistently, at
every rate and every latency - which is the signature of a systematic error rather than
noise.

It was. A cache entry's expiry is set when the fetch *returns*, not when it was asked for,
so the refresh cycle is `T + d` rather than `T`. Dividing by `T` counts more expiries than
happened and spreads the same calls across them.

The fix was not to correct the divisor. Counting clusters is better than dividing by an
assumed cycle length at all, because it does not depend on knowing the cycle: the origin
records when each call started, and calls separated by more than one origin latency belong
to different refreshes. `refresh_cycle_seconds` exists as well, for the total-call and
hit-rate predictions where a cycle length is genuinely needed, and it includes the fetch.

## The second: jitter measured against the wrong scenario

E3 compares jitter to a plain TTL across many keys, and the first version found it barely
helped - a reduction of about a fifth, which is within the range of "probably not worth the
complexity".

The measurement was correct and the scenario was wrong. Keys in that run had been populated
by ordinary traffic, so each one was refreshed whenever its own requests happened to arrive,
and they had drifted apart by themselves. Jitter was being asked to spread out expiries that
were already spread out.

The case jitter is actually for is keys filled in the same instant - after a deploy, a
flush, or a cold start - which stay synchronised because they were synchronised to begin
with. A `prefill` option now creates that condition explicitly, and against **20 keys filled
together** the peak **peaks at 69 simultaneous** origin calls with a plain TTL and **down to
16 simultaneous** with jitter, a **4.31x reduction**.

The lesson is not about jitter. It is that "we measured it and it did not help" is only as
good as the scenario, and a fix aimed at a specific failure will look useless when tested
against a different one.

## The third: a maximum where a median belonged

E3's comparisons were originally made on the largest cluster observed in each run. On one
seed the jittered single-key run reported a stampede of eighteen against the naive run's
eleven, which would have read as jitter making things worse.

It did not. Checking several seeds showed the median cluster was eleven in every run, with
an occasional outlier: on two cores running eleven concurrent sleeps, a pair of refresh
cycles sometimes merges into a single cluster. A maximum over ten clusters is dominated by
whether that happened once.

Claims are now made on the median and the largest is still reported, as an observation
rather than as a basis for one.

## What they have in common

The first was caught by a systematic gap between measurement and derivation. The second by a
result that was too boring to be interesting - "the standard advice does nothing" deserves
more scepticism than it usually gets. The third by running the same thing on three seeds
before believing it.

None was caught by a test.
