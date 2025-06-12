from aws_cdk import (
    Stack,
    Duration,
    aws_iam as iam,
    aws_opensearchserverless as opensearchserverless,
    CfnOutput,
    CfnResource
)
from constructs import Construct
import json

class CompleteKnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, data_bucket, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. Bedrock KnowledgeBase 서비스 역할
        self.kb_service_role = iam.Role(
            self, "KnowledgeBaseServiceRole",
            role_name="AmazonBedrockExecutionRoleForKnowledgeBase_Complete",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonBedrockFullAccess")
            ]
        )

        # S3 데이터 소스 접근 권한
        data_bucket.grant_read(self.kb_service_role)

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

        # 2. OpenSearch Serverless 네트워크 정책
        network_policy = opensearchserverless.CfnSecurityPolicy(
            self, "NetworkPolicy",
            name="notion-kb-network-policy",
            type="network",
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "Resource": ["collection/notion-kb-collection"],
                            "ResourceType": "collection"
                        },
                        {
                            "Resource": ["collection/notion-kb-collection"],
                            "ResourceType": "dashboard"
                        }
                    ],
                    "AllowFromPublic": True
                }
            ])
        )

        # 3. OpenSearch Serverless 암호화 정책
        encryption_policy = opensearchserverless.CfnSecurityPolicy(
            self, "EncryptionPolicy",
            name="notion-kb-encryption-policy",
            type="encryption",
            policy=json.dumps({
                "Rules": [
                    {
                        "Resource": ["collection/notion-kb-collection"],
                        "ResourceType": "collection"
                    }
                ],
                "AWSOwnedKey": True
            })
        )

        # 4. OpenSearch Serverless 컬렉션
        self.vector_collection = opensearchserverless.CfnCollection(
            self, "VectorCollection",
            name="notion-kb-collection",
            type="VECTORSEARCH",
            description="Vector collection for Notion RAG Chatbot Knowledge Base"
        )

        # 의존성 설정
        self.vector_collection.add_dependency(network_policy)
        self.vector_collection.add_dependency(encryption_policy)

        # 5. 데이터 접근 정책
        data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, "DataAccessPolicy",
            name="notion-kb-data-access-policy",
            type="data",
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": ["collection/notion-kb-collection"],
                            "Permission": [
                                "aoss:CreateCollectionItems",
                                "aoss:DeleteCollectionItems",
                                "aoss:UpdateCollectionItems",
                                "aoss:DescribeCollectionItems"
                            ]
                        },
                        {
                            "ResourceType": "index",
                            "Resource": ["index/notion-kb-collection/*"],
                            "Permission": [
                                "aoss:CreateIndex",
                                "aoss:DeleteIndex",
                                "aoss:UpdateIndex",
                                "aoss:DescribeIndex",
                                "aoss:ReadDocument",
                                "aoss:WriteDocument"
                            ]
                        }
                    ],
                    "Principal": [
                        self.kb_service_role.role_arn,
                        f"arn:aws:iam::{self.account}:root"
                    ]
                }
            ])
        )

        # OpenSearch Serverless 접근 권한
        self.kb_service_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll"
                ],
                resources=[self.vector_collection.attr_arn]
            )
        )

        # 6. Bedrock KnowledgeBase 생성
        self.knowledge_base = CfnResource(
            self, "NotionKnowledgeBase",
            type="AWS::Bedrock::KnowledgeBase",
            properties={
                "Name": "knowledge-base-notion-chatbot",
                "Description": "Notion RAG Chatbot Knowledge Base with OpenSearch Serverless",
                "RoleArn": self.kb_service_role.role_arn,
                "KnowledgeBaseConfiguration": {
                    "Type": "VECTOR",
                    "VectorKnowledgeBaseConfiguration": {
                        "EmbeddingModelArn": f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                        "EmbeddingModelConfiguration": {
                            "BedrockEmbeddingModelConfiguration": {
                                "Dimensions": 1024
                            }
                        }
                    }
                },
                "StorageConfiguration": {
                    "Type": "OPENSEARCH_SERVERLESS",
                    "OpensearchServerlessConfiguration": {
                        "CollectionArn": self.vector_collection.attr_arn,
                        "VectorIndexName": "bedrock-knowledge-base-default-index",
                        "FieldMapping": {
                            "VectorField": "bedrock-knowledge-base-default-vector",
                            "TextField": "AMAZON_BEDROCK_TEXT",
                            "MetadataField": "AMAZON_BEDROCK_METADATA"
                        }
                    }
                }
            }
        )

        # 의존성 설정
        self.knowledge_base.node.add_dependency(self.vector_collection)
        self.knowledge_base.node.add_dependency(data_access_policy)

        # 7. S3 데이터 소스 생성
        self.data_source = CfnResource(
            self, "NotionDataSource",
            type="AWS::Bedrock::DataSource",
            properties={
                "Name": "knowledge-base-notion-chatbot-data-source",
                "Description": "Notion data from S3 bucket",
                "KnowledgeBaseId": self.knowledge_base.ref,
                "DataSourceConfiguration": {
                    "Type": "S3",
                    "S3Configuration": {
                        "BucketArn": data_bucket.bucket_arn,
                        "InclusionPrefixes": ["notion-data/"]
                    }
                },
                "DataDeletionPolicy": "DELETE",
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
            self, "VectorCollectionArn",
            value=self.vector_collection.attr_arn,
            description="OpenSearch Serverless Collection ARN"
        )

        CfnOutput(
            self, "VectorCollectionEndpoint",
            value=self.vector_collection.attr_collection_endpoint,
            description="OpenSearch Serverless Collection Endpoint"
        )

        CfnOutput(
            self, "KnowledgeBaseServiceRoleArn",
            value=self.kb_service_role.role_arn,
            description="Knowledge Base Service Role ARN"
        )
