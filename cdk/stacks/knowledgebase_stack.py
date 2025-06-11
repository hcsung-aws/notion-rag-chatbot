from aws_cdk import (
    Stack,
    Duration,
    aws_iam as iam,
    CfnOutput,
    CfnResource
)
from constructs import Construct
import json

class KnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, data_bucket, opensearch_collection, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Bedrock KnowledgeBase 서비스 역할
        self.kb_service_role = iam.Role(
            self, "KnowledgeBaseServiceRole",
            role_name="AmazonBedrockExecutionRoleForKnowledgeBase_NotionChatbot",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
            ]
        )

        # S3 데이터 소스 접근 권한
        data_bucket.grant_read(self.kb_service_role)

        # OpenSearch Serverless 접근 권한
        self.kb_service_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll"
                ],
                resources=[opensearch_collection.attr_arn]
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
        self.knowledge_base = CfnResource(
            self, "NotionKnowledgeBase",
            type="AWS::Bedrock::KnowledgeBase",
            properties={
                "Name": "notion-opensearch-kb",
                "Description": "Notion RAG Chatbot Knowledge Base with OpenSearch Serverless Vector Store",
                "RoleArn": self.kb_service_role.role_arn,
                "KnowledgeBaseConfiguration": {
                    "Type": "VECTOR",
                    "VectorKnowledgeBaseConfiguration": {
                        "EmbeddingModelArn": f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                    }
                },
                "StorageConfiguration": {
                    "Type": "OPENSEARCH_SERVERLESS",
                    "OpensearchServerlessConfiguration": {
                        "CollectionArn": opensearch_collection.attr_arn,
                        "VectorIndexName": "notion-kb-index",
                        "FieldMapping": {
                            "VectorField": "embedding",
                            "TextField": "content",
                            "MetadataField": "metadata"
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
            self, "KnowledgeBaseServiceRoleArn",
            value=self.kb_service_role.role_arn,
            description="Knowledge Base Service Role ARN"
        )
