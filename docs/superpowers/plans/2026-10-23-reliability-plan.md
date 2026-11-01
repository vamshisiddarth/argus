# Argus 0.7.0 reliability plan (gap analysis + build order)

Goal: a report a customer can rely on. Cheaper, correct, complete, repeatable. No scope limit; the release is cut when a customer re-test passes.

## Evidence (all measured on the customer's real 1000-resource run and on live accounts)

| # | Gap | Evidence | Effect |
|---|-----|----------|--------|
| G1 | Resource Explorer types (`ec2:natgateway`) are never mapped to registry/CloudFormation types (`AWS::EC2::NatGateway`) | 0 of 101 real types recognised by the registry, by `_is_billable`, or by the CloudWatch metric table | Baseline rules never fire, metric tables unused (falls back to ListMetrics), remediation policies never match, display names raw. The model silently translated names. |
| G2 | Billable filter is dead for the same reason | 0 types dropped; 192 ECS task definitions, 167 security-group rules, 63 ENIs, 25 subnets, 23 IAM roles ... in the inventory | Free config objects consume the analysis cap and the LLM budget |
| G3 | ReAct loop re-sends a growing conversation every turn | 809 input tokens per resource, $0.0033-$0.0045 per resource | 1000 resources ~ $4; coverage capped at 200 |
| G4 | Budget abort discards model work | `loop.py` returns only rule findings on `BudgetExceededError` | Money spent, findings lost |
| G5 | Cap picks types alphabetically when cap < number of types | 101 types, cap 200 worked; cap 40 would not | Arbitrary coverage |
| G6 | Cost figures are the model's guess | `cost_basis: estimated`, no price catalog | Headline dollars not reproducible |
| G7 | Waste classes with no metric signal are not checked | unattached EBS volumes, unassociated Elastic IPs, stopped instances | Obvious waste missed |
| G8 | Resource Explorer: 1000 results per query, tags need a view | `discovery_complete`, P5/P6 warnings | Inventory and exemption tags can be missing |
| G9 | Findings carry no evidence block | HTML shows the model's prose | Humans cannot verify quickly |

## Build order

**P0 correctness foundation**
1. `adapters/aws/type_map.py`: explicit Resource Explorer -> registry type map; `Resource` keeps the native type; normalise at discovery.
2. Billable/config classification on real names (and cfn-style names).
3. Prove on the real customer type list: every type either recognised, classified free, or explicitly "other".

**P1 evidence pipeline (the cost and completeness fix)**
1. Collect evidence for every remaining resource in code (metrics, cost, activity where useful), in parallel.
2. One stateless LLM call per batch of evidence (no growing history), tool-forced `submit_findings`, split-and-retry on cut-off.
3. Pre-run estimate, risk-ranked order, wrap-up before the budget, never discard findings, exact "not analysed because" accounting.
4. `ARGUS_ENGINE=pipeline` (default) / `react` (legacy, used by chat).

**P2 deterministic waste classes**
Price catalog (list prices, labelled `list_price`), AWS state collectors (EBS available, EIP unassociated, stopped EC2), rules for each, IAM for the new Describe calls.

**P3 discovery**
Split a full region query by service/type to pass 1000; tag fallback through the Resource Groups Tagging API when the view has no tags.

**P4 evidence in the report**
Per-finding evidence block (JSON + HTML), cost breakdown by `cost_basis`, estimate printed before spend.

**P5 validation**
Offline eval harness from the real customer type distribution (ground-truth idle set), repeated-run determinism test, live runs on the personal account, then customer re-test.

## Definition of done
- A scan of the customer's real inventory shape costs well under half of today's, analyses every cost-bearing resource, and two runs agree.
- No path discards paid-for results.
- Every number in the headline is labelled billed / list price / model estimate.
- Each finding shows the evidence it rests on.
