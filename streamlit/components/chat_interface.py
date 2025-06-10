import streamlit as st
import asyncio
import time
from utils.mcp_client import NotionMCPClient
from utils.bedrock_client import BedrockClient

def render_chat_interface():
    """메인 채팅 인터페이스 렌더링"""
    
    # 채팅 히스토리 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # 채팅 컨테이너
    chat_container = st.container()
    
    with chat_container:
        # 이전 메시지들 표시
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                
                # 소스 문서가 있는 경우 표시
                if message.get("sources"):
                    render_sources(message["sources"])
    
    # 사용자 입력
    if prompt := st.chat_input("무엇이든 물어보세요! 예: '프로젝트 일정은 어떻게 되나요?'"):
        # 사용자 메시지 추가
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        # 사용자 메시지 표시
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # AI 응답 생성 및 표시
        with st.chat_message("assistant"):
            with st.spinner("답변을 생성하고 있습니다... 🤔"):
                try:
                    response = get_ai_response(prompt)
                    
                    if response:
                        st.markdown(response["answer"])
                        
                        # 소스 문서 표시
                        if response.get("sources"):
                            render_sources(response["sources"])
                        
                        # 응답을 히스토리에 추가
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": response["answer"],
                            "sources": response.get("sources", [])
                        })
                    else:
                        error_msg = "죄송합니다. 현재 답변을 생성할 수 없습니다. 잠시 후 다시 시도해주세요."
                        st.error(error_msg)
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": error_msg
                        })
                        
                except Exception as e:
                    error_msg = f"오류가 발생했습니다: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_msg
                    })

def get_ai_response(query: str) -> dict:
    """AI 응답 생성"""
    try:
        # MCP 클라이언트를 통한 Notion 검색
        mcp_client = NotionMCPClient()
        notion_results = asyncio.run(mcp_client.search_notion(query))
        
        if not notion_results:
            return {
                "answer": "죄송합니다. 관련된 정보를 찾을 수 없습니다. 다른 질문을 시도해보세요.",
                "sources": []
            }
        
        # 검색 결과를 컨텍스트로 구성
        context = format_notion_context(notion_results)
        
        # Bedrock을 통한 응답 생성
        bedrock_client = BedrockClient()
        ai_response = bedrock_client.generate_response(query, context)
        
        return {
            "answer": ai_response,
            "sources": notion_results
        }
        
    except Exception as e:
        st.error(f"AI 응답 생성 중 오류: {str(e)}")
        return None

def format_notion_context(notion_results: list) -> str:
    """Notion 검색 결과를 컨텍스트로 포맷팅"""
    if not notion_results:
        return "관련 정보를 찾을 수 없습니다."
    
    context_parts = []
    for i, result in enumerate(notion_results[:5], 1):  # 최대 5개 결과만 사용
        title = result.get('title', '제목 없음')
        content = result.get('content', result.get('excerpt', '내용 없음'))
        
        context_parts.append(f"""
문서 {i}: {title}
내용: {content[:500]}...
""")
    
    return "\n".join(context_parts)

def render_sources(sources: list):
    """소스 문서 표시"""
    if not sources:
        return
    
    st.markdown("**📚 참고 문서:**")
    
    for i, source in enumerate(sources[:3], 1):  # 최대 3개만 표시
        with st.expander(f"📄 {source.get('title', f'문서 {i}')}", expanded=False):
            
            # 문서 내용
            content = source.get('content', source.get('excerpt', '내용을 불러올 수 없습니다.'))
            st.markdown(f"**내용:** {content[:300]}...")
            
            # Notion 링크
            if source.get('url'):
                st.markdown(f"**🔗 링크:** [Notion에서 보기]({source['url']})")
            
            # 추가 메타데이터
            if source.get('last_edited_time'):
                st.markdown(f"**📅 마지막 수정:** {source['last_edited_time']}")
            
            if source.get('created_by'):
                st.markdown(f"**👤 작성자:** {source['created_by']}")

def clear_chat_history():
    """채팅 히스토리 초기화"""
    st.session_state.messages = []
    st.rerun()

# 채팅 히스토리 관리 버튼들
def render_chat_controls():
    """채팅 제어 버튼들"""
    col1, col2, col3 = st.columns([1, 1, 1])
    
    with col1:
        if st.button("🗑️ 대화 초기화"):
            clear_chat_history()
    
    with col2:
        if st.button("💾 대화 저장"):
            save_chat_history()
    
    with col3:
        if st.button("📊 통계 보기"):
            show_chat_statistics()

def save_chat_history():
    """채팅 히스토리 저장"""
    if st.session_state.messages:
        # 간단한 텍스트 파일로 저장
        chat_text = ""
        for msg in st.session_state.messages:
            role = "사용자" if msg["role"] == "user" else "AI"
            chat_text += f"{role}: {msg['content']}\n\n"
        
        st.download_button(
            label="💾 대화 내용 다운로드",
            data=chat_text,
            file_name=f"chat_history_{int(time.time())}.txt",
            mime="text/plain"
        )
    else:
        st.info("저장할 대화 내용이 없습니다.")

def show_chat_statistics():
    """채팅 통계 표시"""
    if st.session_state.messages:
        total_messages = len(st.session_state.messages)
        user_messages = len([msg for msg in st.session_state.messages if msg["role"] == "user"])
        ai_messages = len([msg for msg in st.session_state.messages if msg["role"] == "assistant"])
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("전체 메시지", total_messages)
        with col2:
            st.metric("사용자 질문", user_messages)
        with col3:
            st.metric("AI 응답", ai_messages)
    else:
        st.info("통계를 표시할 대화 내용이 없습니다.")
