# Future builds: what this becomes

Nine items, ordered by what I would build first. Each one names what it needs to be safe, because the point of writing this down is to show the next step was designed rather than hoped for. Nothing here is built. This is a plan for Momentive Software to argue with, not a roadmap I am asking anyone to accept.

## 1. The golden set that grows itself

Today the golden set is seven hand written assertions, and I wrote all seven, which is the weakness. In production three feeds grow it without me: every human correction to a digest becomes a labelled example, every rejected claim becomes a negative case, and every production incident becomes a permanent regression test. The set is versioned in the store repository, so the eval history is as auditable as the digest history and you can see which run a case entered on.

**What it needs to be safe:** a correction mechanism on the digest surface, which is item 5. Without somewhere for a human to say "this one is wrong", there are no corrections to learn from and the set only grows from incidents, which is the expensive way to find out.

## 2. The adaptive eval agent, gated

A scheduled agent reads the run logs and the corrections, finds the intents whose pass rate is sliding, and proposes prompt or context changes. It opens a pull request. It does not merge. That is the honest version of an adaptive agent: the adaptation is real, the gate is real, and the gate is a pull request because that is a control the team already has and already trusts, rather than a new approval surface nobody wants to own.

**What it needs to be safe:** per intent scoring, which means the golden set has to be labelled by intent rather than only by pass or fail. An agent that can only see an aggregate pass rate cannot tell you what to change, so it will guess.

## 3. Trust tiers on the filing gate

The approval gate is binary today: the agent proposes and a human files. The path from there is the one worth running anywhere. Tier one, propose only. Tier two, draft into an approval queue where a human signs off. Tier three, file directly within a named scope and a named budget. Nothing reaches tier three without having lived at tier two and produced a measured record there. Widen on evidence, never on time served.

**What it needs to be safe:** the acceptance rate of proposals tracked per theme type, so that widening is a number someone can point at rather than a feeling that things have been going well.

## 4. Drift detection as a scheduled job rather than a reported metric

Per intent pass rates on a schedule with an alert when one slides, plus a week over week comparison of this digest's themes against last week's. The failure mode to design against is not an error. It is a digest that looks completely normal and is quietly missing a day of calls, which nobody notices because it reads fine. So the alert fires on thin runs, not only on failed ones.

**What it needs to be safe:** a recorded expectation of volume per source per day, so "thin" is defined against something. Without that, a genuinely quiet week and a broken connector look identical.

## 5. A feedback surface for the product team

The digest is read only today. The next version lets a product manager mark a theme as useful, wrong, or already known, and that signal becomes a labelled example the moment it is given. This is the single highest value addition on this list, because it is the only one that closes the loop between what the agent thinks matters and what actually mattered.

**What it needs to be safe:** the signal has to be attributed and reversible, so a correction can be traced to who made it and undone when they change their mind. A labelled example nobody can attribute is a labelled example nobody will trust six months later.

## 6. Retrieval when the theme index outgrows layer one

The index is small enough to load in full today, which is the only reason it is a file. When it stops fitting comfortably, themes move behind a retrieval tool with citations required, and retrieval gets evaluated separately from generation: a golden set of questions paired with the documents that should have been retrieved, scored before the model ever answers. I would name the threshold rather than the technology, because the threshold is the part that decides when, and the technology by then will not be the one I would pick today.

**What it needs to be safe:** retrieval scored on its own before it is wired in. A retrieval layer that is only measured through the quality of the final answer hides its misses inside a fluent paragraph.

## 7. More sources, same contract

Zendesk, Intercom, community forums, NPS verbatims, win and loss notes. Each one is a connector implementation against the existing protocol, and the pipeline does not change. The ingestion is not the interesting problem. The interesting problem is entity resolution across sources: the same organization under two names after an acquisition, which is the vocabulary reconciliation trap generalized from features up to accounts.

**What it needs to be safe:** an account resolution step that is deterministic and reviewable, with the merges it performs written to the audit log. Two accounts silently becoming one is a change to every number downstream of it, so it should never happen inside a model call.

## 8. Cost work that does not trade quality

Batch the nightly extraction, which is not latency sensitive and is half price. Cache the theme index prefix across the week, since it is the most reused context in the system. Both are free wins before any model downgrade is considered, and the order matters: cheap wins first, quality tradeoffs last and only against a measurement.

**What it needs to be safe:** the swap comparison already in the repository, so that a downgrade has to show its cost saving next to its eval pass rate and its theme assignment overlap before anyone accepts it. A cost number on its own is not an argument.

## 9. The approval queue as a real surface

`approve` is a CLI because a CLI is honest about what a prototype is. In production the queue is where a product owner spends two minutes a week, and the queue's own metrics are the clearest read on whether the agent is earning its place: how many proposals, how many accepted, and how long they sat before anyone looked.

**What it needs to be safe:** the queue's decisions feeding item 1 and item 3. A rejection that does not become a labelled example and does not move the trust tier is just a click, and a queue that only collects clicks stops getting opened.
