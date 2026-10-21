# Minimal read-only role for running Argus scans.
# Attach a trust policy that lets your scheduler (Lambda, CI, a person) assume it.

variable "trusted_principal_arns" {
  type        = list(string)
  description = "Principals allowed to assume the Argus scan role."
}

resource "aws_iam_role" "argus_scan" {
  name = "argus-read-only-scan"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = var.trusted_principal_arns }
    }]
  })
}

resource "aws_iam_role_policy" "argus_scan" {
  name = "ArgusReadOnly"
  role = aws_iam_role.argus_scan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "resource-explorer-2:Search",
        "resource-explorer-2:GetView",
        "resource-explorer-2:GetDefaultView",
        "resource-explorer-2:ListViews",
        "resource-explorer-2:ListIndexes",
        "resource-explorer-2:GetIndex",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "ce:GetCostAndUsage",
        "ce:GetCostAndUsageWithResources",
        "cloudtrail:LookupEvents",
        "ec2:DescribeInstances",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "elasticache:DescribeCacheClusters",
        "elasticache:DescribeReplicationGroups",
        "redshift:DescribeClusters",
        "es:DescribeDomain",
        "lambda:GetFunctionConfiguration",
        "dms:DescribeReplicationInstances",
        "sts:GetCallerIdentity",
      ]
      Resource = "*"
    }]
  })
}
