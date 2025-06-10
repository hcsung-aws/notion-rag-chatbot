from aws_cdk import (
    Stack,
    Duration,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_logs as logs,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct

class EcsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc, secrets, knowledge_base_id, data_bucket, opensearch_endpoint, vector_lambda_arn, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ECS Cluster
        cluster = ecs.Cluster(
            self, "NotionChatbotCluster",
            vpc=vpc,
            cluster_name="notion-chatbot-cluster",
            enable_fargate_capacity_providers=True
        )

        # Task Role - Bedrock 및 Secrets Manager 접근 권한
        task_role = iam.Role(
            self, "NotionChatbotTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ]
        )

        # S3 접근 권한 추가
        data_bucket.grant_read(task_role)
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:ListBucket"
                ],
                resources=[data_bucket.bucket_arn]
            )
        )

        # OpenSearch 접근 권한 추가
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll"
                ],
                resources=["*"]
            )
        )

        # Bedrock Titan Embedding 모델 접근 권한 추가
        task_role.add_to_policy(
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

        # Lambda 호출 권한 추가 (기존 + 벡터 Lambda)
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:InvokeFunction"
                ],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:NotionChatbotBedrockStack-NotionSyncFunction*",
                    vector_lambda_arn
                ]
            )
        )

        # Bedrock 접근 권한 추가
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                    f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{knowledge_base_id}"
                ]
            )
        )

        # Secrets Manager 접근 권한 추가
        for secret in secrets.values():
            secret.grant_read(task_role)

        # Task Definition
        task_definition = ecs.FargateTaskDefinition(
            self, "NotionChatbotTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            task_role=task_role
        )

        # Container Definition
        container = task_definition.add_container(
            "NotionChatbotContainer",
            image=ecs.ContainerImage.from_registry("python:3.11-slim"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="notion-chatbot",
                log_group=logs.LogGroup(
                    self, "NotionChatbotLogGroup",
                    log_group_name="/ecs/notion-chatbot",
                    retention=logs.RetentionDays.ONE_WEEK
                )
            ),
            environment={
                "AWS_DEFAULT_REGION": self.region,
                "STREAMLIT_SERVER_PORT": "8501",
                "STREAMLIT_SERVER_ADDRESS": "0.0.0.0",
                "NOTION_TOKEN": "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",
                "KNOWLEDGE_BASE_ID": knowledge_base_id,
                "OPENSEARCH_ENDPOINT": opensearch_endpoint,
                "VECTOR_LAMBDA_ARN": vector_lambda_arn
            },
            secrets={
                "NOTION_TOKEN_SECRET_ARN": ecs.Secret.from_secrets_manager(secrets["notion_token"]),
                "APP_CONFIG_SECRET_ARN": ecs.Secret.from_secrets_manager(secrets["app_config"])
            },
            command=[
                "bash", "-c", 
                """
                pip install streamlit boto3 requests notion-client opensearch-py &&
                mkdir -p /app && cd /app &&
                cat > app.py << 'STREAMLIT_EOF'
import streamlit as st
import boto3
import json
import os
import requests
from datetime import datetime
from typing import List, Dict, Any

st.set_page_config(page_title='무엇이든 물어보세요! 🤖', page_icon='🤖', layout='wide')

st.markdown('<div style="text-align: center; padding: 1rem 0; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 10px; margin-bottom: 2rem;"><h1>🤖 무엇이든 물어보세요!</h1><p>Notion 지식 기반에서 답변을 찾아드립니다 (검색 방식 비교 데모)</p></div>', unsafe_allow_html=True)

# AWS 클라이언트 초기화
@st.cache_resource
def get_aws_clients():
    s3 = boto3.client('s3', region_name='ap-northeast-2')
    bedrock = boto3.client('bedrock-runtime', region_name='ap-northeast-2')
    lambda_client = boto3.client('lambda', region_name='ap-northeast-2')
    return s3, bedrock, lambda_client

s3_client, bedrock_client, lambda_client = get_aws_clients()
knowledge_base_id = os.getenv('KNOWLEDGE_BASE_ID', 'simple-kb-demo')
opensearch_endpoint = os.getenv('OPENSEARCH_ENDPOINT', '')
vector_lambda_arn = os.getenv('VECTOR_LAMBDA_ARN', '')

class OpenSearchClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-2')
    
    def generate_embedding(self, text: str) -> List[float]:
        try:
            response = self.bedrock_client.invoke_model(
                modelId='amazon.titan-embed-text-v2:0',
                body=json.dumps({'inputText': text[:8000]})
            )
            response_body = json.loads(response['body'].read())
            return response_body['embedding']
        except Exception as e:
            st.error(f'임베딩 생성 오류: {str(e)}')
            return []
    
    def semantic_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            query_embedding = self.generate_embedding(query)
            if not query_embedding:
                return []
            
            search_body = {
                'size': limit,
                'query': {
                    'knn': {
                        'embedding': {
                            'vector': query_embedding,
                            'k': limit
                        }
                    }
                },
                '_source': ['id', 'title', 'content', 'url', 'metadata']
            }
            
            response = requests.post(
                f'{self.endpoint}/notion-index/_search',
                json=search_body,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                results = response.json()
                documents = []
                for hit in results.get('hits', {}).get('hits', []):
                    source = hit['_source']
                    documents.append({
                        'id': source.get('id'),
                        'title': source.get('title', '제목 없음'),
                        'content': source.get('content', ''),
                        'url': source.get('url', ''),
                        'similarity_score': hit['_score']
                    })
                return documents
            return []
        except Exception as e:
            st.error(f'의미 검색 오류: {str(e)}')
            return []

# OpenSearch 클라이언트 초기화
opensearch_client = None
if opensearch_endpoint:
    opensearch_client = OpenSearchClient(opensearch_endpoint)

def search_opensearch_documents(query, search_method='semantic'):
    try:
        if not opensearch_client:
            st.error('OpenSearch가 설정되지 않았습니다.')
            return []
        
        documents = opensearch_client.semantic_search(query, limit=5)
        return documents
        
    except Exception as e:
        st.error(f'OpenSearch 검색 오류: {str(e)}')
        return []

def search_s3_documents(query, bucket_name):
    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix='notion-data/',
            MaxKeys=50
        )
        
        documents = []
        
        if 'Contents' in response:
            for obj in response['Contents']:
                if obj['Key'].endswith('.json'):
                    doc_response = s3_client.get_object(
                        Bucket=bucket_name,
                        Key=obj['Key']
                    )
                    doc_content = json.loads(doc_response['Body'].read())
                    
                    query_lower = query.lower()
                    title_lower = doc_content.get('title', '').lower()
                    content_lower = doc_content.get('content', '').lower()
                    
                    if any(word in title_lower or word in content_lower for word in query_lower.split()):
                        documents.append(doc_content)
        
        return documents[:5]
        
    except Exception as e:
        st.error(f'S3 검색 오류: {str(e)}')
        return []

def generate_bedrock_response(query, documents):
    try:
        context_parts = []
        for doc in documents:
            title = doc.get('title', '제목 없음')
            content = doc.get('content', '')[:500]
            context_parts.append(f'문서: {title}\\n내용: {content}')
        
        context = '\\n\\n'.join(context_parts)
        
        prompt = f'''사용자 질문: {query}

관련 Notion 문서들:
{context}

위의 Notion 문서 내용을 바탕으로 사용자의 질문에 정확하고 도움이 되는 답변을 한국어로 제공해주세요.'''
        
        body = {
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 2000,
            'temperature': 0.1,
            'messages': [{'role': 'user', 'content': prompt}]
        }
        
        response = bedrock_client.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps(body)
        )
        
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
        
    except Exception as e:
        return f'답변 생성 중 오류가 발생했습니다: {str(e)}'

# 채팅 히스토리 초기화
if 'messages' not in st.session_state:
    st.session_state.messages = []

# 사이드바
with st.sidebar:
    st.markdown('## ⚙️ 설정')
    
    # 검색 방식 선택
    st.markdown('### 🔍 검색 방식 선택')
    search_method = st.selectbox(
        '검색 방식을 선택하세요:',
        ['S3 키워드 검색', 'OpenSearch 의미 검색'],
        help='S3: 키워드 매칭 기반, OpenSearch: 의미 기반 벡터 검색'
    )
    
    # 검색 방식별 설명
    if search_method == 'S3 키워드 검색':
        st.info('📝 키워드 매칭 기반 검색\\n- 빠른 속도\\n- 정확한 키워드 일치\\n- 비용 효율적')
    else:
        st.info('🧠 의미 기반 벡터 검색\\n- 문맥 이해\\n- 유사한 의미 검색\\n- 높은 정확도')
    
    # Knowledge Base 정보
    st.markdown('### 🧠 Knowledge Base')
    if search_method == 'S3 키워드 검색':
        st.success(f'S3 기반 검색: {knowledge_base_id}')
    else:
        if opensearch_endpoint:
            st.success('OpenSearch Serverless 연결됨')
        else:
            st.warning('OpenSearch 설정 필요')
    
    if st.button('🗑️ 대화 초기화'):
        st.session_state.messages = []
        st.rerun()

# 이전 메시지들 표시
for message in st.session_state.messages:
    with st.chat_message(message['role']):
        st.markdown(message['content'])
        if message.get('sources'):
            with st.expander('📚 참고 문서'):
                for i, source in enumerate(message['sources'], 1):
                    st.markdown(f'**{i}. {source.get("title", "문서")}**')
                    content_preview = source.get("content", "내용 없음")[:200]
                    st.markdown(f'내용: {content_preview}...')
                    if source.get('url'):
                        st.markdown(f'[📄 원본 보기]({source["url"]})')
                    if source.get('similarity_score'):
                        st.markdown(f'유사도 점수: {source["similarity_score"]:.3f}')
                    st.markdown('---')

# 사용자 입력
if prompt := st.chat_input('무엇이든 물어보세요! 예: 프로젝트 일정은 어떻게 되나요?'):
    st.session_state.messages.append({'role': 'user', 'content': prompt})
    
    with st.chat_message('user'):
        st.markdown(prompt)
    
    with st.chat_message('assistant'):
        with st.spinner('관련 문서를 검색하고 답변을 생성하고 있습니다... 🤔'):
            try:
                bucket_name = f'notion-chatbot-data-965037532757-ap-northeast-2'
                
                # 선택된 검색 방식에 따라 문서 검색
                if search_method == 'S3 키워드 검색':
                    documents = search_s3_documents(prompt, bucket_name)
                    search_info = f'🔍 S3 키워드 검색 사용'
                else:
                    documents = search_opensearch_documents(prompt)
                    search_info = f'🧠 OpenSearch 의미 검색 사용'
                
                st.info(search_info)
                
                if documents:
                    # Bedrock으로 RAG 응답 생성
                    answer = generate_bedrock_response(prompt, documents)
                    st.markdown(answer)
                    
                    # 참고 문서 표시
                    with st.expander('📚 참고 문서', expanded=True):
                        for i, doc in enumerate(documents[:3], 1):
                            st.markdown(f'**{i}. {doc.get("title", "문서")}**')
                            content_preview = doc.get('content', '내용 없음')[:200]
                            st.markdown(f'내용: {content_preview}...')
                            if doc.get('url'):
                                st.markdown(f'[📄 원본 보기]({doc["url"]})')
                            if doc.get('similarity_score'):
                                st.markdown(f'유사도 점수: {doc["similarity_score"]:.3f}')
                            st.markdown('---')
                    
                    # 메시지 히스토리에 추가
                    st.session_state.messages.append({
                        'role': 'assistant', 
                        'content': answer,
                        'sources': documents
                    })
                else:
                    no_result_msg = '죄송합니다. 관련된 정보를 찾을 수 없습니다. Notion 데이터가 동기화되었는지 확인해주세요.'
                    st.markdown(no_result_msg)
                    st.session_state.messages.append({'role': 'assistant', 'content': no_result_msg})
                    
            except Exception as e:
                error_msg = f'오류가 발생했습니다: {str(e)}'
                st.error(error_msg)
                st.session_state.messages.append({'role': 'assistant', 'content': error_msg})

st.markdown('---')
st.markdown('<div style="text-align: center; color: #666; padding: 1rem;"><p>🔍 S3 키워드 검색 vs 🧠 OpenSearch 의미 검색 비교 데모</p><p>📚 두 가지 검색 방식의 차이를 직접 체험해보세요</p><p>🔄 1시간마다 Notion 데이터 자동 동기화</p></div>', unsafe_allow_html=True)
STREAMLIT_EOF
                streamlit run app.py --server.port=8501 --server.address=0.0.0.0
                """
            ]
        )

        # Port Mapping
        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8501,
                protocol=ecs.Protocol.TCP
            )
        )

        # Application Load Balanced Fargate Service
        self.fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "NotionChatbotService",
            cluster=cluster,
            task_definition=task_definition,
            public_load_balancer=True,
            listener_port=80,
            desired_count=1,  # 비용 절약을 위해 1개 인스턴스
            platform_version=ecs.FargatePlatformVersion.LATEST,
            assign_public_ip=True,
            service_name="notion-chatbot-service"
        )

        # Health Check 설정
        self.fargate_service.target_group.configure_health_check(
            path="/",
            healthy_http_codes="200",
            timeout=Duration.seconds(10),
            interval=Duration.seconds(30),
            healthy_threshold_count=2,
            unhealthy_threshold_count=5
        )

        # Auto Scaling 설정 (선택사항)
        scaling = self.fargate_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=3
        )

        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.minutes(5),
            scale_out_cooldown=Duration.minutes(2)
        )

        # Outputs
        CfnOutput(
            self, "LoadBalancerDNS",
            value=self.fargate_service.load_balancer.load_balancer_dns_name,
            description="Load Balancer DNS Name"
        )

        CfnOutput(
            self, "ServiceURL",
            value=f"http://{self.fargate_service.load_balancer.load_balancer_dns_name}",
            description="Notion Chatbot Service URL"
        )
