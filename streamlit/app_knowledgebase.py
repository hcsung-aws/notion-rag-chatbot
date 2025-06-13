import streamlit as st
import boto3
import json
import os
import requests
from datetime import datetime
from typing import List, Dict, Any

st.set_page_config(page_title='무엇이든 물어보세요! 🤖', page_icon='🤖', layout='wide')

st.markdown('<div style="text-align: center; padding: 1rem 0; background: linear-gradient(90deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 10px; margin-bottom: 2rem;"><h1>🤖 무엇이든 물어보세요!</h1><p>Notion 지식 기반에서 답변을 찾아드립니다 (KnowledgeBase vs S3 검색 비교)</p></div>', unsafe_allow_html=True)

# AWS 클라이언트 초기화
@st.cache_resource
def get_aws_clients():
    s3 = boto3.client('s3', region_name='ap-northeast-2')
    bedrock = boto3.client('bedrock-runtime', region_name='ap-northeast-2')
    bedrock_agent = boto3.client('bedrock-agent-runtime', region_name='ap-northeast-2')
    lambda_client = boto3.client('lambda', region_name='ap-northeast-2')
    return s3, bedrock, bedrock_agent, lambda_client

s3_client, bedrock_client, bedrock_agent_client, lambda_client = get_aws_clients()
knowledge_base_id = os.getenv('KNOWLEDGE_BASE_ID', 'UXF2GSP5IT')
opensearch_endpoint = os.getenv('OPENSEARCH_ENDPOINT', '')
vector_lambda_arn = os.getenv('VECTOR_LAMBDA_ARN', '')

def get_document_info_from_s3(s3_key, bucket_name):
    """S3에서 문서 정보 (제목, URL, 내용) 추출"""
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        content = response['Body'].read().decode('utf-8')
        
        # JSON 파싱하여 제목, URL, 내용 추출
        import json
        doc_data = json.loads(content)
        
        title = doc_data.get('title', '제목 없음')
        url = doc_data.get('url', '')
        content_text = doc_data.get('content', '')
        
        return title, url, content_text
    except Exception as e:
        # 파일명에서 제목 추출 시도
        filename = s3_key.split('/')[-1] if '/' in s3_key else s3_key
        title = filename.replace('.json', '').replace('_', ' ')
        return title, '', ''
    """Bedrock KnowledgeBase를 사용한 검색"""
    try:
        response = bedrock_agent_client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={
                'text': query
            },
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': 5
                }
            }
        )
        
        documents = []
        for result in response.get('retrievalResults', []):
            documents.append({
                'content': result.get('content', {}).get('text', ''),
                'metadata': result.get('metadata', {}),
                'score': result.get('score', 0),
                'location': result.get('location', {})
            })
        
        return documents
        
    except Exception as e:
        st.error(f'KnowledgeBase 검색 오류: {str(e)}')
        return []

