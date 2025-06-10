import boto3
import json
import streamlit as st
from botocore.exceptions import ClientError
from utils.config import get_session_config

class BedrockClient:
    def __init__(self):
        """Bedrock 클라이언트 초기화"""
        self.region = get_session_config('aws_region', 'us-east-1')
        self.model_id = get_session_config('bedrock_model_id', 'anthropic.claude-3-5-sonnet-20241022-v2:0')
        
        try:
            self.bedrock_runtime = boto3.client(
                'bedrock-runtime',
                region_name=self.region
            )
        except Exception as e:
            st.error(f"Bedrock 클라이언트 초기화 실패: {str(e)}")
            raise

    def generate_response(self, query: str, context: str = "") -> str:
        """Claude 3.5 Sonnet으로 응답 생성"""
        try:
            # 프롬프트 구성
            prompt = self._build_prompt(query, context)
            
            # 모델 파라미터
            temperature = st.session_state.get('temperature', 0.1)
            max_tokens = st.session_state.get('max_tokens', 2000)
            
            # Bedrock 호출
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": 0.9,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
            
            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body)
            )
            
            # 응답 파싱
            response_body = json.loads(response['body'].read())
            
            if 'content' in response_body and response_body['content']:
                return response_body['content'][0]['text']
            else:
                return "죄송합니다. 응답을 생성할 수 없습니다."
                
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDeniedException':
                st.error("Bedrock 모델에 대한 접근 권한이 없습니다. AWS 콘솔에서 모델 접근을 활성화해주세요.")
            elif error_code == 'ThrottlingException':
                st.error("요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
            else:
                st.error(f"Bedrock API 오류: {str(e)}")
            return "오류로 인해 응답을 생성할 수 없습니다."
            
        except Exception as e:
            st.error(f"응답 생성 중 오류: {str(e)}")
            return "오류로 인해 응답을 생성할 수 없습니다."

    def _build_prompt(self, query: str, context: str = "") -> str:
        """프롬프트 구성"""
        if context:
            prompt = f"""당신은 Notion 워크스페이스의 내용을 기반으로 질문에 답하는 AI 어시스턴트입니다.

사용자 질문: {query}

관련 Notion 문서 내용:
{context}

위의 Notion 문서 내용을 바탕으로 사용자의 질문에 정확하고 도움이 되는 답변을 제공해주세요. 
답변할 때는 다음 사항을 지켜주세요:

1. 제공된 문서 내용을 기반으로만 답변하세요
2. 확실하지 않은 정보는 추측하지 마세요
3. 한국어로 자연스럽고 친근하게 답변하세요
4. 가능하면 구체적인 예시나 세부사항을 포함하세요
5. 문서에서 직접 인용할 때는 따옴표를 사용하세요

답변:"""
        else:
            prompt = f"""당신은 도움이 되는 AI 어시스턴트입니다. 사용자의 질문에 정확하고 친근하게 답변해주세요.

사용자 질문: {query}

답변:"""
        
        return prompt

    def test_connection(self) -> bool:
        """Bedrock 연결 테스트"""
        try:
            # 간단한 테스트 요청
            test_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 10,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "user",
                        "content": "Hello"
                    }
                ]
            }
            
            response = self.bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps(test_body)
            )
            
            return True
            
        except Exception as e:
            st.error(f"Bedrock 연결 테스트 실패: {str(e)}")
            return False

    def get_model_info(self) -> dict:
        """모델 정보 반환"""
        return {
            "model_id": self.model_id,
            "region": self.region,
            "provider": "Anthropic",
            "model_name": "Claude 3.5 Sonnet"
        }

    def estimate_tokens(self, text: str) -> int:
        """토큰 수 추정 (대략적)"""
        # 영어: 1 토큰 ≈ 4 문자
        # 한국어: 1 토큰 ≈ 2-3 문자
        # 보수적으로 2문자당 1토큰으로 계산
        return len(text) // 2

    def check_token_limit(self, prompt: str) -> bool:
        """토큰 제한 확인"""
        estimated_tokens = self.estimate_tokens(prompt)
        max_input_tokens = 200000  # Claude 3.5 Sonnet의 컨텍스트 윈도우
        
        if estimated_tokens > max_input_tokens:
            st.warning(f"입력 텍스트가 너무 깁니다. (예상 토큰: {estimated_tokens:,})")
            return False
        
        return True
