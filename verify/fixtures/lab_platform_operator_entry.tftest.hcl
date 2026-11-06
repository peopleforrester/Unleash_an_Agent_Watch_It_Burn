# ABOUTME: `terraform test` cases for the cluster root's lab-platform-operator access entry (#873), planned against a
# ABOUTME: mocked aws provider. verify/test_lab_platform_operator_entry.py copies this next to a clean copy of the root.

# The mocks answer only what the root and its registry modules need to plan: ARNs and policy JSON the provider
# validates. Account 111122223333 is a placeholder.
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "111122223333", arn = "arn:aws:iam::111122223333:user/nwuser" }
  }
  mock_data "aws_iam_session_context" {
    defaults = { issuer_arn = "arn:aws:iam::111122223333:user/nwuser" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com", id = "aws" }
  }
  mock_data "aws_region" {
    defaults = { region = "us-west-2", name = "us-west-2", id = "us-west-2" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::111122223333:policy/watch-it-burn-boundary" }
  }
  # The lab VPC the root reads for the cluster API's 443 rule (#906); the rule needs a valid CIDR to plan.
  mock_data "aws_vpc" {
    defaults = { cidr_block = "10.0.0.0/16" }
  }
  # An account with no role of that name, as the harvest's base account is.
  mock_data "aws_iam_roles" {
    defaults = { names = [], arns = [] }
  }
}

variables {
  name               = "watch-it-burn-attendee-007"
  event              = "test"
  profile            = "test"
  region             = "us-west-2"
  hostname           = "soot-sabrina.agenticburn.com"
  vpc_id             = "vpc-0123456789abcdef0"
  private_subnet_ids = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
}

run "seat_in_an_account_with_the_role" {
  command = plan
  variables {
    role = "attendee"
  }
  override_data {
    target = data.aws_iam_roles.lab_platform_operator
    values = {
      names = ["lab-platform-operator"]
      arns  = ["arn:aws:iam::111122223333:role/lab-platform-operator"]
    }
  }
  override_data {
    target = data.aws_iam_role.lab_platform_operator
    values = { unique_id = "AROAEXAMPLEOPERATOR1" }
  }
  # The student's user ARN is known only after apply; given here so the comparison below can be made at plan.
  override_resource {
    target          = aws_iam_user.attendee
    values          = { arn = "arn:aws:iam::111122223333:user/wib-attendee-007" }
    override_during = plan
  }
  assert {
    condition     = length(aws_eks_access_entry.lab_platform_operator) == 1
    error_message = "a seat in an account that holds lab-platform-operator gets one access entry for it"
  }
  assert {
    condition     = aws_eks_access_entry.lab_platform_operator[0].principal_arn == "arn:aws:iam::111122223333:role/lab-platform-operator"
    error_message = "the entry names lab-platform-operator in the seat's own account"
  }
  assert {
    condition     = aws_eks_access_entry.lab_platform_operator[0].kubernetes_groups == toset(["lab-platform:learner-apps"])
    error_message = "the entry's only Kubernetes group is lab-platform:learner-apps"
  }
  assert {
    condition     = aws_eks_access_entry.lab_platform_operator[0].type == "STANDARD"
    error_message = "the entry is a STANDARD entry"
  }
  assert {
    condition     = aws_eks_access_policy_association.attendee_admin.principal_arn != aws_eks_access_entry.lab_platform_operator[0].principal_arn
    error_message = "the root's one access policy association is the student's, never the operator role's"
  }
  assert {
    condition     = terraform_data.lab_platform_operator_id[0].input == "AROAEXAMPLEOPERATOR1"
    error_message = "the entry follows the role's unique id, so a role made again replaces it"
  }
  assert {
    condition     = output.lab_platform_operator_entry == "arn:aws:iam::111122223333:role/lab-platform-operator"
    error_message = "the output names the admitted role"
  }
}

run "seat_in_the_base_account" {
  command = plan
  variables {
    role = "attendee"
  }
  assert {
    condition     = length(aws_eks_access_entry.lab_platform_operator) == 0 && length(data.aws_iam_role.lab_platform_operator) == 0
    error_message = "an account without the role gets no entry, which EKS would refuse for a missing principal"
  }
  assert {
    condition     = output.lab_platform_operator_entry == ""
    error_message = "the output is empty where nothing was admitted"
  }
}

run "community_cluster_with_the_role" {
  command = plan
  variables {
    role     = "community"
    name     = "watch-it-burn-community"
    hostname = "attackme.agenticburn.com"
  }
  override_data {
    target = data.aws_iam_roles.lab_platform_operator
    values = {
      names = ["lab-platform-operator"]
      arns  = ["arn:aws:iam::111122223333:role/lab-platform-operator"]
    }
  }
  assert {
    condition     = length(aws_eks_access_entry.lab_platform_operator) == 0
    error_message = "the community cluster is no seat and admits no harvest probe"
  }
}

run "admin_cluster_with_the_role" {
  command = plan
  variables {
    role     = "admin"
    name     = "watch-it-burn-private"
    hostname = "burritobot-private.agenticburn.com"
  }
  override_data {
    target = data.aws_iam_roles.lab_platform_operator
    values = {
      names = ["lab-platform-operator"]
      arns  = ["arn:aws:iam::111122223333:role/lab-platform-operator"]
    }
  }
  assert {
    condition     = length(aws_eks_access_entry.lab_platform_operator) == 0
    error_message = "the admin cluster is no seat and admits no harvest probe"
  }
}