def generate_knowledgebase_response_with_context(query, knowledge_base_id, conversation_history):
    """KnowledgeBase를 사용한 RAG 응답 생성 + 참고 문서 정보 + 대화 컨텍스트"""
    try:
        # 대화 히스토리를 포함한 컨텍스트 구성
        context_query = query
        if conversation_history:
            # 최근 3개 대화만 컨텍스트로 사용 (토큰 제한 고려)
            recent_history = conversation_history[-6:]  # 사용자-어시스턴트 쌍 3개
            context_parts = []
            
            for i in range(0, len(recent_history), 2):
                if i + 1 < len(recent_history):
                    user_msg = recent_history[i]['content']
                    assistant_msg = recent_history[i + 1]['content']
                    context_parts.append(f"이전 질문: {user_msg}\n이전 답변: {assistant_msg}")
            
            if context_parts:
                context_query = f"이전 대화 내용:\n{chr(10).join(context_parts)}\n\n현재 질문: {query}"
        
        # 1. retrieve_and_generate로 답변 생성 (실제 KnowledgeBase 사용)
        rag_response = bedrock_agent_client.retrieve_and_generate(
            input={
                'text': context_query
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': knowledge_base_id,
                    'modelArn': f'arn:aws:bedrock:ap-northeast-2::foundation-model/anthropic.claude-3-haiku-20240307-v1:0'
                }
            }
        )
        
        answer = rag_response.get('output', {}).get('text', '')
        citations = rag_response.get('citations', [])
        
        # 2. citations가 없거나 부족하면 별도로 retrieve API 호출하여 참고 문서 정보 보강
        if not citations or len(citations) == 0:
            retrieve_response = bedrock_agent_client.retrieve(
                knowledgeBaseId=knowledge_base_id,
                retrievalQuery={
                    'text': query  # 원본 질문으로 검색 (컨텍스트 제외)
                },
                retrievalConfiguration={
                    'vectorSearchConfiguration': {
                        'numberOfResults': 5
                    }
                }
            )
            
            # retrieve 결과를 citations 형태로 변환
            citations = []
            for result in retrieve_response.get('retrievalResults', []):
                citation = {
                    'retrievedReferences': [{
                        'content': result.get('content', {}),
                        'location': result.get('location', {}),
                        'metadata': result.get('metadata', {}),
                        'score': result.get('score', 0)
                    }]
                }
                citations.append(citation)
        
        return answer, citations
        
    except Exception as e:
        return f'답변 생성 중 오류가 발생했습니다: {str(e)}', []

def generate_s3_response_with_context(query, bucket_name, conversation_history):
    """S3 검색 결과를 컨텍스트로 사용하여 답변 생성 + 대화 컨텍스트"""
    try:
        # S3에서 문서 검색
        documents = search_s3_documents(query, bucket_name)
        
        if not documents:
            return '관련 문서를 찾을 수 없습니다.', []
        
        # 대화 히스토리 구성
        conversation_context = ""
        if conversation_history:
            recent_history = conversation_history[-4:]  # 최근 2개 대화 쌍
            context_parts = []
            
            for i in range(0, len(recent_history), 2):
                if i + 1 < len(recent_history):
                    user_msg = recent_history[i]['content']
                    assistant_msg = recent_history[i + 1]['content']
                    context_parts.append(f"사용자: {user_msg}\n어시스턴트: {assistant_msg}")
            
            if context_parts:
                conversation_context = f"\n\n이전 대화:\n{chr(10).join(context_parts)}\n"
        
        # 문서 컨텍스트 구성
        doc_context = "\n\n".join([f"문서 {i+1}: {doc['content']}" for i, doc in enumerate(documents[:3])])
        
        # 프롬프트 구성
        prompt = f"""다음 문서들과 이전 대화 내용을 참고하여 질문에 답변해주세요.

참고 문서:
{doc_context}{conversation_context}

현재 질문: {query}

답변:"""
        
        # Bedrock으로 답변 생성
        response = bedrock_client.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            })
        )
        
        result = json.loads(response['body'].read())
        answer = result['content'][0]['text']
        
        return answer, documents
        
    except Exception as e:
        return f'답변 생성 중 오류가 발생했습니다: {str(e)}', []

