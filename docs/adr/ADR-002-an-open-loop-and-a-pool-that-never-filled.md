# ADR-002: An open loop, and checking the pool was never the limit

**Status.** Accepted.

## The decision

Arrivals are scheduled in advance at fixed intervals and dispatched when their time comes,
whether or not earlier requests have finished. The thread pool is sized well above the
worst expected number of requests in flight, and every result records whether the pool ever
ran out of workers.

## Why a closed loop would have answered a different question

A closed loop with `C` workers, each sending a request and waiting for it, cannot have more
than `C` requests inside a stall. So it would report a stampede of `C` - at every request
rate, at every origin latency, for every cache. The number would be stable, reproducible,
and a property of the harness.

That failure is particularly easy to miss here because `C` is a plausible-looking answer. A
stampede of thirty-two against a pool of thirty-two reads like a measurement rather than a
tautology, and it would agree with itself across runs.

## Why the pool still has to be watched

An open loop with too few workers is a closed loop wearing an open loop's clothes. Once
every worker is occupied, new arrivals queue in the executor rather than reaching the cache,
and the stampede is capped at the pool size exactly as it would have been in a closed loop -
but now with nothing in the shape of the result to say so.

So the pool is sized at three times the expected in-flight count with a floor, and
`pool_saturated` is recorded on every run. The report refuses to print a stampede figure
when it is set, and the law check fails on any recorded run where it was true. E1 reports
`pool_never_saturated` for the whole sweep as a single line, because one saturated run
anywhere in a sweep invalidates the comparison the sweep is making.

## The bias that remains

Scheduled arrivals are not Poisson arrivals. Real traffic clusters, and a cluster landing
on an expiry makes a bigger stampede than the average rate predicts while a gap makes a
smaller one. The derivation `1 + λd` is the expectation either way; what changes is the
spread around it.

That is the right trade for this measurement. Fixed intervals make the predicted count
exact rather than distributional, so a disagreement of two is a disagreement rather than a
sample, which is what makes the law check able to fail. ADR-004 says what that costs.
