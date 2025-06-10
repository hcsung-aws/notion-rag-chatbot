import os
import json
import boto3
from botocore.exceptions import ClientError
import streamlit as st

def load_config():
    """설정 로드 (AWS Secrets Manager 또는 환경 변수)"""
    config = {}
    
    try:
        # AWS Secrets Manager에서 설정 로드
        if os.getenv('AWS_DEFAULT_REGION'):
            config.update(load_from_secrets_manager())
        else:
            # 로컬 개발 환경에서는 환경 변수 사용
            config.update(load_from_env())
            
    except Exception as e:
        st.error(f"설정 로드 실패: {str(e)}")
        # 기본값으로 폴백
        config = get_default_config()
    
    return config

def load_from_secrets_manager():
    """AWS Secrets Manager에서 설정 로드"""
    secrets_client = boto3.client('secretsmanager')
    config = {}
    
    try:
        # Notion 토큰 로드
        notion_secret_arn = os.getenv('NOTION_TOKEN_SECRET_ARN')
        if notion_secret_arn:
            response = secrets_client.get_secret_value(SecretId=notion_secret_arn)
            notion_data = json.loads(response['SecretString'])
            config['notion_token'] = notion_data.get('token')
        
        # 앱 설정 로드
        app_config_secret_arn = os.getenv('APP_CONFIG_SECRET_ARN')
        if app_config_secret_arn:
            response = secrets_client.get_secret_value(SecretId=app_config_secret_arn)
            app_data = json.loads(response['SecretString'])
            config.update(app_data)
            
    except ClientError as e:
        st.error(f"Secrets Manager 접근 실패: {str(e)}")
        raise
    
    return config

def load_from_env():
    """환경 변수에서 설정 로드"""
    return {
        'notion_token': os.getenv('NOTION_TOKEN'),
        'bedrock_model_id': os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20241022-v2:0'),
        'aws_region': os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
        'max_tokens': int(os.getenv('MAX_TOKENS', '4000')),
        'temperature': float(os.getenv('TEMPERATURE', '0.1'))
    }

def get_default_config():
    """기본 설정값"""
    return {
        'bedrock_model_id': 'anthropic.claude-3-5-sonnet-20241022-v2:0',
        'aws_region': 'us-east-1',
        'max_tokens': 4000,
        'temperature': 0.1,
        'notion_token': None  # 반드시 설정되어야 함
    }

def validate_config(config):
    """설정 유효성 검사"""
    required_keys = ['bedrock_model_id', 'aws_region']
    
    for key in required_keys:
        if not config.get(key):
            raise ValueError(f"필수 설정 '{key}'가 누락되었습니다.")
    
    # Notion 토큰 확인 (선택사항 - MCP 서버가 처리할 수도 있음)
    if not config.get('notion_token'):
        st.warning("Notion 토큰이 설정되지 않았습니다. MCP 서버 설정을 확인해주세요.")
    
    return True

@st.cache_data(ttl=300)  # 5분 캐시
def get_cached_config():
    """캐시된 설정 반환"""
    return load_config()

def update_session_config(key, value):
    """세션 설정 업데이트"""
    if 'config' not in st.session_state:
        st.session_state.config = load_config()
    
    st.session_state.config[key] = value

def get_session_config(key, default=None):
    """세션에서 설정값 가져오기"""
    if 'config' not in st.session_state:
        st.session_state.config = load_config()
    
    return st.session_state.config.get(key, default)
