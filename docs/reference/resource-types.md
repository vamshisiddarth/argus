# Supported Resource Types

Argus collects metrics for the following resource types. Resources not in these lists
still appear in scans — the adapter falls back to dynamic metric discovery via
`ListMetrics` / `list_metric_descriptors` / `list_metric_definitions`.

## AWS (43 types with explicit metrics)

| Resource Type | Key Metrics |
|--------------|-------------|
| `AWS::EC2::Instance` | CPUUtilization, NetworkIn, NetworkOut |
| `AWS::EC2::Volume` | VolumeReadOps, VolumeWriteOps, VolumeReadBytes |
| `AWS::EC2::NatGateway` | BytesInFromDestination, BytesOutToDestination, ActiveConnectionCount |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` (ALB) | RequestCount, ActiveConnectionCount |
| `AWS::ElasticLoadBalancingV2::LoadBalancer` (NLB) | ActiveFlowCount, ProcessedBytes |
| `AWS::ElasticLoadBalancing::LoadBalancer` (Classic) | RequestCount, HealthyHostCount |
| `AWS::Lambda::Function` | Invocations, Duration, Errors |
| `AWS::RDS::DBInstance` | CPUUtilization, DatabaseConnections, ReadIOPS, WriteIOPS |
| `AWS::RDS::DBCluster` | CPUUtilization, DatabaseConnections, ServerlessDatabaseCapacity |
| `AWS::ElastiCache::CacheCluster` | CPUUtilization, CurrConnections, NetworkBytesIn |
| `AWS::ElastiCache::ReplicationGroup` | CPUUtilization, CurrConnections, ReplicationLag |
| `AWS::ECS::Service` | CPUUtilization, MemoryUtilization |
| `AWS::EKS::Cluster` | cluster_node_count, cluster_failed_node_count |
| `AWS::OpenSearchService::Domain` | CPUUtilization, SearchableDocuments, IndexingRate |
| `AWS::Kinesis::Stream` | GetRecords.Bytes, PutRecord.Bytes, IncomingRecords |
| `AWS::SQS::Queue` | NumberOfMessagesSent, ApproximateNumberOfMessagesVisible |
| `AWS::SNS::Topic` | NumberOfMessagesPublished, NumberOfNotificationsDelivered |
| `AWS::DynamoDB::Table` | ConsumedReadCapacityUnits, ConsumedWriteCapacityUnits |
| `AWS::CloudFront::Distribution` | Requests, BytesDownloaded, ErrorRate |
| `AWS::ApiGateway::RestApi` | Count, Latency, 4XXError |
| `AWS::ApiGateway::Stage` | Count, Latency |
| `AWS::StepFunctions::StateMachine` | ExecutionsStarted, ExecutionsFailed |
| `AWS::Glue::Job` | glue.driver.aggregate.numCompletedTasks, glue.ALL.jvm.heap.usage |
| `AWS::MSK::Cluster` | KafkaDataLogsDiskUsed, GlobalTopicCount |
| `AWS::SageMaker::Endpoint` | Invocations, CPUUtilization |
| `AWS::EMR::Cluster` | CoreNodesRunning, HDFSUtilization |
| `AWS::DMS::ReplicationInstance` | CPUUtilization, FreeStorageSpace |
| `AWS::Neptune::DBCluster` | CPUUtilization, DatabaseConnections |
| `AWS::DocDB::DBCluster` | CPUUtilization, DatabaseConnections |
| `AWS::WorkSpaces::Workspace` | UserConnected, Unhealthy |
| `AWS::KinesisFirehose::DeliveryStream` | IncomingBytes, DeliveryToS3.Bytes |
| `AWS::AppSync::GraphQLApi` | 4XXError, 5XXError, Latency |
| `AWS::Events::Rule` | Invocations, FailedInvocations |
| `AWS::ElasticBeanstalk::Application` | EnvironmentHealth |
| `AWS::CodeBuild::Project` | Builds, SucceededBuilds, FailedBuilds |
| `AWS::Transfer::Server` | FilesIn, FilesOut |
| `AWS::WAFv2::WebACL` | AllowedRequests, BlockedRequests |
| `AWS::S3::Bucket` | NumberOfObjects, BucketSizeBytes |
| `AWS::Cognito::UserPool` | SignUpSuccesses, SignInSuccesses |
| `AWS::IoT::TopicRule` | TopicMatch, ParseError |
| `AWS::MediaLive::Channel` | ActiveAlerts, DroppedFrames |
| `AWS::Batch::JobQueue` | PendingJobCount, RunnableJobCount |
| `AWS::Route53::HealthCheck` | HealthCheckPercentageHealthy |

## GCP (15 types with explicit metrics)

| Asset Type | Key Metrics |
|-----------|-------------|
| `compute.googleapis.com/Instance` | cpuutilization, received_bytes_count |
| `container.googleapis.com/Cluster` | cpu/request_utilization |
| `cloudsql.googleapis.com/Instance` | database/cpu/utilization, database/network/connections |
| `run.googleapis.com/Service` | request_count, container/cpu/utilizations |
| `appengine.googleapis.com/Application` | http/server/request_count |
| `pubsub.googleapis.com/Topic` | topic/send_message_operation_count |
| `bigquery.googleapis.com/Dataset` | storage/table_count |
| `storage.googleapis.com/Bucket` | storage/object_count |
| `spanner.googleapis.com/Instance` | instance/cpu/utilization |
| `redis.googleapis.com/Instance` | stats/memory/usage_ratio, stats/connected_clients |
| `bigtable.googleapis.com/Instance` | server/request_count |
| `dataproc.googleapis.com/Cluster` | cluster/nodes/count |
| `composer.googleapis.com/Environment` | environment/healthy, environment/dag_processing/total_parse_time |
| `artifactregistry.googleapis.com/Repository` | api/request_count |
| `dns.googleapis.com/ManagedZone` | query_counts |

## Azure (25 types with explicit metrics)

| Resource Type | Key Metrics |
|--------------|-------------|
| `microsoft.compute/virtualmachines` | Percentage CPU, Network In, Network Out |
| `microsoft.compute/virtualmachinescalesets` | Percentage CPU |
| `microsoft.compute/disks` | Composite Disk Read Bytes/sec, Composite Disk Write Bytes/sec |
| `microsoft.sql/servers/databases` | cpu_percent, connection_successful |
| `microsoft.sql/managedinstances` | avg_cpu_percent |
| `microsoft.web/serverfarms` | CpuPercentage, MemoryPercentage |
| `microsoft.web/sites` | CpuTime, Requests |
| `microsoft.containerservice/managedclusters` | node_cpu_usage_percentage |
| `microsoft.containerinstance/containergroups` | CpuUsage, MemoryUsage |
| `microsoft.cache/redis` | percentProcessorTime, connectedclients |
| `microsoft.documentdb/databaseaccounts` | TotalRequests, NormalizedRUConsumption |
| `microsoft.storage/storageaccounts` | UsedCapacity, Transactions |
| `microsoft.eventhub/namespaces` | IncomingMessages, OutgoingMessages |
| `microsoft.servicebus/namespaces` | IncomingMessages, OutgoingMessages |
| `microsoft.apimanagement/service` | TotalRequests, Capacity |
| `microsoft.network/applicationgateways` | TotalRequests, FailedRequests |
| `microsoft.network/loadbalancers` | SYNCount, PacketCount |
| `microsoft.databricks/workspaces` | num_running_clusters |
| `microsoft.hdinsight/clusters` | NumActiveWorkers |
| `microsoft.logic/workflows` | RunsStarted, RunsSucceeded |
| `microsoft.cognitiveservices/accounts` | TotalCalls, SuccessfulCalls |
| `microsoft.search/searchservices` | SearchQueriesPerSecond, ThrottledSearchQueriesPercentage |
| `microsoft.streamanalytics/streamingjobs` | ResourceUtilization, InputEvents |
| `microsoft.datafactory/factories` | PipelineSucceededRuns, PipelineFailedRuns |
| `microsoft.keyvault/vaults` | ServiceApiHit, ServiceApiLatency |
