# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


from constructs import Construct
import boto3
import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    Stack,
    aws_route53 as route53,
    aws_route53_targets as targets,
    aws_iam as iam,
    aws_s3 as s3
)


class GreengrassPrivateNetworkStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        gg_vpc = ec2.Vpc(
            self,
            "GreengrassPrivateNetwork",
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PUBLIC,
                    name="Public",
                ),
                ec2.SubnetConfiguration(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    name="Private with NAT",
                ),
            ],
            max_azs=2,
        )

        gg_vpc.add_flow_log("GreengrassPrivateVpcFlowLog")

        ec2_role_for_gg = iam.Role(
            self, "GreengrassPrivateRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
        )

        ec2_role_for_gg.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        ec2_role_for_gg.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AWSGreengrassReadOnlyAccess"
            )
        )

        bucket = s3.Bucket(self, "greengrass-component-artifacts-{}",
                           bucket_name="greengrass-component-artifacts-{}".format(self.account),
                           enforce_ssl=True,
                           removal_policy=cdk.RemovalPolicy.DESTROY,
                           encryption=s3.BucketEncryption.S3_MANAGED
                           )

        bucket.add_to_resource_policy(iam.PolicyStatement(
            sid="GreengrassAccess",
            principals=[ec2_role_for_gg],
            effect=iam.Effect.ALLOW,
            actions=["s3:PutObject", "s3:Get*"],
            resources=[bucket.bucket_arn, bucket.arn_for_objects("*")]
        ))

        iam.Policy(
            self,
            "AllowsGreengrassToRequiredArtifacts",
            roles=[ec2_role_for_gg],
            policy_name="AllowsGreengrassToRequiredArtifacts",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "s3:GetObject",
                        "s3:ListObjects",
                        "s3:PutObject",
                        "s3:ListAllMyBuckets",
                        "s3:GetBucketLocation"
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[
                        bucket.bucket_arn,
                        bucket.arn_for_objects("*")
                    ],
                )
            ],
        )

        iam.Policy(
            self,
            "AllowsCreationOfComponentsAndDeployments",
            roles=[ec2_role_for_gg],
            policy_name="AllowsCreationOfComponentsAndDeployments",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "greengrass:DescribeComponent",
                        "greengrass:GetComponent",
                        "greengrass:GetComponentVersionArtifact",
                        "greengrass:GetCoreDevice",
                        "greengrass:CreateComponentVersion",
                        "greengrass:CreateDeployment",
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[
                        "*"
                    ],
                )
            ],
        )

        iam.Policy(
            self,
            "AllowGreengrassDeviceLogging",
            roles=[ec2_role_for_gg],
            policy_name="AllowGreengrassDeviceLogging",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                        "logs:DescribeLogStreams",
                    ],
                    effect=iam.Effect.ALLOW,
                    resources=[
                        "arn:aws:logs:{}:{}:/aws/greengrass/*".format(
                            Stack.of(self).region, Stack.of(self).account
                        )
                    ],
                )
            ],
        )

        # scoping for security groups, pulling the cidr range of vpc
        peer = ec2.Peer.ipv4(gg_vpc.vpc_cidr_block)

        endpoints_sg = ec2.SecurityGroup(
            self,
            "endpoints-security-group",
            vpc=gg_vpc,
            description="Securing the endpoints used to create private connection with Greengrass",
            allow_all_outbound=True,
        )

        cloudwatch_endpoints_sg = ec2.SecurityGroup(
            self,
            "cloudwatch-endpoints-security-group",
            vpc=gg_vpc,
            description="Securing the endpoints used to create private connection with Greengrass",
            allow_all_outbound=True,
        )

        proxy_sg = ec2.SecurityGroup(
            self,
            "proxy-security-group",
            vpc=gg_vpc,
            description="Securing the the tiny proxy",
            allow_all_outbound=True,
        )
        proxy_sg.add_ingress_rule(
            peer, ec2.Port.tcp(8888), "Allow incoming MQTT from other devices"
        )
        proxy_sg.add_ingress_rule(
            peer, ec2.Port.tcp(443), "Allow incoming traffic from VPC endpoints"
        )

        greengrass_sg = ec2.SecurityGroup(
            self,
            "greengrass-runtime-security-group",
            vpc=gg_vpc,
            description="Securing the Greengrass runtime",
            allow_all_outbound=True,
        )
        greengrass_sg.add_ingress_rule(
            endpoints_sg, ec2.Port.tcp(8883), "Allow incoming MQTT from other devices"
        )
        greengrass_sg.add_ingress_rule(
            endpoints_sg, ec2.Port.tcp(8443), "Allow incoming communication from IoT Core"
        )
        greengrass_sg.add_ingress_rule(
            proxy_sg, ec2.Port.tcp(8888), "Allow incoming communication from Proxy server"
        )
        greengrass_sg.add_ingress_rule(
            endpoints_sg, ec2.Port.tcp(443), "Allow traffic from endpoints"
        )

        amazon_linux = ec2.MachineImage.latest_amazon_linux2023(
            edition=ec2.AmazonLinuxEdition.STANDARD,
            cpu_type=ec2.AmazonLinuxCpuType.X86_64,
        )

        with open("./user_data/userdata.sh") as f:
            USER_DATA = f.read()

        self.greengrass_instance = ec2.Instance(
            self,
            "Greengrass Instance",
            vpc=gg_vpc,
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T2, ec2.InstanceSize.SMALL
            ),
            machine_image=amazon_linux,

            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            ),
            role=ec2_role_for_gg,
            security_group=greengrass_sg,
            user_data=ec2.UserData.custom(USER_DATA),
            detailed_monitoring=True,
            block_devices=[ec2.BlockDevice(device_name="/dev/xvda",
                                           volume=ec2.BlockDeviceVolume.ebs(volume_size=50,
                                                                            encrypted=True))]
        )

        ec2_role_for_proxy = iam.Role(
            self, "ProxyRole", assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
        )

        ec2_role_for_proxy.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonSSMManagedInstanceCore"
            )
        )

        ubuntu = ec2.GenericLinuxImage({
            "us-east-1": "ami-053b0d53c279acc90",
            "us-east-2": "ami-024e6efaf93d85776"
        })

        # change userdata
        with open("./user_data/userdata_proxy.sh") as f:

            USER_DATA_PROXY = f.read()
            # ToDo fix the  with actual endpoint value using replace
            iot_client = boto3.client("iot", Stack.of(self).region)
            credentials_endpoint = iot_client.describe_endpoint(endpointType="iot:CredentialProvider")
            credentials_endpoint_address = credentials_endpoint["endpointAddress"]
            subdomain = credentials_endpoint_address.split('.')[0]
            print("subdomain: " + subdomain)
            USER_DATA_PROXY.replace("{{replace_with_actual_value}}", subdomain)

        # change instance type from Burstable4, was originally for ARM
        self.proxy_instance = ec2.Instance(
            self,
            "TinyProxy Instance",
            vpc=gg_vpc,
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T2, ec2.InstanceSize.SMALL
            ),
            machine_image=ubuntu,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC,
            ),
            role=ec2_role_for_proxy,
            security_group=proxy_sg,
            user_data=ec2.UserData.custom(USER_DATA_PROXY),
            detailed_monitoring=True,
            block_devices=[ec2.BlockDevice(device_name="/dev/xvda",
                                           volume=ec2.BlockDeviceVolume.ebs(volume_size=50,
                                                                            encrypted=True))]
        )

        # endpoint services: https://docs.aws.amazon.com/vpc/latest/privatelink/integrated-services-vpce-list.html

        iot_core_endpoint = gg_vpc.add_interface_endpoint(
            "IotCoreEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("iot.data", port=443),
            private_dns_enabled=False,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(iot_core_endpoint).add("Name", "iot-endpoint")

        greengrass_endpoint = gg_vpc.add_interface_endpoint(
            "GreengrassEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("greengrass", port=443),
            private_dns_enabled=True,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(greengrass_endpoint).add("Name", "greengrass-endpoint")

        s3_endpoint = gg_vpc.add_interface_endpoint(
            "S3Endpoint",
            service=ec2.InterfaceVpcEndpointAwsService("s3", port=443),
            private_dns_enabled=False,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(s3_endpoint).add("Name", "s3-endpoint")

        logs_endpoint = gg_vpc.add_interface_endpoint(
            "LogsEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("logs", port=443),
            private_dns_enabled=True,
            security_groups=[cloudwatch_endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(logs_endpoint).add("Name", "logs-endpoint")

        ssm_endpoint = gg_vpc.add_interface_endpoint(
            "SsmEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("ssm", port=443),
            private_dns_enabled=True,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(ssm_endpoint).add("Name", "ssm-endpoint")

        ssm_messages_endpoint = gg_vpc.add_interface_endpoint(
            "SsmMessagesEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("ssmmessages", port=443),
            private_dns_enabled=True,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(ssm_messages_endpoint).add("Name", "ssm-messages-endpoint")

        ec2_messages_endpoint = gg_vpc.add_interface_endpoint(
            "Ec2MessagesEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService("ec2messages", port=443),
            private_dns_enabled=True,
            security_groups=[endpoints_sg],
            lookup_supported_azs=True,
        )
        cdk.Tags.of(ec2_messages_endpoint).add("Name", "ec2-messages-endpoint")

        s3_endpoint_uri = "s3.{}.amazonaws.com".format(Stack.of(self).region)

        s3_hosted_zone = route53.HostedZone(
            self,
            "S3HostedZone",
            zone_name=s3_endpoint_uri,
            vpcs=[gg_vpc],
        )

        route53.ARecord(
            self,
            "S3Record",
            zone=s3_hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.InterfaceVpcEndpointTarget(s3_endpoint)
            ),
            record_name=s3_endpoint_uri,
        )

        route53.ARecord(
            self,
            "WildcardS3Record",
            zone=s3_hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.InterfaceVpcEndpointTarget(s3_endpoint)
            ),
            record_name="*." + s3_endpoint_uri,
        )
        # added the Zone and A Record for the Data IoT endpoint
        dataIoT_endpoint_uri = "data.iot.{}.amazonaws.com".format(Stack.of(self).region)
        iotcore_hosted_zone = route53.HostedZone(
            self,
            "dataIoTHostedZone",
            zone_name=dataIoT_endpoint_uri,
            vpcs=[gg_vpc],
        )

        route53.ARecord(
            self,
            "DataIotCoreRecord",
            zone=iotcore_hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.InterfaceVpcEndpointTarget(iot_core_endpoint)
            ),
            record_name=dataIoT_endpoint_uri,
        )

        iot_client = boto3.client("iot", Stack.of(self).region)
        iot_endpoint = iot_client.describe_endpoint(endpointType="iot:Data-ATS")
        iot_endpoint_address = iot_endpoint["endpointAddress"]

        # IoT Core endpoint
        hosted_zone = route53.HostedZone(
            self,
            "IotCoreHostedZone",
            zone_name=iot_endpoint_address,
            vpcs=[gg_vpc],
        )

        route53.ARecord(
            self,
            "IotCoreRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.InterfaceVpcEndpointTarget(iot_core_endpoint)
            ),
            record_name=iot_endpoint_address,
        )

        # Greengrass-ats Hosted Zone
        hosted_zone = route53.HostedZone(
            self,
            "GreengrassATSHostedZone",
            zone_name="greengrass-ats.iot.{}.amazonaws.com".format(
                Stack.of(self).region,
                vpcs=[gg_vpc],
            )
        )

        route53.ARecord(
            self,
            "GreengrassRecord",
            zone=hosted_zone,
            target=route53.RecordTarget.from_alias(
                targets.InterfaceVpcEndpointTarget(iot_core_endpoint)
            ),
            record_name="greengrass-ats.iot.{}.amazonaws.com".format(
                Stack.of(self).region
            ),
        )

        endpoints_sg.add_ingress_rule(
            greengrass_sg, ec2.Port.tcp(8883), "Greengrass secure MQTT to IoT core"
        )

        endpoints_sg.add_ingress_rule(
            greengrass_sg, ec2.Port.tcp(8443), "Secure MQTT to iot core endpoint"
        )
        endpoints_sg.add_ingress_rule(greengrass_sg, ec2.Port.tcp(443), "HTTPS to S3")

        cloudwatch_endpoints_sg.add_ingress_rule(
            peer, ec2.Port.tcp(443), "logging from Greengrass"
        )

        cdk.CfnOutput(
            self, "Greengrass Ec2 Instance:", value=self.greengrass_instance.instance_id
        )

        cdk.CfnOutput(self, "Greengrass Vpc CIDR Block:", value=gg_vpc.vpc_cidr_block)
