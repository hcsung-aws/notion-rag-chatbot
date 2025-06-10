import streamlit as st
import asyncio
import json
from components.chat_interface import render_chat_interface
from components.sidebar import render_sidebar
from utils.config import load_config
from utils.mcp_client import NotionMCPClient
from utils.bedrock_client import BedrockClient

# 페이지 설정
st.set_page_config(
    page_title="무엇이든 물어보세요! 🤖",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 커스텀 CSS
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    
    .chat-container {
        max-height: 600px;
        overflow-y: auto;
        padding: 1rem;
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        background-color: #fafafa;
    }
    
    .source-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
        border-left: 4px solid #667eea;
    }
    
    .stButton > button {
        width: 100%;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1rem;
    }
</style>
""", unsafe_allow_html=True)

def main():
    # 헤더
    st.markdown("""
    <div class="main-header">
        <h1>🤖 무엇이든 물어보세요!</h1>
        <p>Notion 지식 기반에서 답변을 찾아드립니다</p>
    </div>
    """, unsafe_allow_html=True)

    # 설정 로드
    try:
        config = load_config()
        st.session_state.config = config
    except Exception as e:
        st.error(f"설정 로드 중 오류가 발생했습니다: {str(e)}")
        st.stop()

    # 사이드바 렌더링
    render_sidebar()

    # 메인 채팅 인터페이스
    render_chat_interface()

    # 푸터
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; padding: 1rem;">
        <p>💡 Notion 워크스페이스의 내용을 기반으로 답변합니다</p>
        <p>🔒 모든 데이터는 안전하게 처리됩니다</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