def search_s3_documents(query, bucket_name):
    """S3에서 직접 문서 검색 (기존 방식)"""
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
    """기존 방식의 Bedrock 응답 생성"""
    try:
        context_parts = []
        for doc in documents:
            title = doc.get('title', '제목 없음')
            content = doc.get('content', '')[:500]
            context_parts.append(f'문서: {title}\n내용: {content}')
        
        context = '\n\n'.join(context_parts)
        
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
        ['Bedrock KnowledgeBase', 'S3 키워드 검색'],
        help='KnowledgeBase: Bedrock 관리형 RAG, S3: 직접 키워드 검색'
    )
    
    # 검색 방식별 설명
    if search_method == 'Bedrock KnowledgeBase':
        st.info('🧠 Bedrock KnowledgeBase\n- 관리형 RAG 서비스\n- 자동 벡터화 및 청킹\n- 최적화된 검색 성능')
    else:
        st.info('📝 S3 키워드 검색\n- 직접 키워드 매칭\n- 빠른 속도\n- 비용 효율적')
    
    # 동기화 상태 확인 버튼
    if st.button('📊 KnowledgeBase 동기화 상태 확인'):
        try:
            with st.spinner('동기화 상태 확인 중...'):
                # 최근 ingestion job 상태 확인
                jobs_response = bedrock_agent_client.list_ingestion_jobs(
                    knowledgeBaseId=knowledge_base_id,
                    dataSourceId='X1FS4XS5HU',
                    maxResults=5
                )
                
                if jobs_response.get('ingestionJobSummaries'):
                    latest_job = jobs_response['ingestionJobSummaries'][0]
                    status = latest_job['status']
                    job_id = latest_job['ingestionJobId']
                    updated_at = latest_job['updatedAt']
                    
                    # 상세 정보 가져오기
                    job_detail = bedrock_agent_client.get_ingestion_job(
                        knowledgeBaseId=knowledge_base_id,
                        dataSourceId='X1FS4XS5HU',
                        ingestionJobId=job_id
                    )
                    
                    stats = job_detail['ingestionJob']['statistics']
                    
                    # 상태에 따른 아이콘과 색상
                    if status == 'COMPLETE':
                        st.success(f'✅ **동기화 완료** (Job ID: {job_id})')
                    elif status == 'IN_PROGRESS' or status == 'STARTING':
                        st.info(f'🔄 **동기화 진행 중** (Job ID: {job_id})')
                    elif status == 'FAILED':
                        st.error(f'❌ **동기화 실패** (Job ID: {job_id})')
                    else:
                        st.warning(f'⚠️ **상태: {status}** (Job ID: {job_id})')
                    
                    # 통계 정보 표시
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("스캔된 문서", stats.get('numberOfDocumentsScanned', 0))
                    with col2:
                        st.metric("인덱싱된 문서", stats.get('numberOfNewDocumentsIndexed', 0))
                    with col3:
                        st.metric("실패한 문서", stats.get('numberOfDocumentsFailed', 0))
                    
                    st.caption(f"마지막 업데이트: {updated_at}")
                    
                    # 실패한 경우 실패 이유 표시
                    if status == 'FAILED' and 'failureReasons' in job_detail['ingestionJob']:
                        st.error("실패 이유:")
                        for reason in job_detail['ingestionJob']['failureReasons']:
                            st.code(reason)
                else:
                    st.info('동기화 작업 기록이 없습니다.')
                    
        except Exception as e:
            st.error(f'상태 확인 실패: {str(e)}')
    
    # Knowledge Base 정보
    st.markdown('### 🧠 Knowledge Base')
    st.success(f'Knowledge Base ID: {knowledge_base_id}')
    
    # 대화 컨텍스트 상태 표시
    message_count = len(st.session_state.messages)
    if message_count > 0:
        st.info(f'💬 현재 대화 기록: {message_count//2}개 대화 (총 {message_count}개 메시지)')
        st.caption('💡 이전 대화 내용이 새로운 질문 답변에 활용됩니다.')
    else:
        st.info('💬 새로운 대화를 시작해보세요!')
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button('🗑️ 대화 초기화'):
            st.session_state.messages = []
            st.success('대화 기록이 초기화되었습니다!')
            st.rerun()
    
    with col2:
        if st.button('🔄 데이터 동기화'):
            try:
                with st.spinner('데이터 동기화 중...'):
                    # 1. S3 동기화 (Notion → S3)
                    response = lambda_client.invoke(
                        FunctionName='NotionChatbotBedrockStack-NotionSyncFunctionFFED61-DntTQBnmfaiG',
                        InvocationType='Event'
                )
                st.success('✅ S3 동기화 작업을 시작했습니다!')
                
                # 2. KnowledgeBase 동기화 (S3 → KnowledgeBase)
                kb_response = bedrock_agent_client.start_ingestion_job(
                    knowledgeBaseId=knowledge_base_id,
                    dataSourceId='X1FS4XS5HU'  # 현재 사용 중인 데이터 소스 ID
                )
                
                ingestion_job_id = kb_response['ingestionJob']['ingestionJobId']
                st.success(f'✅ KnowledgeBase 동기화 작업을 시작했습니다! (Job ID: {ingestion_job_id})')
                st.info('💡 동기화 완료까지 1-2분 정도 소요될 수 있습니다.')
                
            except Exception as e:
                st.error(f'❌ 동기화 실행 실패: {str(e)}')

