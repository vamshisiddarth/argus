# Supported Resource Types

This page lists every type in the resource registry (`core/registry/`) as of v0.6.0. The registry is
the single source of truth for what Argus knows about each type. Run `argus policies docs <TYPE>` for the full metric list and
valid remediation actions of any type.

Resources whose type isn't listed here still appear in scans: the adapter falls back to dynamic
metric discovery via `ListMetrics` (AWS) / `list_metric_descriptors` (GCP) / `list_metric_definitions` (Azure).

## AWS (43 types)

| Resource type | Name | Metrics | Remediation actions |
|---|---|---|---|
| `AWS::EC2::Instance` | EC2 Instance | CPUUtilization, NetworkOut, NetworkIn | delete, resize, stop, snapshot_delete, convert_spot |
| `AWS::RDS::DBInstance` | RDS Instance | CPUUtilization, DatabaseConnections, NetworkReceiveThroughput | delete, resize, stop, snapshot_delete |
| `AWS::RDS::DBCluster` | Aurora DB Cluster | CPUUtilization, DatabaseConnections, AuroraReplicaLag | delete, resize, stop, snapshot_delete, reduce_replicas |
| `AWS::EC2::NatGateway` | NAT Gateway | BytesOutToDestination, BytesInFromDestination, PacketsOutToDestination | delete |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` | Application/Network Load Balancer | RequestCount, ActiveConnectionCount, TargetResponseTime | delete |
| `AWS::ElasticLoadBalancing::LoadBalancer` | Classic Load Balancer | RequestCount, HealthyHostCount, UnHealthyHostCount | delete |
| `AWS::Lambda::Function` | Lambda Function | Invocations, Duration, Errors | delete, resize |
| `AWS::EC2::Volume` | EBS Volume | VolumeReadOps, VolumeWriteOps, VolumeReadBytes | delete, snapshot_delete, archive |
| `AWS::DynamoDB::Table` | DynamoDB Table | ConsumedReadCapacityUnits, ConsumedWriteCapacityUnits, SuccessfulRequestLatency | delete, archive |
| `AWS::SQS::Queue` | SQS Queue | NumberOfMessagesSent, NumberOfMessagesReceived, ApproximateNumberOfMessagesVisible | delete |
| `AWS::ElastiCache::CacheCluster` | ElastiCache Cluster | CPUUtilization, CurrConnections, CacheHits | delete, resize, stop |
| `AWS::ElastiCache::ReplicationGroup` | ElastiCache Replication Group | CurrConnections, CacheHitRate, ReplicationLag | delete, resize, reduce_replicas |
| `AWS::Redshift::Cluster` | Redshift Cluster | CPUUtilization, DatabaseConnections, ReadIOPS | delete, resize, reduce_nodes, snapshot_delete |
| `AWS::OpenSearchService::Domain` | OpenSearch Domain | CPUUtilization, SearchableDocuments, IndexingRate | delete, resize, reduce_nodes |
| `AWS::ECS::Service` | ECS Service | CPUUtilization, MemoryUtilization | delete, resize |
| `AWS::EKS::Cluster` | EKS Cluster | cluster_node_count, node_cpu_utilization, node_memory_utilization | delete, reduce_nodes |
| `AWS::Kinesis::Stream` | Kinesis Data Stream | GetRecords.Records, IncomingRecords, PutRecord.Success | delete |
| `AWS::SNS::Topic` | SNS Topic | NumberOfNotificationsDelivered, NumberOfMessagesPublished, NumberOfNotificationsFailed | delete |
| `AWS::ApiGateway::RestApi` | API Gateway REST API | Count, 4XXError, 5XXError | delete |
| `AWS::ApiGateway::Stage` | API Gateway Stage | Count, 4XXError, Latency | delete |
| `AWS::CloudFront::Distribution` | CloudFront Distribution | Requests, BytesDownloaded, 4xxErrorRate | delete |
| `AWS::StepFunctions::StateMachine` | Step Functions State Machine | ExecutionsStarted, ExecutionsSucceeded, ExecutionsFailed | delete |
| `AWS::Glue::Job` | Glue Job | glue.driver.aggregate.bytesRead, glue.driver.aggregate.elapsedTime | delete |
| `AWS::MSK::Cluster` | MSK Kafka Cluster | BytesInPerSec, BytesOutPerSec, KafkaDataLogsDiskUsed | delete, reduce_nodes |
| `AWS::SageMaker::Endpoint` | SageMaker Endpoint | Invocations, ModelLatency, CPUUtilization | delete, resize, stop |
| `AWS::EMR::Cluster` | EMR Cluster | YARNMemoryAvailablePercentage, ContainerPendingRatio, AppsRunning | delete, reduce_nodes |
| `AWS::DMS::ReplicationInstance` | DMS Replication Instance | CPUUtilization, FreeableMemory, CDCLatencySource | delete, resize |
| `AWS::Neptune::DBCluster` | Neptune DB Cluster | CPUUtilization, DatabaseConnections, BufferCacheHitRatio | delete, resize, reduce_nodes, snapshot_delete |
| `AWS::DocDB::DBCluster` | DocumentDB Cluster | CPUUtilization, DatabaseConnections, BufferCacheHitRatio | delete, resize, reduce_nodes, snapshot_delete |
| `AWS::WorkSpaces::Workspace` | WorkSpaces Workspace | Available, InSessionLatency, SessionLaunchTime | delete, stop |
| `AWS::KinesisFirehose::DeliveryStream` | Kinesis Firehose Delivery Stream | IncomingBytes, IncomingRecords, DeliveryToS3.Success | delete |
| `AWS::AppSync::GraphQLApi` | AppSync GraphQL API | 4XXError, 5XXError, Latency | delete |
| `AWS::Events::Rule` | EventBridge Rule | TriggeredRules, Invocations, FailedInvocations | delete |
| `AWS::ElasticBeanstalk::Environment` | Elastic Beanstalk Environment | EnvironmentHealth, ApplicationRequestsTotal, CPUUtilization | delete, resize |
| `AWS::CodeBuild::Project` | CodeBuild Project | Builds, SucceededBuilds, Duration | delete |
| `AWS::Transfer::Server` | Transfer Family Server | FilesIn, FilesOut, BytesIn | delete, stop |
| `AWS::WAFv2::WebACL` | WAFv2 Web ACL | AllowedRequests, BlockedRequests, CountedRequests | delete |
| `AWS::S3::Bucket` | S3 Bucket | NumberOfObjects, BucketSizeBytes, AllRequests | delete, archive |
| `AWS::Cognito::UserPool` | Cognito User Pool | SignInSuccesses, TokenRefreshSuccesses, SignUpSuccesses | delete |
| `AWS::IoT::Thing` | IoT Core Thing | PublishIn.Success, PublishOut.Success, Connect.Success | delete |
| `AWS::MediaLive::Channel` | MediaLive Channel | ActiveOutputs, DroppedFrames, NetworkIn | delete, stop |
| `AWS::Batch::JobQueue` | Batch Job Queue | PendingJobCount, RunnableJobCount, RunningJobCount | delete |
| `AWS::Route53::HostedZone` | Route 53 Hosted Zone | DNSQueries | delete |

## GCP (31 types)

| Resource type | Name | Metrics | Remediation actions |
|---|---|---|---|
| `compute.googleapis.com/Instance` | GCE Instance | instance/cpu/utilization, instance/network/sent_bytes_count, instance/network/received_bytes_count | delete, resize, stop, snapshot_delete, convert_spot |
| `compute.googleapis.com/Disk` | Persistent Disk | instance/disk/read_ops_count, instance/disk/write_ops_count | delete, snapshot_delete, archive |
| `sqladmin.googleapis.com/Instance` | Cloud SQL Instance | database/cpu/utilization, database/network/connections, database/network/received_bytes_count | delete, resize, stop, snapshot_delete |
| `container.googleapis.com/Cluster` | GKE Cluster | kubernetes.io/container/cpu/request_utilization, kubernetes.io/container/memory/request_utilization, kubernetes.io/node/cpu/allocatable_utilization | delete, resize, reduce_nodes |
| `run.googleapis.com/Service` | Cloud Run Service | request_count, request_latencies, container/cpu/utilizations | delete, resize |
| `cloudfunctions.googleapis.com/Function` | Cloud Function | function/execution_count, function/execution_times | delete |
| `storage.googleapis.com/Bucket` | Cloud Storage Bucket | api/request_count, network/sent_bytes_count | delete, archive |
| `bigquery.googleapis.com/Dataset` | BigQuery Dataset | storage/table_count, storage/stored_bytes | delete, archive |
| `bigquery.googleapis.com/Table` | BigQuery Table | storage/stored_bytes, storage/row_count | delete, archive |
| `redis.googleapis.com/Instance` | Cloud Memorystore (Redis) | clients/connected, stats/cache_hit_ratio, stats/memory/usage_ratio | delete, resize |
| `spanner.googleapis.com/Instance` | Cloud Spanner Instance | instance/cpu/utilization, instance/session_count | delete, resize, reduce_nodes |
| `pubsub.googleapis.com/Topic` | Pub/Sub Topic | topic/send_message_operation_count, topic/byte_cost | delete |
| `pubsub.googleapis.com/Subscription` | Pub/Sub Subscription | subscription/pull_message_operation_count, subscription/num_undelivered_messages | delete |
| `dataflow.googleapis.com/Job` | Dataflow Job | job/data_watermark_age, job/elapsed_time, job/element_count | delete, stop |
| `dataproc.googleapis.com/Cluster` | Dataproc Cluster | cluster/yarn/allocated_memory_percentage, cluster/hdfs/storage_utilization | delete, stop, reduce_nodes |
| `aiplatform.googleapis.com/Endpoint` | Vertex AI Endpoint | prediction/online/request_count, prediction/online/latencies | delete, resize |
| `compute.googleapis.com/Router` | Cloud Router | nat/sent_bytes_count, nat/received_bytes_count, nat/port_usage | delete |
| `compute.googleapis.com/ForwardingRule` | Cloud Load Balancer (Forwarding Rule) | https/request_count, https/total_latencies | delete |
| `compute.googleapis.com/BackendService` | Cloud Load Balancer Backend Service | https/request_count, https/backend_request_bytes_count | delete |
| `compute.googleapis.com/VpnTunnel` | Cloud VPN Tunnel | vpn/sent_bytes_count, vpn/received_bytes_count | delete |
| `compute.googleapis.com/Address` | Static IP Address | instance/network/sent_bytes_count | delete |
| `vpcaccess.googleapis.com/Connector` | VPC Access Connector | connector/sent_bytes_count, connector/received_bytes_count | delete |
| `bigtable.googleapis.com/Instance` | Cloud Bigtable Instance | server/request_count, cluster/cpu_load, cluster/storage_utilization | delete, resize, reduce_nodes |
| `alloydb.googleapis.com/Cluster` | AlloyDB Cluster | database/cpu/utilization, database/postgresql/num_backends | delete, resize, snapshot_delete |
| `file.googleapis.com/Instance` | Filestore Instance | nfs/server/used_bytes_percent, nfs/server/read_ops_count, nfs/server/write_ops_count | delete, snapshot_delete |
| `memcache.googleapis.com/Instance` | Cloud Memorystore (Memcached) | node/curr_connections, node/cmd_get_count, node/cmd_set_count | delete, resize |
| `firestore.googleapis.com/Database` | Firestore Database | document/read_count, document/write_count | delete, archive |
| `composer.googleapis.com/Environment` | Cloud Composer Environment | environment/dagbag_size, environment/num_celery_workers, environment/worker/pod_eviction_count | delete, resize, reduce_nodes |
| `notebooks.googleapis.com/Instance` | Vertex AI Workbench (Notebook) | instance/cpu/utilization, instance/network/sent_bytes_count | delete, stop |
| `appengine.googleapis.com/Application` | App Engine Application | http/server/response_count, system/cpu/usage | delete, stop |
| `cloudtasks.googleapis.com/Queue` | Cloud Tasks Queue | queue/depth, api/request_count | delete |

## Azure (40 types)

| Resource type | Name | Metrics | Remediation actions |
|---|---|---|---|
| `microsoft.compute/virtualmachines` | Virtual Machine | Percentage CPU, Network In Total, Network Out Total | delete, resize, stop, snapshot_delete, convert_spot |
| `microsoft.compute/virtualmachinescalesets` | VM Scale Set | Percentage CPU, Network In Total, Network Out Total | delete, resize, reduce_nodes |
| `microsoft.compute/disks` | Managed Disk | Composite Disk Read Operations/sec, Composite Disk Write Operations/sec | delete, snapshot_delete, archive |
| `microsoft.sql/servers/databases` | Azure SQL Database | cpu_percent, connection_successful, storage_percent | delete, resize, snapshot_delete |
| `microsoft.sql/managedinstances` | SQL Managed Instance | avg_cpu_percent, storage_space_used_mb | delete, resize, snapshot_delete |
| `microsoft.web/serverfarms` | App Service Plan | CpuPercentage, MemoryPercentage, HttpQueueLength | delete, resize |
| `microsoft.web/sites` | App Service / Function App | CpuTime, Requests, BytesReceived | delete, stop |
| `microsoft.containerservice/managedclusters` | AKS Cluster | node_cpu_usage_percentage, node_memory_rss_percentage, kube_node_status_allocatable_cpu_cores | delete, resize, reduce_nodes |
| `microsoft.containerinstance/containergroups` | Container Instance | CpuUsage, MemoryUsage, NetworkBytesReceivedPerSecond | delete, stop |
| `microsoft.cache/redis` | Azure Cache for Redis | connectedclients, cachehits, cachemisses | delete, resize |
| `microsoft.documentdb/databaseaccounts` | Cosmos DB Account | TotalRequests, NormalizedRUConsumption, ServerSideLatency | delete, resize, reduce_replicas |
| `microsoft.storage/storageaccounts` | Storage Account | Transactions, Ingress, Egress | delete, archive |
| `microsoft.containerservice/managedclusters/agentpools` | AKS Node Pool | node_cpu_usage_percentage, node_memory_rss_percentage | delete, resize, reduce_nodes |
| `microsoft.eventhub/namespaces` | Event Hubs Namespace | IncomingMessages, OutgoingMessages, ActiveConnections | delete, resize |
| `microsoft.servicebus/namespaces` | Service Bus Namespace | IncomingMessages, OutgoingMessages, ActiveConnections | delete, resize |
| `microsoft.web/sites/functions` | Azure Functions | FunctionExecutionCount, FunctionExecutionUnits | delete, stop |
| `microsoft.apimanagement/service` | API Management Service | TotalRequests, SuccessfulRequests, Capacity | delete, resize |
| `microsoft.network/applicationgateways` | Application Gateway | TotalRequests, CurrentConnections, Throughput | delete, resize |
| `microsoft.network/loadbalancers` | Load Balancer | PacketCount, ByteCount, AllocatedSnatPorts | delete |
| `microsoft.databricks/workspaces` | Azure Databricks Workspace | autoOptimizeClusterUtilization, numActiveClusters | delete, resize |
| `microsoft.hdinsight/clusters` | HDInsight Cluster | GatewayRequests, CategorizedGatewayRequests | delete, resize, reduce_nodes |
| `microsoft.logic/workflows` | Logic App Workflow | RunsStarted, RunsCompleted, RunsFailed | delete, stop |
| `microsoft.cognitiveservices/accounts` | Cognitive Services / Azure OpenAI | TotalCalls, TotalErrors, Latency | delete, resize |
| `microsoft.search/searchservices` | Azure AI Search | SearchQueriesPerSecond, ThrottledSearchQueriesPercentage | delete, resize |
| `microsoft.streamanalytics/streamingjobs` | Stream Analytics Job | InputEvents, OutputEvents, ResourceUtilization | delete, stop |
| `microsoft.datafactory/factories` | Azure Data Factory | PipelineRunsStarted, ActivityRunsStarted, TriggerRunsStarted | delete |
| `microsoft.network/natgateways` | NAT Gateway | ByteCount, PacketCount, SNATConnectionCount | delete |
| `microsoft.network/virtualnetworkgateways` | VPN Gateway | TunnelIngressBytes, TunnelEgressBytes, P2SConnectionCount | delete, resize |
| `microsoft.network/azurefirewalls` | Azure Firewall | DataProcessed, FirewallHealth, Throughput | delete, stop |
| `microsoft.network/frontdoors` | Azure Front Door | RequestCount, TotalLatency, RequestSize | delete |
| `microsoft.network/expressroutecircuits` | ExpressRoute Circuit | BitsInPerSecond, BitsOutPerSecond | delete |
| `microsoft.network/publicipaddresses` | Public IP Address | ByteCount, PacketCount | delete |
| `microsoft.dbformysql/flexibleservers` | Azure Database for MySQL | cpu_percent, active_connections, storage_percent | delete, resize, stop, snapshot_delete |
| `microsoft.dbforpostgresql/flexibleservers` | Azure Database for PostgreSQL | cpu_percent, active_connections, storage_percent | delete, resize, stop, snapshot_delete |
| `microsoft.dbformariadb/servers` | Azure Database for MariaDB | cpu_percent, active_connections, storage_percent | delete, resize, stop, snapshot_delete |
| `microsoft.synapse/workspaces/sqlpools` | Synapse SQL Pool | DWUUsedPercent, ActiveQueries, ConnectionsBlockedByFirewall | delete, resize, snapshot_delete |
| `microsoft.machinelearningservices/workspaces/onlineendpoints` | Azure ML Online Endpoint | RequestsPerMinute, RequestLatency | delete, resize |
| `microsoft.batch/batchaccounts` | Batch Account | TaskStartEvent, CoreCount, IdleNodeCount | delete, reduce_nodes |
| `microsoft.devices/iothubs` | IoT Hub | d2c.telemetry.ingress.allProtocol, connectedDeviceCount, totalDeviceCount | delete, resize |
| `microsoft.signalrservice/signalr` | Azure SignalR Service | ConnectionCount, MessageCount, InboundTraffic | delete, resize |

GCP metric names are shown without their `<service>.googleapis.com/` prefix.
