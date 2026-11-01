variable "sandbox_account_id" {
  description = "12-digit id of the sandbox account. The provider refuses to run anywhere else."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.sandbox_account_id))
    error_message = "sandbox_account_id must be 12 digits."
  }
}

variable "region" {
  description = "Region for the testbed."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "argus-testbed"
}

variable "enable_costly_classes" {
  description = "Create the NAT gateway and the load balancer (about 49 USD per month while they exist)."
  type        = bool
  default     = false
}

variable "client_vpn_server_certificate_arn" {
  description = "ACM server certificate for the idle Client VPN endpoint. Empty skips that class."
  type        = string
  default     = ""
}

variable "client_vpn_root_certificate_arn" {
  description = "ACM client root certificate for mutual authentication. Required with the server certificate."
  type        = string
  default     = ""
}