# 이전 메시지들 표시
for message in st.session_state.messages:
    with st.chat_message(message['role']):
        st.markdown(message['content'])
        if message.get('sources'):
            with st.expander('📚 참고 문서'):
                bucket_name = 'notion-chatbot-data-965037532757-ap-northeast-2'
                
                for i, source in enumerate(message['sources'], 1):
                    if isinstance(source, dict):
                        # KnowledgeBase citations 구조 처리
                        if 'retrievedReferences' in source:
                            for ref in source['retrievedReferences']:
                                # S3 위치에서 문서 정보 추출
                                location = ref.get('location', {})
                                title = f"문서 {i}"
                                url = ""
                                s3_content = ""
                                
                                if location.get('s3Location'):
                                    s3_loc = location['s3Location']
                                    key = s3_loc.get('objectKey', '')
                                    if key:
                                        try:
                                            title, url, s3_content = get_document_info_from_s3(key, bucket_name)
                                        except Exception as e:
                                            filename = key.split('/')[-1] if '/' in key else key
                                            title = filename.replace('.json', '').replace('_', ' ')
                                
                                # S3 검색과 완전히 동일한 포맷으로 표시
                                st.markdown(f'**{i}. {title}**')
                                
                                # S3에서 가져온 내용이 있으면 사용, 없으면 KnowledgeBase 내용 사용
                                if s3_content:
                                    content_preview = s3_content[:200] + '...' if len(s3_content) > 200 else s3_content
                                else:
                                    # KnowledgeBase에서 가져온 내용 사용
                                    content = ref.get('content', {})
                                    if isinstance(content, dict):
                                        content_text = content.get('text', '')
                                    else:
                                        content_text = str(content)
                                    content_preview = content_text[:200] + '...' if len(content_text) > 200 else content_text
                                
                                st.markdown(f'내용: {content_preview}')
                                
                                # URL이 있으면 원본 보기 링크 표시 (S3 검색과 동일)
                                if url:
                                    st.markdown(f'[📄 원본 보기]({url})')
                        
                        # S3 직접 검색 방식 (기존)
                        elif 'title' in source:
                            st.markdown(f'**{i}. {source.get("title", "문서")}**')
                            content_preview = source.get("content", "내용 없음")[:200]
                            st.markdown(f'내용: {content_preview}...')
                            if source.get('url'):
                                st.markdown(f'[📄 원본 보기]({source["url"]})')
                        
                        # 기타 형태
                        else:
                            st.markdown(f'**{i}. 문서 {i}**')
                            content_preview = source.get("content", "내용 없음")[:200]
                            st.markdown(f'내용: {content_preview}...')
                            if source.get('score'):
                                st.markdown(f'관련도 점수: {source["score"]:.3f}')
                    st.markdown('---')

