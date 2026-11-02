# cache-stampede

**A time to live is not a load-smoothing knob. It is a clock that tells every concurrent
reader of a key to miss at exactly the same moment — and the size of the resulting spike
does not depend on the time to live at all.**

While a refresh is in flight the cache has nothing to serve, so every request arriving in
that window goes to the origin too. With arrivals at rate `λ` and an origin that takes `d`
seconds, that is:

```text
origin calls per refresh = 1 + λd
```

There is no `T` on the right-hand side. At **200 requests a second** against **an origin
taking 50 ms**, **11 requests reach it at once** every time the key turns over — while the
hit rate for the same run reads over ninety percent.

## E1. The stampede is the rate times the latency

Sweeping each term independently, every measurement lands on the derivation exactly. These
are counts of scheduled arrivals, not samples, so "close" would mean something was wrong.

<!-- table:e1 -->
```text
     rate    origin   stampede   derived    peak   hit rate
-----------------------------------------------------------
    100/s      50ms        6.0         6       6     90.33%
    200/s      50ms       11.0        11      11     90.83%
    400/s      50ms       21.0        21      21     91.33%
    800/s      50ms       41.0        41      42     91.42%
    200/s      20ms        5.0         5       5     95.00%
    200/s      50ms       11.0        11      11     91.00%
    200/s     100ms       21.0        21      21     82.67%
    200/s     200ms       41.0        41      41     72.83%
```
<!-- /table:e1 -->

**At 800 requests a second** the stampede **becomes 41**. With the rate held still and **an
origin at 200 ms** it is **also 41** — the two terms are interchangeable, which is the
uncomfortable part: a slow dependency is punished twice, once for being slow and again
because being slow widens the window in which everyone else misses too.

Across the whole sweep the hit rate **never fell below 72.8%** and ran **as high as 95.0%**.

## E2. Turning the TTL up improves everything except the spike

The derivation has no TTL term, so the time to live can only change how *often* the window
opens. Sweeping it:

<!-- table:e2 -->
```text
     ttl   stampede   derived   refreshes    calls   hit rate
-------------------------------------------------------------
   0.25s       11.0        11          29      316     84.20%
   0.50s       11.0        11          17      181     90.95%
   1.00s       11.0        11          10      110     94.50%
   2.00s       11.0        11           5       54     97.30%
```
<!-- /table:e2 -->

Going **from 0.25 seconds** **to 2 seconds**, the hit rate **climbed from 84.2%** **to a hit
rate of 97.3%**, **316 origin calls** came **down to 54** — **5.9x fewer calls** — and the
stampede **stayed at 11 calls** per refresh at every single setting.

That is the trap. An operator lengthens the TTL, watches the hit rate improve and total
origin traffic fall, concludes the cache is now working, and has not touched the height of
the spike that was knocking the origin over. The incident simply becomes rarer, which also
makes it harder to catch and easier to blame on something else.

## E3. Three fixes, and what each actually removes

<!-- table:e3 -->
```text
cache               per refresh   calls   made to wait   hit rate   stale
-------------------------------------------------------------------------
naive                      11.0     110          9.17%     90.83%       0
jittered                   11.0     109          9.08%     90.92%       0
single_flight               1.0      11          5.50%     99.08%       0
early_recompute             1.0      12          1.75%     99.00%      48
```
<!-- /table:e3 -->

**Jitter does nothing here and the measurement says so.** A plain TTL **admits 11 calls per
refresh** on one hot key and **jitter gives 11**. A single key has one expiry however that
expiry was chosen; spreading it moves the stampede without shrinking it.

**Single flight collapses it to one call** and leaves the stall: it **made 5.50% of requests
wait** on the reader doing the work.

**Early recomputation collapses it too and removes the stall**, taking those waits **to
1.75%** — **3.1x fewer requests** — because it refreshes while the old value is still
serveable instead of after it has gone. It pays in staleness: **48 values served** during
refreshes in that run.

Jitter does have a case, and it is a different one. Against **20 keys filled together** —
what a deploy, a flush or a cold start produces — a plain TTL **peaks at 69 simultaneous**
origin calls and jitter takes it **down to 16 simultaneous**, a **4.31x reduction**. An
earlier version of this experiment measured jitter against keys that had drifted apart on
their own and found it barely helped, which was a true measurement of the wrong scenario;
[ADR-003](docs/adr/ADR-003-three-scenarios-that-had-to-be-built-right.md) records how that
was found.

