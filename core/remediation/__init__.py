# ruff: noqa: E501
"""Registry-driven remediation command templates.

Maps (type_id, action) → concrete CLI command strings.
Commands use ``{resource_id}`` and ``{region}`` as placeholders that callers
fill in at render time via :func:`get_command`.

No cloud SDK imports — pure Python string templates.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Command templates
# Keys: type_id (matches registry) → action → CLI template string.
# Placeholders: {resource_id}, {region}, {account_id} — filled by get_command().
# ---------------------------------------------------------------------------
_COMMANDS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ AWS
    "AWS::EC2::Instance": {
        "stop": "aws ec2 stop-instances --instance-ids {resource_id} --region {region}",
        "delete": (
            "aws ec2 terminate-instances --instance-ids {resource_id} --region {region}"
        ),
        "resize": (
            "aws ec2 modify-instance-attribute --instance-id {resource_id} "
            "--instance-type Value=<new_type> --region {region}"
        ),
        "convert_spot": (
            "# 1. Create AMI from instance\n"
            "aws ec2 create-image --instance-id {resource_id} --name argus-spot-ami --region {region}\n"
            "# 2. Launch replacement Spot instance from AMI\n"
            "aws ec2 run-instances --image-id <ami-id> --instance-market-options MarketType=spot "
            "--instance-type <type> --region {region}"
        ),
    },
    "AWS::RDS::DBInstance": {
        "stop": (
            "aws rds stop-db-instance --db-instance-identifier {resource_id} --region {region}"
        ),
        "delete": (
            "aws rds delete-db-instance --db-instance-identifier {resource_id} "
            "--skip-final-snapshot --region {region}"
        ),
        "resize": (
            "aws rds modify-db-instance --db-instance-identifier {resource_id} "
            "--db-instance-class <new_class> --apply-immediately --region {region}"
        ),
        "snapshot_delete": (
            "aws rds delete-db-snapshot --db-snapshot-identifier {resource_id} --region {region}"
        ),
    },
    "AWS::RDS::DBCluster": {
        "stop": (
            "aws rds stop-db-cluster --db-cluster-identifier {resource_id} --region {region}"
        ),
        "delete": (
            "aws rds delete-db-cluster --db-cluster-identifier {resource_id} "
            "--skip-final-snapshot --region {region}"
        ),
        "resize": (
            "aws rds modify-db-cluster --db-cluster-identifier {resource_id} "
            "--db-cluster-instance-class <new_class> --apply-immediately --region {region}"
        ),
        "reduce_replicas": (
            "aws rds delete-db-instance --db-instance-identifier <replica_id> "
            "--skip-final-snapshot --region {region}"
        ),
    },
    "AWS::Lambda::Function": {
        "delete": (
            "aws lambda delete-function --function-name {resource_id} --region {region}"
        ),
        "resize": (
            "aws lambda update-function-configuration --function-name {resource_id} "
            "--memory-size <mb> --region {region}"
        ),
    },
    "AWS::ElastiCache::CacheCluster": {
        "delete": (
            "aws elasticache delete-cache-cluster --cache-cluster-id {resource_id} --region {region}"
        ),
        "resize": (
            "aws elasticache modify-cache-cluster --cache-cluster-id {resource_id} "
            "--cache-node-type <new_type> --apply-immediately --region {region}"
        ),
        "stop": (
            "# ElastiCache doesn't support pause — delete then recreate to save cost\n"
            "aws elasticache delete-cache-cluster --cache-cluster-id {resource_id} --region {region}"
        ),
    },
    "AWS::Redshift::Cluster": {
        "delete": (
            "aws redshift delete-cluster --cluster-identifier {resource_id} "
            "--skip-final-cluster-snapshot --region {region}"
        ),
        "resize": (
            "aws redshift modify-cluster --cluster-identifier {resource_id} "
            "--node-type <new_type> --number-of-nodes <count> --region {region}"
        ),
        "reduce_nodes": (
            "aws redshift modify-cluster --cluster-identifier {resource_id} "
            "--number-of-nodes <count> --region {region}"
        ),
        "snapshot_delete": (
            "aws redshift delete-cluster-snapshot --snapshot-identifier <snapshot_id>"
        ),
    },
    "AWS::OpenSearchService::Domain": {
        "delete": (
            "aws opensearch delete-domain --domain-name {resource_id} --region {region}"
        ),
        "resize": (
            "aws opensearch update-domain-config --domain-name {resource_id} "
            "--cluster-config InstanceType=<new_type> --region {region}"
        ),
        "reduce_nodes": (
            "aws opensearch update-domain-config --domain-name {resource_id} "
            "--cluster-config InstanceCount=<count> --region {region}"
        ),
    },
    "AWS::ECS::Service": {
        "delete": (
            "aws ecs delete-service --cluster <cluster> --service {resource_id} "
            "--force --region {region}"
        ),
        "resize": (
            "aws ecs update-service --cluster <cluster> --service {resource_id} "
            "--task-definition <task:new_revision> --region {region}"
        ),
    },
    "AWS::EKS::Cluster": {
        "delete": "aws eks delete-cluster --name {resource_id} --region {region}",
        "reduce_nodes": (
            "aws eks update-nodegroup-config --cluster-name {resource_id} "
            "--nodegroup-name <group> --scaling-config desiredSize=0,minSize=0,maxSize=<n> "
            "--region {region}"
        ),
    },
    "AWS::S3::Bucket": {
        "archive": (
            "aws s3api put-bucket-lifecycle-configuration --bucket {resource_id} "
            "--lifecycle-configuration file://transition-to-glacier.json"
        ),
        "delete": (
            "# 1. Empty the bucket first\n"
            "aws s3 rm s3://{resource_id} --recursive\n"
            "# 2. Delete the bucket\n"
            "aws s3api delete-bucket --bucket {resource_id} --region {region}"
        ),
    },
    "AWS::DynamoDB::Table": {
        "delete": (
            "aws dynamodb delete-table --table-name {resource_id} --region {region}"
        ),
        "archive": (
            "aws dynamodb update-table --table-name {resource_id} "
            "--billing-mode PAY_PER_REQUEST --region {region}"
        ),
    },
    "AWS::SNS::Topic": {
        "delete": "aws sns delete-topic --topic-arn {resource_id} --region {region}",
    },
    "AWS::SQS::Queue": {
        "delete": (
            "aws sqs delete-queue --queue-url https://sqs.{region}.amazonaws.com/{account_id}/{resource_id} "
            "--region {region}"
        ),
    },
    "AWS::DMS::ReplicationInstance": {
        "delete": (
            "aws dms delete-replication-instance "
            "--replication-instance-arn {resource_id} --region {region}"
        ),
        "resize": (
            "aws dms modify-replication-instance "
            "--replication-instance-arn {resource_id} "
            "--replication-instance-class <new_class> --region {region}"
        ),
    },
    # ------------------------------------------------------------------ GCP
    "compute.googleapis.com/Instance": {
        "stop": "gcloud compute instances stop {resource_id} --zone {region}",
        "delete": "gcloud compute instances delete {resource_id} --zone {region} --quiet",
        "resize": (
            "gcloud compute instances set-machine-type {resource_id} "
            "--machine-type <new_type> --zone {region}"
        ),
        "convert_spot": (
            "# Spot VMs cannot be set on existing instances — recreate:\n"
            "gcloud compute instances create {resource_id}-spot "
            "--machine-type <type> --provisioning-model=SPOT --zone {region}"
        ),
    },
    "sqladmin.googleapis.com/Instance": {
        "stop": "gcloud sql instances patch {resource_id} --activation-policy NEVER",
        "delete": "gcloud sql instances delete {resource_id} --quiet",
        "resize": ("gcloud sql instances patch {resource_id} --tier <new_tier>"),
    },
    "container.googleapis.com/Cluster": {
        "delete": "gcloud container clusters delete {resource_id} --zone {region} --quiet",
        "resize": (
            "gcloud container clusters resize {resource_id} "
            "--node-pool <pool> --num-nodes <count> --zone {region}"
        ),
        "reduce_nodes": (
            "gcloud container clusters resize {resource_id} "
            "--node-pool <pool> --num-nodes 0 --zone {region}"
        ),
    },
    "redis.googleapis.com/Instance": {
        "delete": "gcloud redis instances delete {resource_id} --region {region} --quiet",
        "resize": (
            "gcloud redis instances update {resource_id} --size <gb> --region {region}"
        ),
    },
    "bigquery.googleapis.com/Dataset": {
        "delete": "bq rm -r -f {resource_id}",
        "archive": (
            "# Set partition expiration to reduce storage costs\n"
            "bq update --time_partitioning_expiration <seconds> {resource_id}.<table>"
        ),
    },
    "run.googleapis.com/Service": {
        "delete": "gcloud run services delete {resource_id} --region {region} --quiet",
    },
    "cloudfunctions.googleapis.com/Function": {
        "delete": "gcloud functions delete {resource_id} --region {region} --quiet",
    },
    "storage.googleapis.com/Bucket": {
        "delete": "gsutil rm -r gs://{resource_id}",
        "archive": (
            "gsutil lifecycle set lifecycle.json gs://{resource_id}\n"
            "# lifecycle.json: transition objects older than <days> to Coldline/Archive"
        ),
    },
    "spanner.googleapis.com/Instance": {
        "delete": "gcloud spanner instances delete {resource_id} --quiet",
        "reduce_nodes": (
            "gcloud spanner instances update {resource_id} --nodes <count>"
        ),
        "resize": (
            "gcloud spanner instances update {resource_id} --processing-units <count>"
        ),
    },
    # --------------------------------------------------------------- Azure
    "microsoft.compute/virtualmachines": {
        "stop": (
            "az vm deallocate --name {resource_id} --resource-group <rg> --no-wait"
        ),
        "delete": (
            "az vm delete --name {resource_id} --resource-group <rg> --yes --no-wait"
        ),
        "resize": (
            "az vm resize --name {resource_id} --resource-group <rg> --size <new_size>"
        ),
        "convert_spot": (
            "# Azure Spot VMs must be created from scratch:\n"
            "az vm create --name {resource_id}-spot --resource-group <rg> "
            "--image <image> --priority Spot --eviction-policy Deallocate --size <size>"
        ),
    },
    "microsoft.sql/servers/databases": {
        "delete": (
            "az sql db delete --name {resource_id} --server <server> --resource-group <rg> --yes"
        ),
        "resize": (
            "az sql db update --name {resource_id} --server <server> "
            "--resource-group <rg> --service-objective <tier>"
        ),
    },
    "microsoft.dbforpostgresql/flexibleservers": {
        "stop": (
            "az postgres flexible-server stop --name {resource_id} --resource-group <rg>"
        ),
        "delete": (
            "az postgres flexible-server delete --name {resource_id} --resource-group <rg> --yes"
        ),
        "resize": (
            "az postgres flexible-server update --name {resource_id} "
            "--resource-group <rg> --sku-name <new_sku>"
        ),
    },
    "microsoft.containerservice/managedclusters": {
        "delete": "az aks delete --name {resource_id} --resource-group <rg> --yes --no-wait",
        "resize": (
            "az aks nodepool scale --cluster-name {resource_id} "
            "--name <pool> --node-count <count> --resource-group <rg>"
        ),
        "reduce_nodes": (
            "az aks nodepool scale --cluster-name {resource_id} "
            "--name <pool> --node-count 0 --resource-group <rg>"
        ),
    },
    "microsoft.cache/redis": {
        "delete": ("az redis delete --name {resource_id} --resource-group <rg> --yes"),
        "resize": (
            "az redis update --name {resource_id} --resource-group <rg> --sku <tier> --vm-size <size>"
        ),
    },
    "microsoft.web/sites": {
        "stop": "az webapp stop --name {resource_id} --resource-group <rg>",
        "delete": "az webapp delete --name {resource_id} --resource-group <rg>",
    },
    "microsoft.storage/storageaccounts": {
        "delete": (
            "az storage account delete --name {resource_id} --resource-group <rg> --yes"
        ),
        "archive": (
            "az storage account management-policy create --account-name {resource_id} "
            "--resource-group <rg> --policy @lifecycle-policy.json"
        ),
    },
    "microsoft.servicebus/namespaces": {
        "delete": (
            "az servicebus namespace delete --name {resource_id} --resource-group <rg>"
        ),
        "resize": (
            "az servicebus namespace update --name {resource_id} "
            "--resource-group <rg> --sku <tier>"
        ),
    },
}


def get_command(
    type_id: str,
    action: str,
    resource_id: str = "{resource_id}",
    region: str = "{region}",
    account_id: str = "{account_id}",
) -> str | None:
    """Return the CLI command string for the given resource type and action.

    Placeholders ``{resource_id}``, ``{region}``, ``{account_id}`` are filled
    from the corresponding kwargs.  Returns ``None`` if no template is registered
    for this (type_id, action) pair.
    """
    template = _COMMANDS.get(type_id, {}).get(action)
    if template is None:
        return None
    return template.format(
        resource_id=resource_id,
        region=region,
        account_id=account_id,
    )


def runbook(
    type_id: str,
    resource_id: str = "{resource_id}",
    region: str = "{region}",
    account_id: str = "{account_id}",
) -> list[tuple[str, str]]:
    """Return all known (action, command) pairs for a resource type.

    Useful for generating full runbook entries.  Returns an empty list if
    no commands are registered for this type.
    """
    entries = _COMMANDS.get(type_id, {})
    return [
        (
            action,
            template.format(
                resource_id=resource_id,
                region=region,
                account_id=account_id,
            ),
        )
        for action, template in entries.items()
    ]


def supported_types() -> list[str]:
    """Return all type_ids that have at least one registered command."""
    return sorted(_COMMANDS.keys())