# 사용자 입력
if prompt := st.chat_input('무엇이든 물어보세요! 예: 프로젝트 일정은 어떻게 되나요?'):
    st.session_state.messages.append({'role': 'user', 'content': prompt})
    
    with st.chat_message('user'):
        st.markdown(prompt)
    
    with st.chat_message('assistant'):
        with st.spinner('관련 문서를 검색하고 답변을 생성하고 있습니다... 🤔'):
            try:
                if search_method == 'Bedrock KnowledgeBase':
                    # KnowledgeBase 사용 (대화 컨텍스트 포함)
                    answer, citations = generate_knowledgebase_response_with_context(
                        prompt, 
                        knowledge_base_id, 
                        st.session_state.messages
                    )
                    search_info = '🧠 Bedrock KnowledgeBase 사용 (대화 컨텍스트 포함)'
                    
                    st.info(search_info)
                    st.markdown(answer)
                    
                    if citations:
                        with st.expander('📚 참고 문서', expanded=True):
                            bucket_name = 'notion-chatbot-data-965037532757-ap-northeast-2'
                            
                            for i, citation in enumerate(citations, 1):
                                if 'retrievedReferences' in citation:
                                    for ref in citation['retrievedReferences']:
                                        # S3 위치에서 문서 정보 추출
                                        location = ref.get('location', {})
                                        title = f"문서 {i}"
                                        url = ""
                                        s3_content = ""
                                        
                                        if location.get('s3Location'):
                                            s3_loc = location['s3Location']
                                            key = s3_loc.get('objectKey', '')
                                            if key:
                                                try:
                                                    title, url, s3_content = get_document_info_from_s3(key, bucket_name)
                                                except Exception as e:
                                                    # 파일명에서 제목 추출
                                                    filename = key.split('/')[-1] if '/' in key else key
                                                    title = filename.replace('.json', '').replace('_', ' ')
                                        
                                        # S3 검색과 완전히 동일한 포맷으로 표시
                                        st.markdown(f'**{i}. {title}**')
                                        
                                        # S3에서 가져온 내용이 있으면 사용, 없으면 KnowledgeBase 내용 사용
                                        if s3_content:
                                            content_preview = s3_content[:200] + '...' if len(s3_content) > 200 else s3_content
                                        else:
                                            # KnowledgeBase에서 가져온 내용 사용
                                            content = ref.get('content', {})
                                            if isinstance(content, dict):
                                                content_text = content.get('text', '')
                                            else:
                                                content_text = str(content)
                                            content_preview = content_text[:200] + '...' if len(content_text) > 200 else content_text
                                        
                                        st.markdown(f'내용: {content_preview}')
                                        
                                        # URL이 있으면 원본 보기 링크 표시 (S3 검색과 동일)
                                        if url:
                                            st.markdown(f'[📄 원본 보기]({url})')
                                        
                                        st.markdown('---')
                        
                        # 메시지 히스토리에 추가
                        st.session_state.messages.append({
                            'role': 'assistant', 
                            'content': answer,
                            'sources': citations
                        })
                    else:
                        st.warning('참고 문서를 찾을 수 없습니다.')
                        st.session_state.messages.append({
                            'role': 'assistant', 
                            'content': answer
                        })
                
                else:
                    # S3 직접 검색 사용 (대화 컨텍스트 포함)
                    bucket_name = f'notion-chatbot-data-965037532757-ap-northeast-2'
                    answer, documents = generate_s3_response_with_context(
                        prompt, 
                        bucket_name, 
                        st.session_state.messages
                    )
                    search_info = '📝 S3 키워드 검색 사용 (대화 컨텍스트 포함)'
                    
                    st.info(search_info)
                    st.markdown(answer)
                    
                    if documents:
                        # 참고 문서 표시
                        with st.expander('📚 참고 문서', expanded=True):
                            for i, doc in enumerate(documents[:3], 1):
                                st.markdown(f'**{i}. {doc.get("title", "문서")}**')
                                content_preview = doc.get('content', '내용 없음')[:200]
                                st.markdown(f'내용: {content_preview}...')
                                if doc.get('url'):
                                    st.markdown(f'[📄 원본 보기]({doc["url"]})')
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
st.markdown('<div style="text-align: center; color: #666; padding: 1rem;"><p>🧠 Bedrock KnowledgeBase vs 📝 S3 키워드 검색 비교 데모</p><p>🔄 관리형 RAG 서비스와 직접 구현 방식의 차이를 체험해보세요</p></div>', unsafe_allow_html=True)