So the three are not alternatives:

| problem | fix |
| --- | --- |
| many keys expiring together | jitter the TTL |
| one hot key hammering the origin | single flight |
| one hot key, and the stall matters too | early recomputation, at the cost of staleness |

## Why the hit rate cannot see any of this

Over a run of `D` seconds there are `D / (T + d)` refreshes and `λD` requests, so the miss
rate is `(1 + λd) / (λ(T + d))`. **At 1000 requests a second** against the same fifty
millisecond origin, with **a 60 second TTL**, that is under a tenth of a percent — **a hit
rate of 99.92%** while the origin takes **51 simultaneous calls** every minute.

Every number on the cache dashboard is excellent. The thing behind it is being knocked over
on a schedule. The only instrument that shows it is the count of simultaneous calls at the
origin, over a window about as short as the origin's own latency; widen that window and the
spike averages into a rate that looks fine.

## How the numbers are kept honest

The derivation is written before any measurement and never fitted to one.
`tools/check_laws.py` re-derives it on every `make verify` and checks it against the
committed results, so the published counts stay checkable on a machine that has never run
the load. It was run against tampered results before being trusted.

The load is driven **open loop** — arrivals scheduled in advance and dispatched when due —
because a closed loop with `C` workers cannot put more than `C` requests into a stall and
would report a stampede of `C` at every rate.
[ADR-002](docs/adr/ADR-002-an-open-loop-and-a-pool-that-never-filled.md) argues it, and
every run records whether the thread pool ever ran out of workers, because an open loop with
too few workers is a closed loop wearing an open loop's clothes.

Three measurements here were wrong first — a divisor that assumed the wrong refresh cycle,
jitter tested against the wrong scenario, and a maximum used where a median belonged — and
all three are written up in
[ADR-003](docs/adr/ADR-003-three-scenarios-that-had-to-be-built-right.md). None was caught
by a test.

## What this cannot measure

Read [ADR-004](docs/adr/ADR-004-what-this-cannot-measure.md) first. The most important
omission:

- **A stampede of eleven is not eleven times the cost.** The origin here sleeps, so eleven
  simultaneous calls take as long as one. A real origin gets slower under concurrency, which
  widens the window, which admits more requests — and `1 + λd` is therefore a floor. The
  feedback loop left out is exactly the one that turns a spike into an outage.
- **No eviction.** Every entry here leaves because its TTL ran out. A real cache under
  memory pressure evicts early and unpredictably, and an eviction has the same effect as an
  expiry while being invisible to every TTL setting.
- Arrivals are scheduled, not clustered. The derivation is the expectation; the spread
  around it is missing, and the tail of that spread is what an incident is made of.
- Single flight here is a lock in one process. Across a fleet it gives one call per
  instance, not one call in total.

## Running it

`make verify` is the gate: lint, **85 tests**, the law check and the number check.

```bash
make install
make verify
make bench      # the three experiments, a couple of minutes
```

A single run, with the exit code as the interface:

```bash
cache-stampede --cache naive --request-rate 200 --origin-seconds 0.05
```

| exit | meaning |
| --- | --- |
| 0 | one origin call per refresh — the stampede is gone |
| 2 | the scenario cannot show a stampede |
| 3 | the run did not complete |
| 4 | everybody missed at once when the key expired |
| 5 | the pool saturated, or the count misses the derivation |

Real transcripts are in [docs/cli-output.md](docs/cli-output.md).

## Layout

```text
src/cache_stampede/
  config.py    scenario validation that refuses runs which cannot show a stampede
  theory.py    the stampede factor, derived before any measurement
  origin.py    a slow dependency that counts calls and clusters them into refreshes
  caches.py    plain TTL, jittered, single flight, early recomputation
  harness.py   open-loop load, and the check that the pool was never the limit
  report.py    verdict, plus the refusal to publish a saturated run
  cli.py       exit codes
experiments/   the three experiments above
tools/         metric collection, the two checkers, the tables, the transcripts
docs/adr/      four decision records, including three mistakes and their fixes
```

## How this was built

This repository was built by Murali Marupudi working with Claude, an AI assistant, as a
pair-programming partner. The claim, the experimental design, the decisions about what to
measure and what to throw away, and the judgement calls recorded in the decision records are
the author's. Claude was used for implementation, for argument, and as a second pair of eyes
on the measurements.

## Licence

MIT. See [LICENSE](LICENSE).
