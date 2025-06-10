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
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v1"
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
                "sh", "-c", 
                "pip install streamlit boto3 requests notion-client opensearch-py && "
                "mkdir -p /app && cd /app && "
                "cat > opensearch_client.py << 'OPENSEARCH_EOF'\n"
                "import json\n"
                "import boto3\n"
                "import requests\n"
                "from typing import List, Dict, Any\n"
                "import streamlit as st\n"
                "\n"
                "class OpenSearchClient:\n"
                "    def __init__(self, endpoint: str):\n"
                "        self.endpoint = endpoint\n"
                "        self.bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-2')\n"
                "    \n"
                "    def generate_embedding(self, text: str) -> List[float]:\n"
                "        try:\n"
                "            response = self.bedrock_client.invoke_model(\n"
                "                modelId='amazon.titan-embed-text-v1',\n"
                "                body=json.dumps({'inputText': text[:8000]})\n"
                "            )\n"
                "            response_body = json.loads(response['body'].read())\n"
                "            return response_body['embedding']\n"
                "        except Exception as e:\n"
                "            st.error(f'임베딩 생성 오류: {str(e)}')\n"
                "            return []\n"
                "    \n"
                "    def semantic_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:\n"
                "        try:\n"
                "            query_embedding = self.generate_embedding(query)\n"
                "            if not query_embedding:\n"
                "                return []\n"
                "            \n"
                "            search_body = {\n"
                "                'size': limit,\n"
                "                'query': {\n"
                "                    'knn': {\n"
                "                        'embedding': {\n"
                "                            'vector': query_embedding,\n"
                "                            'k': limit\n"
                "                        }\n"
                "                    }\n"
                "                },\n"
                "                '_source': ['id', 'title', 'content', 'url', 'metadata']\n"
                "            }\n"
                "            \n"
                "            response = requests.post(\n"
                "                f'{self.endpoint}/notion-index/_search',\n"
                "                json=search_body,\n"
                "                headers={'Content-Type': 'application/json'}\n"
                "            )\n"
                "            \n"
                "            if response.status_code == 200:\n"
                "                results = response.json()\n"
                "                documents = []\n"
                "                for hit in results.get('hits', {}).get('hits', []):\n"
                "                    source = hit['_source']\n"
                "                    documents.append({\n"
                "                        'id': source.get('id'),\n"
                "                        'title': source.get('title', '제목 없음'),\n"
                "                        'content': source.get('content', ''),\n"
                "                        'url': source.get('url', ''),\n"
                "                        'similarity_score': hit['_score']\n"
                "                    })\n"
                "                return documents\n"
                "            return []\n"
                "        except Exception as e:\n"
                "            st.error(f'의미 검색 오류: {str(e)}')\n"
                "            return []\n"
                "OPENSEARCH_EOF\n"
                "cat > app.py << 'EOF'\n"
                "import streamlit as st\n"
                "import boto3\n"
                "import json\n"
                "import os\n"
                "from datetime import datetime\n"
                "from opensearch_client import OpenSearchClient\n"
                "\n"
                "st.set_page_config(page_title='무엇이든 물어보세요! 🤖', page_icon='🤖', layout='wide')\n"
                "\n"
                "st.markdown('<div style=\"text-align: center; padding: 1rem 0; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 10px; margin-bottom: 2rem;\"><h1>🤖 무엇이든 물어보세요!</h1><p>Notion 지식 기반에서 답변을 찾아드립니다 (검색 방식 비교 데모)</p></div>', unsafe_allow_html=True)\n"
                "\n"
                "# AWS 클라이언트 초기화\n"
                "@st.cache_resource\n"
                "def get_aws_clients():\n"
                "    s3 = boto3.client('s3', region_name='ap-northeast-2')\n"
                "    bedrock = boto3.client('bedrock-runtime', region_name='ap-northeast-2')\n"
                "    lambda_client = boto3.client('lambda', region_name='ap-northeast-2')\n"
                "    return s3, bedrock, lambda_client\n"
                "\n"
                "s3_client, bedrock_client, lambda_client = get_aws_clients()\n"
                "knowledge_base_id = os.getenv('KNOWLEDGE_BASE_ID', 'simple-kb-demo')\n"
                "opensearch_endpoint = os.getenv('OPENSEARCH_ENDPOINT', '')\n"
                "vector_lambda_arn = os.getenv('VECTOR_LAMBDA_ARN', '')\n"
                "\n"
                "# OpenSearch 클라이언트 초기화\n"
                "opensearch_client = None\n"
                "if opensearch_endpoint:\n"
                "    opensearch_client = OpenSearchClient(opensearch_endpoint)\n"
                "\n"
                "                "def search_opensearch_documents(query, search_method='semantic'):\n"
                "    '''OpenSearch를 사용한 의미 기반 검색'''\n"
                "    try:\n"
                "        if not opensearch_client:\n"
                "            st.error('OpenSearch가 설정되지 않았습니다.')\n"
                "            return []\n"
                "        \n"
                "        if search_method == 'semantic':\n"
                "            documents = opensearch_client.semantic_search(query, limit=5)\n"
                "        else:\n"
                "            documents = opensearch_client.hybrid_search(query, limit=5)\n"
                "        \n"
                "        return documents\n"
                "        \n"
                "    except Exception as e:\n"
                "        st.error(f'OpenSearch 검색 오류: {str(e)}')\n"
                "        return []\n"
                "\n"\n"
                "    '''S3에서 Notion 문서 검색'''\n"
                "    try:\n"
                "        # S3에서 notion-data/ 폴더의 모든 JSON 파일 나열\n"
                "        response = s3_client.list_objects_v2(\n"
                "            Bucket=bucket_name,\n"
                "            Prefix='notion-data/',\n"
                "            MaxKeys=50\n"
                "        )\n"
                "        \n"
                "        documents = []\n"
                "        \n"
                "        if 'Contents' in response:\n"
                "            for obj in response['Contents']:\n"
                "                if obj['Key'].endswith('.json'):\n"
                "                    # 각 문서 내용 가져오기\n"
                "                    doc_response = s3_client.get_object(\n"
                "                        Bucket=bucket_name,\n"
                "                        Key=obj['Key']\n"
                "                    )\n"
                "                    doc_content = json.loads(doc_response['Body'].read())\n"
                "                    \n"
                "                    # 간단한 키워드 매칭으로 관련성 확인\n"
                "                    query_lower = query.lower()\n"
                "                    title_lower = doc_content.get('title', '').lower()\n"
                "                    content_lower = doc_content.get('content', '').lower()\n"
                "                    \n"
                "                    # 키워드가 제목이나 내용에 포함되어 있으면 관련 문서로 판단\n"
                "                    if any(word in title_lower or word in content_lower for word in query_lower.split()):\n"
                "                        documents.append(doc_content)\n"
                "        \n"
                "        return documents[:5]  # 최대 5개 문서 반환\n"
                "        \n"
                "    except Exception as e:\n"
                "        st.error(f'S3 검색 오류: {str(e)}')\n"
                "        return []\n"
                "\n"
                "def generate_bedrock_response(query, documents):\n"
                "    '''Bedrock으로 RAG 응답 생성'''\n"
                "    try:\n"
                "        # 문서 컨텍스트 구성\n"
                "        context_parts = []\n"
                "        for doc in documents:\n"
                "            title = doc.get('title', '제목 없음')\n"
                "            content = doc.get('content', '')[:500]  # 처음 500자만 사용\n"
                "            context_parts.append(f'문서: {title}\\n내용: {content}')\n"
                "        \n"
                "        context = '\\n\\n'.join(context_parts)\n"
                "        \n"
                "        # Claude 3 Haiku 프롬프트\n"
                "        prompt = f'''사용자 질문: {query}\n"
                "\n"
                "관련 Notion 문서들:\n"
                "{context}\n"
                "\n"
                "위의 Notion 문서 내용을 바탕으로 사용자의 질문에 정확하고 도움이 되는 답변을 한국어로 제공해주세요. 답변할 때는 다음 사항을 지켜주세요:\n"
                "1. 제공된 문서 내용을 기반으로만 답변하세요\n"
                "2. 확실하지 않은 정보는 추측하지 마세요\n"
                "3. 자연스럽고 친근하게 답변하세요\n"
                "4. 가능하면 구체적인 예시나 세부사항을 포함하세요'''\n"
                "        \n"
                "        # Bedrock 호출\n"
                "        body = {\n"
                "            'anthropic_version': 'bedrock-2023-05-31',\n"
                "            'max_tokens': 2000,\n"
                "            'temperature': 0.1,\n"
                "            'messages': [{'role': 'user', 'content': prompt}]\n"
                "        }\n"
                "        \n"
                "        response = bedrock_client.invoke_model(\n"
                "            modelId='anthropic.claude-3-haiku-20240307-v1:0',\n"
                "            body=json.dumps(body)\n"
                "        )\n"
                "        \n"
                "        response_body = json.loads(response['body'].read())\n"
                "        return response_body['content'][0]['text']\n"
                "        \n"
                "    except Exception as e:\n"
                "        return f'답변 생성 중 오류가 발생했습니다: {str(e)}'\n"
                "\n"
                "# 채팅 히스토리 초기화\n"
                "if 'messages' not in st.session_state:\n"
                "    st.session_state.messages = []\n"
                "\n"
                "# 이전 메시지들 표시\n"
                "for message in st.session_state.messages:\n"
                "    with st.chat_message(message['role']):\n"
                "        st.markdown(message['content'])\n"
                "        if message.get('sources'):\n"
                "            with st.expander('📚 참고 문서'):\n"
                "                for i, source in enumerate(message['sources'], 1):\n"
                "                    st.markdown(f'**{i}. {source.get(\"title\", \"문서\")}**')\n"
                "                    content_preview = source.get(\"content\", \"내용 없음\")[:200]\n"
                "                    st.markdown(f'내용: {content_preview}...')\n"
                "                    if source.get('url'):\n"
                "                        st.markdown(f'[📄 원본 보기]({source[\"url\"]})')\n"
                "                    st.markdown('---')\n"
                "\n"
                "# 사용자 입력\n"
                "if prompt := st.chat_input('무엇이든 물어보세요! 예: 프로젝트 일정은 어떻게 되나요?'):\n"
                "    st.session_state.messages.append({'role': 'user', 'content': prompt})\n"
                "    \n"
                "    with st.chat_message('user'):\n"
                "        st.markdown(prompt)\n"
                "    \n"
                "    with st.chat_message('assistant'):\n"
                "        with st.spinner('S3에서 관련 문서를 검색하고 답변을 생성하고 있습니다... 🤔'):\n"
                "            try:\n"
                "                # S3 버킷 이름\n"
                "                bucket_name = f'notion-chatbot-data-965037532757-ap-northeast-2'\n"
                "                \n"
                "                # 선택된 검색 방식에 따라 문서 검색\n"
                "                if search_method == 'S3 키워드 검색':\n"
                "                    documents = search_s3_documents(prompt, bucket_name)\n"
                "                    search_info = f'🔍 S3 키워드 검색 사용'\n"
                "                else:\n"
                "                    documents = search_opensearch_documents(prompt)\n"
                "                    search_info = f'🧠 OpenSearch 의미 검색 사용'\n"
                "                \n"
                "                st.info(search_info)\n"
                "                \n"
                "                if documents:\n"
                "                    # Bedrock으로 RAG 응답 생성\n"
                "                    answer = generate_bedrock_response(prompt, documents)\n"
                "                    st.markdown(answer)\n"
                "                    \n"
                "                    # 참고 문서 표시\n"
                "                    with st.expander('📚 참고 문서', expanded=True):\n"
                "                        for i, doc in enumerate(documents[:3], 1):\n"
                "                            st.markdown(f'**{i}. {doc.get(\"title\", \"문서\")}**')\n"
                "                            content_preview = doc.get('content', '내용 없음')[:200]\n"
                "                            st.markdown(f'내용: {content_preview}...')\n"
                "                            if doc.get('url'):\n"
                "                                st.markdown(f'[📄 원본 보기]({doc[\"url\"]})')\n"
                "                            st.markdown('---')\n"
                "                    \n"
                "                    # 메시지 히스토리에 추가\n"
                "                    st.session_state.messages.append({\n"
                "                        'role': 'assistant', \n"
                "                        'content': answer,\n"
                "                        'sources': documents\n"
                "                    })\n"
                "                else:\n"
                "                    no_result_msg = '죄송합니다. 관련된 정보를 찾을 수 없습니다. Notion 데이터가 동기화되었는지 확인해주세요.'\n"
                "                    st.markdown(no_result_msg)\n"
                "                    st.session_state.messages.append({'role': 'assistant', 'content': no_result_msg})\n"
                "                    \n"
                "            except Exception as e:\n"
                "                error_msg = f'오류가 발생했습니다: {str(e)}'\n"
                "                st.error(error_msg)\n"
                "                st.session_state.messages.append({'role': 'assistant', 'content': error_msg})\n"
                "\n"
                "# 사이드바\n"
                "with st.sidebar:\n"
                "    st.markdown('## ⚙️ 설정')\n"
                "    \n"
                "    # 검색 방식 선택\n"
                "    st.markdown('### 🔍 검색 방식 선택')\n"
                "    search_method = st.selectbox(\n"
                "        '검색 방식을 선택하세요:',\n"
                "        ['S3 키워드 검색', 'OpenSearch 의미 검색'],\n"
                "        help='S3: 키워드 매칭 기반, OpenSearch: 의미 기반 벡터 검색'\n"
                "    )\n"
                "    \n"
                "    # 검색 방식별 설명\n"
                "    if search_method == 'S3 키워드 검색':\n"
                "        st.info('📝 키워드 매칭 기반 검색\\n- 빠른 속도\\n- 정확한 키워드 일치\\n- 비용 효율적')\n"
                "    else:\n"
                "        st.info('🧠 의미 기반 벡터 검색\\n- 문맥 이해\\n- 유사한 의미 검색\\n- 높은 정확도')\n"
                "    \n"
                "    # Knowledge Base 정보\n"
                "    st.markdown('### 🧠 Knowledge Base')\n"
                "    st.success(f'S3 기반 검색: {knowledge_base_id}')\n"
                "    \n"
                "    if st.button('🗑️ 대화 초기화'):\n"
                "        st.session_state.messages = []\n"
                "        st.rerun()\n"
                "    \n"
                "    if st.button('🔄 데이터 동기화 실행'):\n"
                "        sync_type = st.radio('동기화 방식:', ['S3만 동기화', 'S3 + OpenSearch 동기화'])\n"
                "        \n"
                "        if st.button('동기화 시작'):\n"
                "            try:\n"
                "                # S3 동기화\n"
                "                response = lambda_client.invoke(\n"
                "                    FunctionName='NotionChatbotBedrockStack-NotionSyncFunctionFFED61-DntTQBnmfaiG',\n"
                "                    InvocationType='Event'\n"
                "                )\n"
                "                st.success('S3 동기화 작업을 시작했습니다!')\n"
                "                \n"
                "                # OpenSearch 동기화 (선택된 경우)\n"
                "                if sync_type == 'S3 + OpenSearch 동기화' and vector_lambda_arn:\n"
                "                    vector_response = lambda_client.invoke(\n"
                "                        FunctionName=vector_lambda_arn.split(':')[-1],\n"
                "                        InvocationType='Event'\n"
                "                    )\n"
                "                    st.success('OpenSearch 벡터 인덱싱 작업도 시작했습니다!')\n"
                "                    \n"
                "            except Exception as e:\n"
                "                st.error(f'동기화 실행 실패: {str(e)}')\n"
                "    \n"
                "    st.markdown('### 💡 S3 + RAG 방식 특징')\n"
                "    st.markdown('- Notion 데이터가 S3에 JSON으로 저장됨\\n- 키워드 기반 문서 검색\\n- Claude 3 Haiku로 컨텍스트 기반 답변\\n- 실시간 소스 추적 가능')\n"
                "    \n"
                "    st.markdown('### 📊 통계')\n"
                "    if st.session_state.messages:\n"
                "        total = len(st.session_state.messages)\n"
                "        user_msgs = len([m for m in st.session_state.messages if m['role'] == 'user'])\n"
                "        ai_msgs = len([m for m in st.session_state.messages if m['role'] == 'assistant'])\n"
                "        sources_count = sum(len(m.get('sources', [])) for m in st.session_state.messages if m['role'] == 'assistant')\n"
                "        \n"
                "        st.metric('총 메시지', total)\n"
                "        st.metric('사용자 질문', user_msgs)\n"
                "        st.metric('AI 응답', ai_msgs)\n"
                "        st.metric('참조 문서', sources_count)\n"
                "    \n"
                "    st.markdown('### 🔄 동기화 정보')\n"
                "    st.info('Notion 데이터는 1시간마다 자동 동기화됩니다.')\n"
                "    st.info('수동 동기화 버튼으로 즉시 업데이트 가능합니다.')\n"
                "\n"
                "st.markdown('---')\n"
                "st.markdown('<div style=\"text-align: center; color: #666; padding: 1rem;\"><p>🔍 S3 키워드 검색 vs 🧠 OpenSearch 의미 검색 비교 데모</p><p>📚 두 가지 검색 방식의 차이를 직접 체험해보세요</p><p>🔄 1시간마다 Notion 데이터 자동 동기화</p></div>', unsafe_allow_html=True)\n"
                "EOF\n"
                "streamlit run app.py --server.port=8501 --server.address=0.0.0.0"
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
