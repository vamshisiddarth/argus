output "resource_ids" {
  description = "Logical testbed id to cloud resource id, for matching a scan by hand."
  value = merge(
    {
      "w-unattached-vol-1"         = aws_ebs_volume.unattached_1.id
      "w-unattached-vol-2"         = aws_ebs_volume.unattached_2.id
      "d-attached-vol-1"           = aws_ebs_volume.attached.id
      "w-overprov-iops-1"          = aws_ebs_volume.overprovisioned.id
      "w-stopped-instance-1"       = aws_instance.stopped.id
      "w-unassociated-eip-1"       = aws_eip.unassociated_1.id
      "w-unassociated-eip-2"       = aws_eip.unassociated_2.id
      "d-associated-eip-1"         = aws_eip.associated.id
      "w-log-group-no-retention-1" = aws_cloudwatch_log_group.no_retention.name
      "d-log-group-retention-1"    = aws_cloudwatch_log_group.with_retention.name
    },
    { for r in aws_nat_gateway.idle : "w-idle-nat-1" => r.id },
    { for r in aws_lb.idle : "w-idle-lb-1" => r.arn },
    { for r in aws_ec2_client_vpn_endpoint.idle : "w-idle-client-vpn-1" => r.id },
  )
}

output "deployed_classes_to_exclude" {
  description = "Classes to pass to --exclude-class when scoring this deployment."
  value = concat(
    var.enable_costly_classes ? [] : ["idle_nat", "idle_lb"],
    local.client_vpn ? [] : ["idle_client_vpn"],
  )
}
