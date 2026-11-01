# Baseline Rules

Argus asks the model to judge resources, but a few cases are obvious enough that
the answer should not depend on the model's mood. These are **deterministic
baseline rules**: they run before the model, over every discovered resource of
the matching type (they ignore the `MAX_RESOURCES_PER_SCAN` cap), and their
findings win over the model's for the same resource. Two runs on the same
account therefore always agree on them.

The first three rules read CloudWatch metrics; the last three read the resource's current configuration with read-only EC2 `Describe*` calls (`ec2:DescribeVolumes`, `ec2:DescribeAddresses`, `ec2:DescribeInstances`). A rule only fires on data Argus actually received. A resource with no
data, or a failed metrics call, is never reported by a rule (the model may still
look at it, with low confidence).

| Rule id | Resource | Fires when (over the metrics window) | List price used |
|---|---|---|---|
| `nat-gateway-idle` | NAT gateway | Under 1 MiB in and out combined | $32.85/month |
| `alb-no-requests` | Application Load Balancer (ARN contains `/app/`) | 0 requests and 0 active connections | $16.43/month |
| `classic-elb-no-requests` | Classic Load Balancer | 0 requests | $18.25/month |
| `ebs-volume-unattached` | EBS volume | State is `available` (not attached to anything) | size x type price, for example 100 GiB gp3 = $8.00/month |
| `elastic-ip-unassociated` | Elastic IP | Not associated with an instance or network interface | $3.65/month |
| `ec2-instance-stopped` | EC2 instance | State is `stopped` (its attached volumes still bill) | sum of attached volumes; confidence `medium`, no finding if the cost is 0 |

List prices are us-east-1 hourly rates x 730 hours, excluding data processing.
When Cost Explorer returns a billed cost for the resource, that replaces the list
price and the finding's `cost_basis` is `billed`; otherwise it is `estimated`.

Each rule finding has `detected_by: "rule:<id>"`, `confidence: "high"` (a
window under 90 days caps it at `medium`), and a recommendation that tells you
what to check before deleting (for example route tables that still point at a
NAT gateway).

Rules are on by default. Set `ARGUS_BASELINE_RULES=false` to turn them off.
Coverage counts a resource as analysed once a rule has evaluated it.
