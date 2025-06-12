from aws_cdk import (
    Stack,
    Duration,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
    RemovalPolicy
)
from constructs import Construct
import json

class AuroraSimpleStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Aurora PostgreSQL용 보안 그룹
        self.aurora_security_group = ec2.SecurityGroup(
            self, "AuroraSecurityGroup",
            vpc=vpc,
            description="Security group for Aurora PostgreSQL Serverless",
            allow_all_outbound=True
        )

        # VPC 내부에서의 PostgreSQL 접근 허용
        self.aurora_security_group.add_ingress_rule(
            peer=ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(5432),
            description="Allow PostgreSQL access from VPC"
        )

        # Aurora PostgreSQL 클러스터용 서브넷 그룹
        subnet_group = rds.SubnetGroup(
            self, "AuroraSubnetGroup",
            description="Subnet group for Aurora PostgreSQL",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            )
        )

        # Aurora PostgreSQL 마스터 사용자 시크릿 (간단한 비밀번호)
        self.aurora_secret = secretsmanager.Secret(
            self, "AuroraSecret",
            description="Aurora PostgreSQL master user credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"username": "postgres"}),
                generate_string_key="password",
                exclude_characters=" \"@/\\",
                password_length=12,
                include_space=False
            )
        )

        # Aurora PostgreSQL Serverless v2 클러스터
        self.aurora_cluster = rds.DatabaseCluster(
            self, "AuroraCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_3
            ),
            credentials=rds.Credentials.from_secret(self.aurora_secret),
            default_database_name="vectordb",
            vpc=vpc,
            subnet_group=subnet_group,
            security_groups=[self.aurora_security_group],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            backup=rds.BackupProps(
                retention=Duration.days(7)
            ),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Data API 활성화 (Bedrock KnowledgeBase 필수)
        cfn_cluster = self.aurora_cluster.node.default_child
        cfn_cluster.add_property_override("EnableHttpEndpoint", True)

        # Outputs
        CfnOutput(
            self, "AuroraClusterEndpoint",
            value=self.aurora_cluster.cluster_endpoint.hostname,
            description="Aurora PostgreSQL Cluster Endpoint"
        )

        CfnOutput(
            self, "AuroraSecretArn",
            value=self.aurora_secret.secret_arn,
            description="Aurora PostgreSQL Secret ARN"
        )

        CfnOutput(
            self, "AuroraClusterArn",
            value=f"arn:aws:rds:{self.region}:{self.account}:cluster:{self.aurora_cluster.cluster_identifier}",
            description="Aurora PostgreSQL Cluster ARN"
        )
