from aws_cdk import (
    Stack,
    Duration,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
    CfnResource,
    RemovalPolicy
)
from constructs import Construct
import json

class AuroraKnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc, data_bucket, **kwargs) -> None:
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

        # Aurora PostgreSQL 마스터 사용자 시크릿
        self.aurora_secret = secretsmanager.Secret(
            self, "AuroraSecret",
            description="Aurora PostgreSQL master user credentials",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"username": "postgres"}),
                generate_string_key="password",
                exclude_characters=" %+~`#$&*()|[]{}:;<>?!'/\"\\@",
                password_length=16
            )
        )

        # Aurora PostgreSQL Serverless v2 클러스터
        self.aurora_cluster = rds.DatabaseCluster(
            self, "AuroraCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_3
            ),
            credentials=rds.Credentials.from_secret(self.aurora_secret),
            default_database_name="notionkb",
            vpc=vpc,
            subnet_group=subnet_group,
            security_groups=[self.aurora_security_group],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=2,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[
                rds.ClusterInstance.serverless_v2("reader", scale_with_writer=True)
            ],
            backup=rds.BackupProps(
                retention=Duration.days(7)
            ),
            deletion_protection=False,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Data API 활성화 (CloudFormation 속성 직접 설정)
        cfn_cluster = self.aurora_cluster.node.default_child
        cfn_cluster.add_property_override("EnableHttpEndpoint", True)

        # Bedrock KnowledgeBase 서비스 역할
        self.kb_service_role = iam.Role(
            self, "KnowledgeBaseServiceRole",
            role_name="AmazonBedrockExecutionRoleForKnowledgeBase_Aurora",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
            ]
        )

        # S3 데이터 소스 접근 권한
        data_bucket.grant_read(self.kb_service_role)

        # Aurora 접근 권한
        self.aurora_secret.grant_read(self.kb_service_role)
        
        # RDS 접근 권한
        cluster_arn = f"arn:aws:rds:{self.region}:{self.account}:cluster:{self.aurora_cluster.cluster_identifier}"
        self.kb_service_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "rds:DescribeDBClusters",
                    "rds:DescribeDBInstances"
                ],
                resources=[cluster_arn]
            )
        )

        # Bedrock 모델 접근 권한 (임베딩용)
        self.kb_service_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel"
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                ]
            )
        )

        # Bedrock KnowledgeBase 생성
        cluster_arn = f"arn:aws:rds:{self.region}:{self.account}:cluster:{self.aurora_cluster.cluster_identifier}"
        self.knowledge_base = CfnResource(
            self, "NotionKnowledgeBase",
            type="AWS::Bedrock::KnowledgeBase",
            properties={
                "Name": "notion-aurora-kb",
                "Description": "Notion RAG Chatbot Knowledge Base with Aurora PostgreSQL",
                "RoleArn": self.kb_service_role.role_arn,
                "KnowledgeBaseConfiguration": {
                    "Type": "VECTOR",
                    "VectorKnowledgeBaseConfiguration": {
                        "EmbeddingModelArn": f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                    }
                },
                "StorageConfiguration": {
                    "Type": "RDS",
                    "RdsConfiguration": {
                        "ResourceArn": cluster_arn,
                        "CredentialsSecretArn": self.aurora_secret.secret_arn,
                        "DatabaseName": "notionkb",
                        "TableName": "bedrock_integration.bedrock_kb",
                        "FieldMapping": {
                            "VectorField": "embedding",
                            "TextField": "chunks",
                            "MetadataField": "metadata",
                            "PrimaryKeyField": "id"
                        }
                    }
                }
            }
        )

        # S3 데이터 소스 생성
        self.data_source = CfnResource(
            self, "NotionDataSource",
            type="AWS::Bedrock::DataSource",
            properties={
                "Name": "notion-s3-data-source",
                "Description": "Notion data from S3 bucket",
                "KnowledgeBaseId": self.knowledge_base.ref,
                "DataSourceConfiguration": {
                    "Type": "S3",
                    "S3Configuration": {
                        "BucketArn": data_bucket.bucket_arn,
                        "InclusionPrefixes": ["notion-data/"]
                    }
                },
                "VectorIngestionConfiguration": {
                    "ChunkingConfiguration": {
                        "ChunkingStrategy": "FIXED_SIZE",
                        "FixedSizeChunkingConfiguration": {
                            "MaxTokens": 512,
                            "OverlapPercentage": 20
                        }
                    }
                }
            }
        )

        # 의존성 설정
        self.data_source.node.add_dependency(self.knowledge_base)

        # Outputs
        CfnOutput(
            self, "KnowledgeBaseId",
            value=self.knowledge_base.ref,
            description="Bedrock Knowledge Base ID"
        )

        CfnOutput(
            self, "DataSourceId", 
            value=self.data_source.ref,
            description="Bedrock Data Source ID"
        )

        CfnOutput(
            self, "KnowledgeBaseArn",
            value=self.knowledge_base.get_att("KnowledgeBaseArn").to_string(),
            description="Bedrock Knowledge Base ARN"
        )

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
