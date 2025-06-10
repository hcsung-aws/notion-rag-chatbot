import streamlit as st
from components.chat_interface import render_chat_controls

def render_sidebar():
    """사이드바 렌더링"""
    
    with st.sidebar:
        st.markdown("## ⚙️ 설정")
        
        # 모델 설정
        st.markdown("### 🤖 AI 모델 설정")
        
        # 온도 설정
        temperature = st.slider(
            "응답 창의성 (Temperature)",
            min_value=0.0,
            max_value=1.0,
            value=st.session_state.get('temperature', 0.1),
            step=0.1,
            help="낮을수록 일관된 답변, 높을수록 창의적인 답변"
        )
        st.session_state.temperature = temperature
        
        # 최대 토큰 수
        max_tokens = st.slider(
            "최대 응답 길이",
            min_value=500,
            max_value=4000,
            value=st.session_state.get('max_tokens', 2000),
            step=100,
            help="응답의 최대 길이를 제한합니다"
        )
        st.session_state.max_tokens = max_tokens
        
        st.markdown("---")
        
        # 검색 설정
        st.markdown("### 🔍 검색 설정")
        
        # 검색 결과 수
        max_results = st.slider(
            "검색 결과 수",
            min_value=1,
            max_value=10,
            value=st.session_state.get('max_results', 5),
            step=1,
            help="Notion에서 가져올 검색 결과의 최대 개수"
        )
        st.session_state.max_results = max_results
        
        # 검색 필터
        search_filter = st.selectbox(
            "검색 범위",
            options=["전체", "페이지만", "데이터베이스만"],
            index=0,
            help="검색할 Notion 콘텐츠의 범위를 선택하세요"
        )
        st.session_state.search_filter = search_filter
        
        st.markdown("---")
        
        # 채팅 제어
        st.markdown("### 💬 대화 관리")
        render_chat_controls()
        
        st.markdown("---")
        
        # 시스템 정보
        st.markdown("### ℹ️ 시스템 정보")
        
        # 연결 상태 확인
        if st.button("🔄 연결 상태 확인"):
            check_system_status()
        
        # 사용 통계
        if st.button("📈 사용 통계"):
            show_usage_statistics()
        
        st.markdown("---")
        
        # 도움말
        st.markdown("### ❓ 도움말")
        
        with st.expander("💡 사용 팁"):
            st.markdown("""
            **효과적인 질문 방법:**
            - 구체적이고 명확한 질문하기
            - 키워드를 포함하여 질문하기
            - 맥락 정보 제공하기
            
            **예시 질문:**
            - "프로젝트 A의 일정은 어떻게 되나요?"
            - "마케팅 전략에 대한 문서를 찾아주세요"
            - "회의록에서 결정사항을 알려주세요"
            """)
        
        with st.expander("🔧 문제 해결"):
            st.markdown("""
            **자주 발생하는 문제:**
            
            1. **답변이 나오지 않는 경우**
               - 질문을 다르게 표현해보세요
               - 키워드를 바꿔서 시도해보세요
            
            2. **느린 응답 속도**
               - 검색 결과 수를 줄여보세요
               - 잠시 후 다시 시도해보세요
            
            3. **부정확한 답변**
               - 더 구체적인 질문을 해보세요
               - 참고 문서를 직접 확인해보세요
            """)
        
        # 버전 정보
        st.markdown("---")
        st.markdown("""
        <div style="text-align: center; color: #666; font-size: 0.8em;">
            <p>Notion MCP Chatbot v1.0</p>
            <p>Powered by Claude 3.5 Sonnet</p>
        </div>
        """, unsafe_allow_html=True)

def check_system_status():
    """시스템 연결 상태 확인"""
    status_container = st.empty()
    
    with status_container.container():
        st.info("시스템 상태를 확인하고 있습니다...")
        
        # Bedrock 연결 확인
        try:
            from utils.bedrock_client import BedrockClient
            bedrock_client = BedrockClient()
            bedrock_status = "✅ 연결됨"
        except Exception as e:
            bedrock_status = f"❌ 연결 실패: {str(e)[:50]}..."
        
        # MCP 서버 연결 확인
        try:
            from utils.mcp_client import NotionMCPClient
            mcp_client = NotionMCPClient()
            mcp_status = "✅ 연결됨"
        except Exception as e:
            mcp_status = f"❌ 연결 실패: {str(e)[:50]}..."
        
        # 결과 표시
        st.success("시스템 상태 확인 완료!")
        st.markdown(f"""
        **🤖 Bedrock (Claude 3.5 Sonnet):** {bedrock_status}
        
        **🔗 Notion MCP Server:** {mcp_status}
        """)

def show_usage_statistics():
    """사용 통계 표시"""
    if "messages" not in st.session_state:
        st.info("사용 통계가 없습니다.")
        return
    
    messages = st.session_state.messages
    
    if not messages:
        st.info("사용 통계가 없습니다.")
        return
    
    # 기본 통계
    total_messages = len(messages)
    user_messages = len([msg for msg in messages if msg["role"] == "user"])
    ai_messages = len([msg for msg in messages if msg["role"] == "assistant"])
    
    # 소스가 있는 응답 수
    responses_with_sources = len([
        msg for msg in messages 
        if msg["role"] == "assistant" and msg.get("sources")
    ])
    
    st.markdown("### 📊 현재 세션 통계")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("총 메시지", total_messages)
        st.metric("사용자 질문", user_messages)
    
    with col2:
        st.metric("AI 응답", ai_messages)
        st.metric("소스 포함 응답", responses_with_sources)
    
    # 성공률 계산
    if ai_messages > 0:
        success_rate = (responses_with_sources / ai_messages) * 100
        st.metric("응답 성공률", f"{success_rate:.1f}%")
    
    # 최근 활동
    if messages:
        st.markdown("### 📝 최근 활동")
        recent_messages = messages[-3:]  # 최근 3개 메시지
        
        for msg in recent_messages:
            role_icon = "👤" if msg["role"] == "user" else "🤖"
            content_preview = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
            st.markdown(f"{role_icon} {content_preview}")

def export_settings():
    """설정 내보내기"""
    settings = {
        "temperature": st.session_state.get('temperature', 0.1),
        "max_tokens": st.session_state.get('max_tokens', 2000),
        "max_results": st.session_state.get('max_results', 5),
        "search_filter": st.session_state.get('search_filter', "전체")
    }
    
    import json
    settings_json = json.dumps(settings, indent=2, ensure_ascii=False)
    
    st.download_button(
        label="⚙️ 설정 내보내기",
        data=settings_json,
        file_name="chatbot_settings.json",
        mime="application/json"
    )
