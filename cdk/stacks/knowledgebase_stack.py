from aws_cdk import (
    Stack,
    Duration,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_opensearchserverless as opensearchserverless,
    CfnOutput
)
from constructs import Construct
import json

class KnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, data_bucket, opensearch_collection, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Bedrock KnowledgeBase 서비스 역할
        self.kb_service_role = iam.Role(
            self, "KnowledgeBaseServiceRole",
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

        # OpenSearch 데이터 접근 정책 업데이트 (KnowledgeBase 역할 추가)
        kb_data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, "KnowledgeBaseDataAccessPolicy",
            name="kb-data-access-policy",
            type="data",
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": ["collection/notion-chatbot-vectors"],
                            "Permission": [
                                "aoss:CreateCollectionItems",
                                "aoss:DeleteCollectionItems",
                                "aoss:UpdateCollectionItems",
                                "aoss:DescribeCollectionItems"
                            ]
                        },
                        {
                            "ResourceType": "index",
                            "Resource": ["index/notion-chatbot-vectors/*"],
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

        # Bedrock KnowledgeBase 생성
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self, "NotionKnowledgeBase",
            name="notion-chatbot-kb",
            description="Notion RAG Chatbot Knowledge Base with OpenSearch Serverless",
            role_arn=self.kb_service_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                )
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=opensearch_collection.attr_arn,
                    vector_index_name="notion-kb-index",
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field="embedding",
                        text_field="content",
                        metadata_field="metadata"
                    )
                )
            )
        )

        # 의존성 설정
        self.knowledge_base.add_dependency(kb_data_access_policy)

        # S3 데이터 소스 생성
        self.data_source = bedrock.CfnDataSource(
            self, "NotionDataSource",
            name="notion-s3-data-source",
            description="Notion data from S3 bucket",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=data_bucket.bucket_arn,
                    inclusion_prefixes=["notion-data/"]
                )
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512,
                        overlap_percentage=20
                    )
                )
            )
        )

        # Outputs
        CfnOutput(
            self, "KnowledgeBaseId",
            value=self.knowledge_base.attr_knowledge_base_id,
            description="Bedrock Knowledge Base ID"
        )

        CfnOutput(
            self, "DataSourceId", 
            value=self.data_source.attr_data_source_id,
            description="Bedrock Data Source ID"
        )

        CfnOutput(
            self, "KnowledgeBaseArn",
            value=self.knowledge_base.attr_knowledge_base_arn,
            description="Bedrock Knowledge Base ARN"
        )
