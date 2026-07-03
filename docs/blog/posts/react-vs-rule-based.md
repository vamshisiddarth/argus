---
date: 2026-07-07
authors:
  - vamshisiddarth
categories:
  - Engineering
  - AI
tags:
  - ai
  - cloud-cost
  - finops
  - aws
  - architecture
description: >
  Most cloud cost tools flag idle resources using static thresholds. We tried that first and it kept getting things wrong. Here is why we switched to a ReAct agent loop instead.
---

# Why we use a ReAct loop instead of rules for idle resource detection

![Why rules break and what we did instead](../../assets/images/blog/hero-react-vs-rules.svg)

Most cloud cost tools work off rules. If CPU stays below 5% for seven days, flag the instance as idle. If a volume has zero read operations for thirty days, flag it as unused. These rules are simple, fast, and easy to audit. We tried this approach first when building [Argus](https://github.com/vamshisiddarth/argus). It kept getting things wrong.

This post explains what the problem actually is, what a ReAct loop is, and the specific tradeoffs we accepted by going down this path.

<!-- more -->

## What rules look like in practice

Here is a small slice of what a rule-based idle detector needs to handle for just five resource types:

| Resource | Rule |
|---|---|
| EC2 instance | CPU &lt; 5% for 7 days |
| RDS instance | connections = 0 for 14 days |
| NAT Gateway | bytes transferred &lt; 1 MB/day |
| Lambda function | invocations &lt; 10/month |
| EBS volume | read/write ops = 0 for 30 days |

This looks manageable until you add more resource types. AWS alone has over 200 resource types that can show up in a real account. GCP and Azure add hundreds more. Each one needs its own rule, its own metric, its own threshold, and its own exception list.

But the bigger problem is not scale. It is that "idle" is context-dependent in ways a static rule cannot express.

## The context problem

Take a NAT Gateway moving 500 KB per day. The rule says: flag it, that is too low. But:

- Is it a VPN tunnel that carries low-volume management traffic to on-premise systems? Then it is not idle, it is load-bearing.
- Is it attached to a subnet with no active instances since a migration six months ago? Then it is completely orphaned.
- Does it have an `environment=prod` tag and an owner from the platform team? Different action than one tagged `environment=dev` with no owner.

The bytes metric alone cannot tell you which scenario you are in. You need to look at the routing table, the subnet, the tag, the CloudTrail history, and the cost trend together. A rule cannot do that. It can only look at one metric at a time.

This is not a corner case. It comes up constantly in real accounts. The monthly reporting job that runs once a month and looks idle every other week. The RDS read replica that has zero connections because it exists as a failover, not for active use. The Lambda function invoked three times a month that sends critical billing notifications.

Rules have no way to distinguish these from genuinely dead resources. So they either produce false positives that erode trust, or you add so many exceptions that the rules stop doing anything useful.

## What a ReAct loop is

ReAct stands for Reason and Act. It is a pattern for AI agents where the model alternates between reasoning about what to do next and calling a tool to gather more information.

![The ReAct loop](../../assets/images/blog/react-loop.svg)

In Argus, the loop works like this:

1. The AI receives a list of all resources in your account along with their types, regions, and tags.
2. It picks a resource that looks worth investigating and calls `get_metrics()` to fetch the last 14 days of CloudWatch data.
3. It reads the metrics, adds them to its context, and decides whether to look further. It might call `get_cost()` to check what the resource is actually spending, or `get_last_activity()` to check CloudTrail for the last time a human or system touched it.
4. It keeps going until it has enough information to make a judgment, then writes a finding in plain language with its reasoning, a cost estimate, and a recommendation.

The loop exits when the AI decides it has investigated enough resources. It does not need to check every resource. It reasons about which ones warrant deeper investigation, the same way a senior engineer would skim a list of resources and immediately know which ones to look at first.

## How signals combine

Here is a concrete example of what this looks like for a single resource:

![Combining signals](../../assets/images/blog/signal-combination.svg)

The AI sees all five signals together. It knows that 847 bytes of network traffic over 14 days is essentially nothing. It knows that 73 days without human activity is a long time. It knows $94.20 per month is real money. It knows the team=backend tag means it should call out the owner. No single signal would have been enough. Together, they add up to a clear finding.

A rule checking bytes transferred would have flagged this correctly, but it would have also flagged the VPN tunnel next to it. The AI can read the routing table context and distinguish the two. A rule cannot.

## The actual tradeoffs

This approach is not free. Here is what we gave up:

**Determinism.** Two scans of the same account might produce slightly different findings if resource states are borderline. We set `temperature=0` and prompt the model to cite specific metrics in every finding, which makes its reasoning auditable and significantly reduces variance. But it is not zero.

**Speed.** The agent loop takes longer than a rule check. Rules run in milliseconds. A full Argus scan takes two to four minutes depending on account size. For a weekly report this is fine. For something you want to run on every deployment it is not.

**Cost.** Each scan uses one batched AI API call. On AWS we use Bedrock. A typical scan costs around $0.24 in API usage. Across 52 weeks that is about $12.50 per year per account. For the context: a single overlooked idle NAT Gateway costs $32/month.

**Debuggability.** When a rule fires, you know exactly why. When the AI flags a resource, you have to read its reasoning. We require the AI to include specific metric values in every finding, so you can verify the logic. But it is more work to audit than a threshold check.

What we got in return: we do not write rules. We do not maintain thresholds per resource type. We do not build exception lists. The same agent works across AWS, GCP, and Azure without any cloud-specific idle logic. When AWS releases a new resource type, the agent can reason about it immediately using whatever metrics are available, without any code changes.

## What this means if you want to extend Argus

The core of Argus is the agent loop in [`core/agent/loop.py`](https://github.com/vamshisiddarth/argus/blob/main/core/agent/loop.py). It calls four methods on a cloud adapter: `list_resources`, `get_metrics`, `get_cost`, and `get_last_activity`. That is the full contract.

If you want to add a new cloud, you implement those four methods. If you want to improve the analysis, you edit the system prompt in [`core/agent/prompts.py`](https://github.com/vamshisiddarth/argus/blob/main/core/agent/prompts.py). Nothing else needs to change.

The adapter pattern and the AI reasoning are deliberately separated so that each can be swapped out independently. You could replace Claude with GPT-4o or Gemini by implementing a different AI provider. You could add a new cloud by writing a new adapter. The core loop stays the same either way.

---

If you want to try it on your own account, the [quickstart](https://vamshisiddarth.github.io/argus/getting-started/quickstart/) takes about ten minutes. The source is on [GitHub](https://github.com/vamshisiddarth/argus). Feedback and PRs welcome.
