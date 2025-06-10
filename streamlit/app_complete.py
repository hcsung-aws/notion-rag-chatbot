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
                modelId='amazon.titan-embed-text-v1',
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
    '''OpenSearch를 사용한 의미 기반 검색'''
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
    '''S3에서 Notion 문서 검색'''
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
    '''Bedrock으로 RAG 응답 생성'''
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

위의 Notion 문서 내용을 바탕으로 사용자의 질문에 정확하고 도움이 되는 답변을 한국어로 제공해주세요. 답변할 때는 다음 사항을 지켜주세요:
1. 제공된 문서 내용을 기반으로만 답변하세요
2. 확실하지 않은 정보는 추측하지 마세요
3. 자연스럽고 친근하게 답변하세요
4. 가능하면 구체적인 예시나 세부사항을 포함하세요'''
        
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
        st.info('📝 키워드 매칭 기반 검색\n- 빠른 속도\n- 정확한 키워드 일치\n- 비용 효율적')
    else:
        st.info('🧠 의미 기반 벡터 검색\n- 문맥 이해\n- 유사한 의미 검색\n- 높은 정확도')
    
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
    
    if st.button('🔄 데이터 동기화 실행'):
        sync_type = st.radio('동기화 방식:', ['S3만 동기화', 'S3 + OpenSearch 동기화'])
        
        if st.button('동기화 시작'):
            try:
                # S3 동기화
                response = lambda_client.invoke(
                    FunctionName='NotionChatbotBedrockStack-NotionSyncFunctionFFED61-DntTQBnmfaiG',
                    InvocationType='Event'
                )
                st.success('S3 동기화 작업을 시작했습니다!')
                
                # OpenSearch 동기화 (선택된 경우)
                if sync_type == 'S3 + OpenSearch 동기화' and vector_lambda_arn:
                    vector_response = lambda_client.invoke(
                        FunctionName=vector_lambda_arn.split(':')[-1],
                        InvocationType='Event'
                    )
                    st.success('OpenSearch 벡터 인덱싱 작업도 시작했습니다!')
                    
            except Exception as e:
                st.error(f'동기화 실행 실패: {str(e)}')

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
