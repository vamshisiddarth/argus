# Deployment

Argus runs on a weekly schedule on your cloud infrastructure.
Choose the platform that matches your cloud:

| Cloud | Platform | Template |
|-------|----------|----------|
| AWS | Lambda + EventBridge | CloudFormation |
| GCP | Cloud Run Job + Cloud Scheduler | `deploy.sh` |
| Azure | Azure Function + Timer trigger | Bicep |

All deployments use the **same agent code** — only the entrypoint and runtime differ.

- [AWS Lambda](aws.md)
- [GCP Cloud Run](gcp.md)
- [Azure Function](azure.md)
- [Multi-Account (AWS)](multi-account.md)
