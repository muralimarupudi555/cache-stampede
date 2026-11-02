# ADR-004: What this cannot measure

**Status.** Accepted. Read this before quoting any figure from here.

## A stampede of eleven is not eleven times the cost

The origin here sleeps. It holds no lock, burns no CPU, and eleven simultaneous calls take
exactly as long as one. A real origin under eleven concurrent requests is slower per
request than under one, which means the window widens, which means more requests arrive
inside it, which means the stampede is larger than `1 + λd` predicts.

So the derivation is a floor, not a ceiling, and the feedback loop it leaves out is exactly
the one that turns a spike into an outage. Measuring that properly needs an origin with a
real concurrency response, and this does not have one.

## Scheduled arrivals are not real arrivals

Requests arrive at exact intervals. Real traffic clusters, and a cluster landing on an
expiry produces a bigger stampede than the average rate predicts. The derivation is the
expectation either way; what is missing is the spread, and the tail of that spread is what
an incident is made of.

This was a deliberate trade, argued in ADR-002: fixed intervals make the predicted count
exact rather than distributional, which is what lets the law check fail on a disagreement of
two rather than shrug at it.

## One process, no network, no eviction

There is no cache server, so there is no cache-server latency widening the window, no
connection pool between the application and the cache, and no network partition pretending
to be an expiry.

There is also no eviction. Every entry here leaves the cache because its time to live ran
out. A real cache under memory pressure evicts entries early and unpredictably, and an
eviction has exactly the same effect as an expiry while being invisible to every TTL
setting. A key that is being evicted rather than expiring will stampede on a schedule
nobody configured.

## Several keys are only glanced at

E3 runs twenty keys to make a point about jitter and nothing else. Real caches have a long
tail of keys with wildly different rates, and the interesting questions there - which keys
deserve coalescing, what a shared lock table costs, what happens when the hot key changes -
are not asked here.

## Early recomputation's staleness is counted, not judged

The report counts the values served while a refresh was in flight: **48 values served** in
the headline run. Whether that is acceptable is a question about the data, not about the
cache, and nothing here can answer it. A stale price is a different problem from a stale
article.

## Single flight across processes is a different mechanism

The single flight here is a lock in one process. Across a fleet, every instance has its own
lock, so a stampede of eleven becomes one call per instance rather than one call in total,
and getting to one needs a distributed lock with all of that entails. The reduction measured
here is the within-process one.

## What is left standing

That the stampede is the arrival rate times the refresh duration, that the time to live does
not appear in it, that the hit rate is structurally unable to show it, that jitter addresses
synchronised keys rather than hot ones, and that coalescing changes the arithmetic rather
than the tuning. Those follow from the shape of the window and survive every gap above.
