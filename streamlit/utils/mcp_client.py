import asyncio
import json
import subprocess
import streamlit as st
from typing import List, Dict, Any
import tempfile
import os

class NotionMCPClient:
    def __init__(self):
        """Notion MCP 클라이언트 초기화"""
        self.server_config = self._get_server_config()
        
    def _get_server_config(self) -> dict:
        """MCP 서버 설정 반환"""
        return {
            "command": "npx",
            "args": [
                "@modelcontextprotocol/server-everything",
                "--notion-token", 
                self._get_notion_token()
            ]
        }
    
    def _get_notion_token(self) -> str:
        """Notion 토큰 가져오기"""
        from utils.config import get_session_config
        
        token = get_session_config('notion_token')
        if not token:
            # 환경 변수에서 시도
            token = os.getenv('NOTION_TOKEN')
        
        if not token:
            st.error("Notion 토큰이 설정되지 않았습니다.")
            raise ValueError("Notion token not configured")
        
        return token

    async def search_notion(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Notion에서 검색 수행"""
        try:
            # 임시 방법: Notion API를 직접 사용
            # 실제 환경에서는 MCP 서버를 통해 처리
            return await self._direct_notion_search(query, max_results)
            
        except Exception as e:
            st.error(f"Notion 검색 중 오류: {str(e)}")
            return []

    async def _direct_notion_search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """직접 Notion API 호출 (MCP 서버 대체)"""
        try:
            import requests
            
            token = self._get_notion_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }
            
            # Notion Search API 호출
            search_url = "https://api.notion.com/v1/search"
            search_payload = {
                "query": query,
                "page_size": max_results,
                "filter": {
                    "property": "object",
                    "value": "page"
                }
            }
            
            response = requests.post(search_url, headers=headers, json=search_payload)
            
            if response.status_code != 200:
                st.error(f"Notion API 오류: {response.status_code}")
                return []
            
            data = response.json()
            results = []
            
            for page in data.get('results', []):
                # 페이지 내용 가져오기
                page_content = await self._get_page_content(page['id'], headers)
                
                result = {
                    'id': page['id'],
                    'title': self._extract_title(page),
                    'url': page['url'],
                    'content': page_content,
                    'last_edited_time': page.get('last_edited_time'),
                    'created_time': page.get('created_time'),
                    'created_by': page.get('created_by', {}).get('id', 'Unknown')
                }
                results.append(result)
            
            return results
            
        except Exception as e:
            st.error(f"Notion 직접 검색 중 오류: {str(e)}")
            return []

    async def _get_page_content(self, page_id: str, headers: dict) -> str:
        """페이지 내용 가져오기"""
        try:
            import requests
            
            blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
            response = requests.get(blocks_url, headers=headers)
            
            if response.status_code != 200:
                return "내용을 가져올 수 없습니다."
            
            data = response.json()
            content_parts = []
            
            for block in data.get('results', []):
                block_text = self._extract_block_text(block)
                if block_text:
                    content_parts.append(block_text)
            
            return '\n'.join(content_parts)
            
        except Exception as e:
            return f"내용 로드 오류: {str(e)}"

    def _extract_title(self, page: dict) -> str:
        """페이지 제목 추출"""
        try:
            properties = page.get('properties', {})
            
            # 제목 속성 찾기
            for prop_name, prop_data in properties.items():
                if prop_data.get('type') == 'title':
                    title_array = prop_data.get('title', [])
                    if title_array:
                        return title_array[0].get('text', {}).get('content', '제목 없음')
            
            return '제목 없음'
            
        except Exception:
            return '제목 없음'

    def _extract_block_text(self, block: dict) -> str:
        """블록에서 텍스트 추출"""
        try:
            block_type = block.get('type')
            
            if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
                rich_text = block.get(block_type, {}).get('rich_text', [])
                return ''.join([text.get('text', {}).get('content', '') for text in rich_text])
            
            elif block_type == 'bulleted_list_item':
                rich_text = block.get('bulleted_list_item', {}).get('rich_text', [])
                text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
                return f"• {text}"
            
            elif block_type == 'numbered_list_item':
                rich_text = block.get('numbered_list_item', {}).get('rich_text', [])
                text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
                return f"1. {text}"
            
            elif block_type == 'to_do':
                rich_text = block.get('to_do', {}).get('rich_text', [])
                text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
                checked = block.get('to_do', {}).get('checked', False)
                checkbox = "☑" if checked else "☐"
                return f"{checkbox} {text}"
            
            return ""
            
        except Exception:
            return ""

    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            # 간단한 검색으로 연결 테스트
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(self.search_notion("test", 1))
            loop.close()
            
            return True
            
        except Exception as e:
            st.error(f"Notion MCP 연결 테스트 실패: {str(e)}")
            return False

    def get_workspace_info(self) -> dict:
        """워크스페이스 정보 가져오기"""
        try:
            import requests
            
            token = self._get_notion_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }
            
            # 사용자 정보 가져오기
            user_url = "https://api.notion.com/v1/users/me"
            response = requests.get(user_url, headers=headers)
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    "user_name": user_data.get('name', 'Unknown'),
                    "user_id": user_data.get('id'),
                    "avatar_url": user_data.get('avatar_url')
                }
            
            return {"error": "워크스페이스 정보를 가져올 수 없습니다."}
            
        except Exception as e:
            return {"error": f"오류: {str(e)}"}

# 유틸리티 함수들
def format_search_results(results: List[Dict[str, Any]]) -> str:
    """검색 결과를 포맷팅"""
    if not results:
        return "검색 결과가 없습니다."
    
    formatted_parts = []
    for i, result in enumerate(results, 1):
        title = result.get('title', '제목 없음')
        content = result.get('content', '내용 없음')
        
        # 내용이 너무 길면 자르기
        if len(content) > 300:
            content = content[:300] + "..."
        
        formatted_parts.append(f"""
**{i}. {title}**
{content}
""")
    
    return "\n".join(formatted_parts)

def extract_keywords(query: str) -> List[str]:
    """질문에서 키워드 추출"""
    # 간단한 키워드 추출 (실제로는 더 정교한 NLP 처리 필요)
    import re
    
    # 한글, 영문, 숫자만 추출
    words = re.findall(r'[가-힣a-zA-Z0-9]+', query)
    
    # 불용어 제거 (간단한 버전)
    stop_words = {'은', '는', '이', '가', '을', '를', '에', '의', '와', '과', '로', '으로', 
                  'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
    
    keywords = [word for word in words if word.lower() not in stop_words and len(word) > 1]
    
    return keywords[:5]  # 최대 5개 키워드만 반환
