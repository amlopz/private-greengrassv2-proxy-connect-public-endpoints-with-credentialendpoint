#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import aws_cdk as cdk
from aws_cdk import Aspects
import os
from cdk_nag import AwsSolutionsChecks
from cdk_nag import NagSuppressions

from greengrass_private_network.greengrass_private_network_stack import (
    GreengrassPrivateNetworkStack,
)


# Cannot look up VPC endpoint availability zones if account/region are not specified

app = cdk.App()
stack = GreengrassPrivateNetworkStack(
    app,
    "greengrass-private-network",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEPLOY_ACCOUNT"),
        region=os.environ.get("CDK_DEPLOY_REGION"),
    ),
)
Aspects.of(app).add(AwsSolutionsChecks())
NagSuppressions.add_stack_suppressions(stack, suppressions=[
    {"id": "AwsSolutions-EC29", "reason": "ASG not enabled for greengrass or proxy example"},
    {"id": "AwsSolutions-S1", "reason": "Server access logs not required, not running as a web server"},
    {"id": "AwsSolutions-IAM4", "reason": "Managed policy for SSM, not valuable to hand build a policy"},
    {"id": "AwsSolutions-IAM5", "reason": "Wildcard for file names, we won't know the file names on the s3 bucket"},
    {"id": "CdkNagValidationFailure", "reason": "Hide any nag failures due to runtime exceptions"}
])

app.synth()
