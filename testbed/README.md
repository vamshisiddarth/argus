# Argus testbed

Labelled test resources and a scoring tool, so every release can be measured instead of guessed at.

- `manifest.json` lists what is waste (10 resources in 8 classes) and what is a look-alike decoy (3 resources). Each resource has a logical id.
- `terraform/` creates those resources in a sandbox AWS account, each tagged `argus-testbed-id = <logical id>`.
- `python -m core.calibration score` reads an Argus scan report and the manifest and prints recall, precision, cost error, evidence completeness and run cost.
- `fixtures/` and `baseline.json` hold a **synthetic** report and its score, used by the offline test suite.

## What is real and what is not

| Part | Status |
|------|--------|
| Manifest, scoring tool, tests | real, run in CI (offline) |
| Terraform | validated (`terraform fmt`, `terraform validate`); **never applied** by this project yet |
| `fixtures/synthetic-scan.json` | hand-made, with two misses, one false positive and a few wrong prices on purpose. It tests the scorer. It says nothing about how accurate Argus is |
| `baseline.json` | the score of that synthetic fixture. It guards the scoring code, not Argus |
| A real baseline | needs a real run (steps below) in a sandbox account; not recorded yet |

## Classes

| Class | Resource | Approx. cost while it exists |
|-------|----------|------------------------------|
| unattached_volume | 2 gp3 volumes, attached to nothing | $1.60 and $8.00 per month |
| stopped_instance | t3.micro stopped, root disk bills | $0.64 per month |
| unassociated_eip | 2 addresses attached to nothing | $3.65 each per month |
| overprovisioned_iops | gp3, 6,000 IOPS and 250 MB/s, no I/O | about $28 per month |
| log_group_no_retention | log group that never expires | cents |
| idle_nat (costly) | NAT gateway, no traffic | about $33 per month |
| idle_lb (costly) | internal load balancer, no targets | about $16 per month |
| idle_client_vpn (costly) | Client VPN endpoint with one association, no users | about $73 per month |

Decoys: an attached volume, an address attached to a running instance, a log group with 30-day retention. They are in use by structure, not by load, so a finding on one counts against precision; review ambiguous cases by hand.

Prices are approximate us-east-1 list prices (730 hours a month) and exist to size the cost-error metric. A running host instance (t3.micro) also exists to carry the attached volumes and the in-use address; it is untagged, so findings on it are counted as "outside the testbed" and are not scored.

## Run it

Use a sandbox account that holds nothing else. The Terraform refuses to run in any other account.

```bash
cd testbed/terraform
terraform init
terraform apply -var sandbox_account_id=<12-digit sandbox id>
# costly classes: add -var enable_costly_classes=true
# client VPN: also pass the two ACM certificate ARNs (variables.tf)
```

Idle detection looks at metrics, which need time. Let the resources age, or scan with a short window, for example `--lookback-days 3`. Then:

```bash
argus scan --cloud aws --ai-provider <provider> --expect-account <sandbox id> \
  --lookback-days 3 --llm-budget 2
python -m core.calibration score \
  --report local_reports/aws/<date>/<scan>.json \
  --manifest testbed/manifest.json \
  --exclude-class idle_nat --exclude-class idle_lb --exclude-class idle_client_vpn \
  --json scorecard.json --md scorecard.md
terraform destroy -var sandbox_account_id=<id>
```

Pass `--exclude-class` for every class you did not deploy (`terraform output deployed_classes_to_exclude` lists them). Add `--baseline <earlier scorecard.json>` to fail (exit 1) when recall, per-class recall, precision, verified share or mean cost error get worse.

## Metrics

| Metric | Meaning |
|--------|---------|
| Recall | waste resources that got a finding, over all waste resources deployed |
| Precision | waste found over waste found plus decoys flagged |
| Cost error | relative error of the finding's dollars against `expected_monthly_usd`; unpriced findings are counted separately, not as zero error |
| Verified share | share of true-positive dollars with a billed basis |
| Evidence complete | true positives backed by metrics or a deterministic rule |
| Class targets | `target_recall` per class in the manifest; proposals, not measurements |

## Keep the pieces in step

`tests/test_testbed.py` fails if the manifest ids and the Terraform tags differ, if the fixture is older than the report schema, or if the fixture scores worse than the baseline. After a report schema change:

```bash
python testbed/fixtures/make_synthetic_scan.py
python -m core.calibration score --report testbed/fixtures/synthetic-scan.json \
  --manifest testbed/manifest.json --json testbed/baseline.json
```

## Not done yet

- A real run and a real baseline (needs a sandbox account).
- Replaying a recorded cloud so the engine itself can run offline in CI; today CI scores a fixed report, not a fresh scan.
- Grouping quality metrics (arrive with opportunity grouping).
