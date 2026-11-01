# Opportunities

A scan can return hundreds of findings. Nobody decides about 499 things one by
one, so Argus groups findings into **opportunities**: a short list of decisions,
each with one action, a savings range, and the full list of resources behind it.
The grouping is deterministic. No model is involved, so two runs on the same
findings always give the same opportunities.

!!! note "Prototype"
    Opportunities are in the JSON report (`opportunities`, `opportunity_summary`)
    and in `python -m core.opportunities`. The HTML report, Slack digest and
    ticket flow do not use them yet.

## How findings are grouped

The key is **action x resource family x tier**.

| Part | Values | How it is decided |
|------|--------|-------------------|
| Action | `remove`, `stop`, `rightsize`, `retention`, `review` | Rule findings are removals. Otherwise the first verb in the recommendation decides ("delete", "terminate", "release" are `remove`; "right-size", "downsize" are `rightsize`; "review", "verify", "confirm" are `review`). No verb means `review` |
| Family | the resource type, except all snapshot types share `snapshot` | |
| Tier | `flagged`, `unsure`, `sure` | `flagged` when the finding needs human review (production-like name or large unbilled estimate); `unsure` when its confidence is low or missing; otherwise `sure`. One doubtful member therefore cannot keep a whole group out of the easy lane |

Owners are **not** part of the key. Splitting by owner multiplied the group
count by more than two on a real scan. Each opportunity lists its top five
owners (from the `team`, `owner`, `project`, `application` or `service` tag, in
that order) and how many members have none.

## Small groups and the cap

Groups smaller than `min_group_size` (default 2) collapse into one **other
resources** opportunity per action and tier. If the list still has more than
`max_opportunities` (default 50), the minimum is raised until it fits. Every
finding is in exactly one opportunity, so totals never double count.

## Lanes

| Lane | Meaning |
|------|---------|
| `easy` | action is `remove`, `stop` or `retention`, and the tier is `sure` |
| `doubt` | everything else: `review` and `rightsize` actions, `unsure` and `flagged` tiers |

Easy opportunities are listed first, then by savings.

## Savings range

| Field | Meaning |
|-------|---------|
| `low_usd` | billed plus list-priced dollars: deterministic figures |
| `high_usd` | `low_usd` plus the model's estimates, taken at face value |
| `by_basis` | dollars per `cost_basis` |
| `unpriced` | members with no dollar figure; they are not in either bound |

The two bounds add up to the report's `total_estimated_waste_usd` (high) and to
its billed and list-priced part (low).

## Stable ids and related links

`id` is a hash of the key, so the same kind of opportunity keeps its id from one
scan to the next. Decisions recorded against an id therefore survive new scans.

`related` lists other opportunities whose findings name one of this opportunity's
resource ids in their reasoning (for example a stopped instance that mentions its
disk). It is a hint to check for overlap, not a guarantee.

## Measuring a report

```bash
python -m core.opportunities summary --report local_reports/aws/<date>/<scan>.json
python -m core.opportunities summary --report <scan>.json --list 10
```

Without `--list` only counts and dollars are printed, never resource names.
`--min-group-size` and `--max-opportunities` override the defaults.

## Limits

- The action comes from keywords in the recommendation text, so an unusual
  phrasing falls back to `review`.
- Relations between resources are found by id mentions only.
- Titles are plain templates. Richer text and risk notes come later.
