# ADR-001: Four caches, an origin that takes time, and no network

**Status.** Accepted.

## The decision

Everything runs in one process. The cache is a dictionary with a lock, the origin is a
function that sleeps, and the load is real threads against a real clock. There is no Redis
and no HTTP anywhere in it.

## Why that is enough

The mechanism is a window. While a refresh is in flight the cache has nothing to serve, and
every request that arrives inside the window goes to the origin as well. What makes the
window is that the origin takes time; what fills it is that requests keep arriving. Neither
of those needs a network to be real, and neither changes shape when one is added.

A real cache server would contribute its own latency, which widens the window a little, and
its own failure modes, which are a different subject. What it would take away is the ability
to state the arrival rate and the origin latency as numbers rather than measuring them, and
E1's whole claim is a relationship between those two numbers and a third.

## Why the origin sleeps rather than computing

A sleeping origin holds no lock, burns no CPU, and competes with nothing. On a two-core box
an origin that actually did work would have its concurrent calls fighting each other, and a
stampede of eleven would take longer than one call rather than the same time - which is
true of real systems and would confound the measurement of how many calls there were with
how expensive they became. The second effect is real and is named in ADR-004 rather than
being quietly folded into the first.

## Why four caches

Three of them are the standard advice, and they are not interchangeable:

- **Jitter** spreads expiry times so that keys filled together do not expire together. It
  is sound for that and does nothing for a single hot key, which E3 shows rather than
  asserts.
- **Single flight** lets one reader recompute while the others wait on it. It removes the
  stampede completely and leaves the stall.
- **Early recomputation** refreshes while the old value is still serveable, so there is
  never a moment with nothing to serve. It removes the stall as well, and pays in staleness.

The naive cache is included because it is what most code does, and because the other three
have nothing to be compared against without it.

## The second freshness check

Inside single flight, the entry is checked again after the lock is acquired. That check is
the entire mechanism. Without it, every reader that queued on the lock goes on to fetch
anyway, having waited for the privilege - which is strictly worse than the naive cache,
because the calls are now serialised as well as redundant. It is a two-line mistake and it
is easy to make.
