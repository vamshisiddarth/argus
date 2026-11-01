provider "aws" {
  region              = var.region
  allowed_account_ids = [var.sandbox_account_id]

  default_tags {
    tags = {
      Project   = "argus-testbed"
      ManagedBy = "terraform"
    }
  }
}

locals {
  costly      = var.enable_costly_classes
  client_vpn  = var.enable_costly_classes && var.client_vpn_server_certificate_arn != "" && var.client_vpn_root_certificate_arn != ""
  host_prefix = "${var.name_prefix}-host"
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Network: free resources that the paid classes need.

resource "aws_vpc" "testbed" {
  cidr_block           = "10.99.0.0/16"
  enable_dns_hostnames = true

  tags = { Name = var.name_prefix }
}

resource "aws_internet_gateway" "testbed" {
  vpc_id = aws_vpc.testbed.id

  tags = { Name = var.name_prefix }
}

resource "aws_subnet" "a" {
  vpc_id            = aws_vpc.testbed.id
  cidr_block        = "10.99.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = { Name = "${var.name_prefix}-a" }
}

resource "aws_subnet" "b" {
  vpc_id            = aws_vpc.testbed.id
  cidr_block        = "10.99.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = { Name = "${var.name_prefix}-b" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.testbed.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.testbed.id
  }

  tags = { Name = "${var.name_prefix}-public" }
}

resource "aws_route_table_association" "a" {
  subnet_id      = aws_subnet.a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "host" {
  name        = "${local.host_prefix}-sg"
  description = "No inbound, no outbound"
  vpc_id      = aws_vpc.testbed.id
}

# Host that carries the decoy volume, the decoy address and the over-provisioned volume.

resource "aws_instance" "host" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.a.id
  vpc_security_group_ids = [aws_security_group.host.id]

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = local.host_prefix }
}

# Waste: unattached volumes.

resource "aws_ebs_volume" "unattached_1" {
  availability_zone = aws_subnet.a.availability_zone
  size              = 20
  type              = "gp3"
  encrypted         = true

  tags = {
    Name             = "${var.name_prefix}-unattached-1"
    argus-testbed-id = "w-unattached-vol-1"
  }
}

resource "aws_ebs_volume" "unattached_2" {
  availability_zone = aws_subnet.a.availability_zone
  size              = 100
  type              = "gp3"
  encrypted         = true

  tags = {
    Name             = "${var.name_prefix}-unattached-2"
    argus-testbed-id = "w-unattached-vol-2"
  }
}

# Decoy: a volume that is attached.

resource "aws_ebs_volume" "attached" {
  availability_zone = aws_subnet.a.availability_zone
  size              = 20
  type              = "gp3"
  encrypted         = true

  tags = {
    Name             = "${var.name_prefix}-attached"
    argus-testbed-id = "d-attached-vol-1"
  }
}

resource "aws_volume_attachment" "attached" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.attached.id
  instance_id = aws_instance.host.id
}

# Waste: provisioned performance far above anything used.

resource "aws_ebs_volume" "overprovisioned" {
  availability_zone = aws_subnet.a.availability_zone
  size              = 100
  type              = "gp3"
  iops              = 6000
  throughput        = 250
  encrypted         = true

  tags = {
    Name             = "${var.name_prefix}-overprovisioned"
    argus-testbed-id = "w-overprov-iops-1"
  }
}

resource "aws_volume_attachment" "overprovisioned" {
  device_name = "/dev/sdg"
  volume_id   = aws_ebs_volume.overprovisioned.id
  instance_id = aws_instance.host.id
}

# Waste: a stopped instance whose disk still bills.

resource "aws_instance" "stopped" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = "t3.micro"
  subnet_id              = aws_subnet.a.id
  vpc_security_group_ids = [aws_security_group.host.id]

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    volume_size = 8
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name             = "${var.name_prefix}-stopped"
    argus-testbed-id = "w-stopped-instance-1"
  }
}

resource "aws_ec2_instance_state" "stopped" {
  instance_id = aws_instance.stopped.id
  state       = "stopped"
}

# Waste: addresses attached to nothing. Decoy: an address in use.

resource "aws_eip" "unassociated_1" {
  domain = "vpc"

  tags = {
    Name             = "${var.name_prefix}-unassociated-1"
    argus-testbed-id = "w-unassociated-eip-1"
  }
}

resource "aws_eip" "unassociated_2" {
  domain = "vpc"

  tags = {
    Name             = "${var.name_prefix}-unassociated-2"
    argus-testbed-id = "w-unassociated-eip-2"
  }
}

resource "aws_eip" "associated" {
  domain = "vpc"

  tags = {
    Name             = "${var.name_prefix}-associated"
    argus-testbed-id = "d-associated-eip-1"
  }

  depends_on = [aws_internet_gateway.testbed]
}

resource "aws_eip_association" "associated" {
  allocation_id = aws_eip.associated.id
  instance_id   = aws_instance.host.id
}

# Waste: a log group that keeps logs forever. Decoy: one with retention.

resource "aws_cloudwatch_log_group" "no_retention" {
  name = "/argus-testbed/no-retention"

  tags = {
    argus-testbed-id = "w-log-group-no-retention-1"
  }
}

resource "aws_cloudwatch_log_group" "with_retention" {
  name              = "/argus-testbed/with-retention"
  retention_in_days = 30

  tags = {
    argus-testbed-id = "d-log-group-retention-1"
  }
}

# Costly classes, off by default.

resource "aws_eip" "nat" {
  count  = local.costly ? 1 : 0
  domain = "vpc"

  tags = { Name = "${var.name_prefix}-nat" }
}

resource "aws_nat_gateway" "idle" {
  count         = local.costly ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.a.id

  tags = {
    Name             = "${var.name_prefix}-idle-nat"
    argus-testbed-id = "w-idle-nat-1"
  }

  depends_on = [aws_internet_gateway.testbed]
}

resource "aws_lb" "idle" {
  count                      = local.costly ? 1 : 0
  name                       = "${var.name_prefix}-idle"
  load_balancer_type         = "application"
  internal                   = true
  subnets                    = [aws_subnet.a.id, aws_subnet.b.id]
  drop_invalid_header_fields = true

  tags = {
    argus-testbed-id = "w-idle-lb-1"
  }
}

resource "aws_ec2_client_vpn_endpoint" "idle" {
  count                  = local.client_vpn ? 1 : 0
  description            = "${var.name_prefix} idle"
  server_certificate_arn = var.client_vpn_server_certificate_arn
  client_cidr_block      = "10.200.0.0/22"

  authentication_options {
    type                       = "certificate-authentication"
    root_certificate_chain_arn = var.client_vpn_root_certificate_arn
  }

  connection_log_options {
    enabled = false
  }

  tags = {
    argus-testbed-id = "w-idle-client-vpn-1"
  }
}

resource "aws_ec2_client_vpn_network_association" "idle" {
  count                  = local.client_vpn ? 1 : 0
  client_vpn_endpoint_id = aws_ec2_client_vpn_endpoint.idle[0].id
  subnet_id              = aws_subnet.a.id
}
