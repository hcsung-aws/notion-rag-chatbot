from aws_cdk import (
    Stack,
    Duration,
    aws_opensearchserverless as opensearchserverless,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    CfnOutput
)
from constructs import Construct
import json

class OpenSearchStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, secrets, data_bucket, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # OpenSearch Serverless 보안 정책들
        
        # 1. 암호화 정책
        encryption_policy = opensearchserverless.CfnSecurityPolicy(
            self, "NotionChatbotEncryptionPolicy",
            name="notion-encrypt-policy",
            type="encryption",
            policy=json.dumps({
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": ["collection/notion-chatbot-vectors"]
                    }
                ],
                "AWSOwnedKey": True
            })
        )

        # 2. 네트워크 정책
        network_policy = opensearchserverless.CfnSecurityPolicy(
            self, "NotionChatbotNetworkPolicy",
            name="notion-network-policy",
            type="network",
            policy=json.dumps([
                {
                    "Rules": [
                        {
                            "ResourceType": "collection",
                            "Resource": ["collection/notion-chatbot-vectors"]
                        },
                        {
                            "ResourceType": "dashboard",
                            "Resource": ["collection/notion-chatbot-vectors"]
                        }
                    ],
                    "AllowFromPublic": True
                }
            ])
        )

        # 3. OpenSearch Serverless 컬렉션
        self.vector_collection = opensearchserverless.CfnCollection(
            self, "NotionVectorCollection",
            name="notion-chatbot-vectors",
            type="VECTORSEARCH",
            description="Vector collection for Notion chatbot semantic search"
        )

        # 의존성 설정
        self.vector_collection.add_dependency(encryption_policy)
        self.vector_collection.add_dependency(network_policy)

        # 4. OpenSearch 서비스 역할
        self.opensearch_service_role = iam.Role(
            self, "OpenSearchServiceRole",
            assumed_by=iam.ServicePrincipal("opensearch.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonOpenSearchServiceFullAccess")
            ]
        )

        # 6. 벡터 임베딩 및 인덱싱을 위한 Lambda 함수 역할
        self.vector_lambda_role = iam.Role(
            self, "VectorLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # S3 접근 권한
        data_bucket.grant_read(self.vector_lambda_role)

        # Bedrock 접근 권한 (임베딩 모델용)
        self.vector_lambda_role.add_to_policy(
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

        # OpenSearch Serverless 접근 권한
        self.vector_lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll"
                ],
                resources=[self.vector_collection.attr_arn]
            )
        )

        # Secrets Manager 접근 권한
        for secret in secrets.values():
            secret.grant_read(self.vector_lambda_role)

        # 5. 데이터 접근 정책 (KnowledgeBase 서비스 포함)
        data_access_policy = opensearchserverless.CfnAccessPolicy(
            self, "NotionChatbotDataAccessPolicy",
            name="notion-data-access-policy",
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
                        self.opensearch_service_role.role_arn,
                        self.vector_lambda_role.role_arn,
                        f"arn:aws:iam::{self.account}:root",
                        "arn:aws:iam::*:role/service-role/AmazonBedrockExecutionRoleForKnowledgeBase*"
                    ]
                }
            ])
        )

        data_access_policy.add_dependency(self.vector_collection)

        # 7. 벡터 임베딩 Lambda 함수
        self.vector_lambda = lambda_.Function(
            self, "VectorEmbeddingFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            role=self.vector_lambda_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            environment={
                "OPENSEARCH_ENDPOINT": self.vector_collection.attr_collection_endpoint,
                "BUCKET_NAME": data_bucket.bucket_name,
                "COLLECTION_NAME": "notion-chatbot-vectors",
                "INDEX_NAME": "notion-index"
            },
            code=lambda_.Code.from_inline("""
import json
import boto3
import urllib3
import os
import time
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import urlparse

def handler(event, context):
    print("Starting vector embedding process...")
    
    # AWS 클라이언트 초기화
    s3 = boto3.client('s3')
    bedrock = boto3.client('bedrock-runtime')
    session = boto3.Session()
    credentials = session.get_credentials()
    
    try:
        # S3에서 Notion 데이터 가져오기
        bucket_name = os.environ['BUCKET_NAME']
        
        response = s3.list_objects_v2(
            Bucket=bucket_name,
            Prefix='notion-data/'
        )
        
        if 'Contents' not in response:
            return {'statusCode': 200, 'body': 'No documents found'}
        
        documents = []
        for obj in response['Contents']:
            if obj['Key'].endswith('.json'):
                doc_response = s3.get_object(Bucket=bucket_name, Key=obj['Key'])
                doc_content = json.loads(doc_response['Body'].read())
                documents.append(doc_content)
        
        print(f"Processing {len(documents)} documents")
        
        # OpenSearch 엔드포인트 설정
        opensearch_endpoint = os.environ['OPENSEARCH_ENDPOINT']
        index_name = os.environ['INDEX_NAME']
        region = os.environ.get('AWS_REGION', 'ap-northeast-2')
        
        # 인덱스 생성 (존재하지 않는 경우)
        create_index_if_not_exists(opensearch_endpoint, index_name, credentials, region)
        
        # 각 문서에 대해 임베딩 생성 및 인덱싱
        indexed_count = 0
        for doc in documents:
            try:
                # 문서 텍스트 준비
                text_content = f"{doc.get('title', '')} {doc.get('content', '')}"
                
                # Bedrock으로 임베딩 생성
                embedding = generate_embedding(bedrock, text_content)
                
                if embedding:
                    # OpenSearch에 문서 인덱싱
                    doc_with_embedding = {
                        'id': doc.get('id'),
                        'title': doc.get('title'),
                        'content': doc.get('content'),
                        'url': doc.get('url'),
                        'embedding': embedding,
                        'metadata': doc.get('metadata', {})
                    }
                    
                    if index_document(opensearch_endpoint, index_name, doc['id'], doc_with_embedding, credentials, region):
                        indexed_count += 1
                        
            except Exception as e:
                print(f"Error processing document {doc.get('id', 'unknown')}: {str(e)}")
                continue
            
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Successfully processed {len(documents)} documents',
                'indexed_count': indexed_count
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def generate_embedding(bedrock_client, text):
    '''Bedrock Titan Embedding으로 벡터 생성'''
    try:
        response = bedrock_client.invoke_model(
            modelId='amazon.titan-embed-text-v2:0',
            body=json.dumps({
                'inputText': text[:8000]  # Titan 모델 제한
            })
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['embedding']
        
    except Exception as e:
        print(f"Embedding generation error: {str(e)}")
        return []

def sign_request(method, url, body, credentials, region):
    '''AWS SigV4로 요청 서명'''
    parsed_url = urlparse(url)
    request = AWSRequest(method=method, url=url, data=body, headers={'Content-Type': 'application/json'})
    SigV4Auth(credentials, 'aoss', region).add_auth(request)
    return request

def create_index_if_not_exists(endpoint, index_name, credentials, region):
    '''OpenSearch 인덱스 생성'''
    try:
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "url": {"type": "keyword"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 1024,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib"
                        }
                    },
                    "metadata": {"type": "object"}
                }
            }
        }
        
        url = f"{endpoint}/{index_name}"
        body = json.dumps(index_body)
        signed_request = sign_request('PUT', url, body, credentials, region)
        
        http = urllib3.PoolManager()
        response = http.urlopen(
            signed_request.method,
            signed_request.url,
            body=signed_request.body,
            headers=dict(signed_request.headers)
        )
        
        if response.status in [200, 400]:  # 400은 이미 존재하는 경우
            print(f"Index {index_name} ready")
        else:
            print(f"Index creation failed: {response.data.decode()}")
            
    except Exception as e:
        print(f"Index creation error: {str(e)}")

def index_document(endpoint, index_name, doc_id, document, credentials, region):
    '''OpenSearch에 문서 인덱싱'''
    try:
        url = f"{endpoint}/{index_name}/_doc/{doc_id}"
        body = json.dumps(document)
        signed_request = sign_request('PUT', url, body, credentials, region)
        
        http = urllib3.PoolManager()
        response = http.urlopen(
            signed_request.method,
            signed_request.url,
            body=signed_request.body,
            headers=dict(signed_request.headers)
        )
        
        if response.status in [200, 201]:
            print(f"Document {doc_id} indexed successfully")
            return True
        else:
            print(f"Document indexing failed: {response.data.decode()}")
            return False
            
    except Exception as e:
        print(f"Document indexing error: {str(e)}")
        return False
""")
        )

        # CloudWatch 로그 그룹
        vector_log_group = logs.LogGroup(
            self, "VectorEmbeddingLogGroup",
            log_group_name=f"/aws/lambda/{self.vector_lambda.function_name}",
            retention=logs.RetentionDays.ONE_WEEK
        )

        # Outputs
        CfnOutput(
            self, "OpenSearchCollectionEndpoint",
            value=self.vector_collection.attr_collection_endpoint,
            description="OpenSearch Serverless Collection Endpoint"
        )

        CfnOutput(
            self, "OpenSearchCollectionArn",
            value=self.vector_collection.attr_arn,
            description="OpenSearch Serverless Collection ARN"
        )

        CfnOutput(
            self, "VectorLambdaArn",
            value=self.vector_lambda.function_arn,
            description="Vector Embedding Lambda Function ARN"
        )
