# Contributing to Notion RAG Chatbot

## 🎯 기여 방법

이 프로젝트에 기여해주셔서 감사합니다! 다음 가이드라인을 따라주세요.

## 🐛 버그 리포트

버그를 발견하셨나요? 다음 정보를 포함해서 Issue를 생성해주세요:

- 버그 설명
- 재현 단계
- 예상 동작
- 실제 동작
- 환경 정보 (OS, AWS 리전, 브라우저 등)
- 스크린샷 (가능한 경우)

## 💡 기능 제안

새로운 기능을 제안하고 싶으시다면:

- 기능 설명
- 사용 사례
- 구현 방안 (선택사항)
- 관련 이슈나 PR 링크 (있는 경우)

## 🔧 개발 환경 설정

### 로컬 개발
\`\`\`bash
# 1. 저장소 클론
git clone https://github.com/yourusername/notion-rag-chatbot.git
cd notion-rag-chatbot

# 2. Python 가상환경 생성
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 의존성 설치
cd streamlit
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일을 편집하여 필요한 값들 설정

# 5. 로컬 실행
streamlit run app.py
\`\`\`

### CDK 개발
\`\`\`bash
cd cdk
pip install -r requirements.txt
cdk synth  # CloudFormation 템플릿 생성
\`\`\`

## 📝 코딩 스타일

### Python
- PEP 8 준수
- Type hints 사용
- Docstring 작성 (Google 스타일)
- Black 포매터 사용

### TypeScript/JavaScript
- Prettier 사용
- ESLint 규칙 준수

### 예시
\`\`\`python
def search_documents(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    S3에서 문서를 검색합니다.
    
    Args:
        query: 검색 쿼리
        limit: 최대 결과 수
        
    Returns:
        검색된 문서 리스트
    """
    pass
\`\`\`

## 🧪 테스트

### 단위 테스트
\`\`\`bash
# 테스트 실행
pytest tests/

# 커버리지 확인
pytest --cov=src tests/
\`\`\`

### 통합 테스트
\`\`\`bash
# CDK 테스트
cd cdk
npm test
\`\`\`

## 📋 Pull Request 가이드라인

### PR 체크리스트
- [ ] 코드가 스타일 가이드를 준수하는가?
- [ ] 테스트가 통과하는가?
- [ ] 문서가 업데이트되었는가?
- [ ] 변경사항이 CHANGELOG.md에 기록되었는가?

### PR 템플릿
\`\`\`markdown
## 변경사항
- 

## 테스트
- [ ] 로컬 테스트 완료
- [ ] 통합 테스트 완료

## 스크린샷 (UI 변경 시)

## 관련 이슈
Closes #
\`\`\`

## 🏷️ 커밋 메시지

Conventional Commits 형식을 사용합니다:

\`\`\`
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
\`\`\`

### 타입
- `feat`: 새로운 기능
- `fix`: 버그 수정
- `docs`: 문서 변경
- `style`: 코드 스타일 변경
- `refactor`: 리팩토링
- `test`: 테스트 추가/수정
- `chore`: 빌드 프로세스나 도구 변경

### 예시
\`\`\`
feat(chat): add message history export feature

Add ability to export chat history as JSON or markdown file.
Users can now download their conversation history from the sidebar.

Closes #123
\`\`\`

## 🔍 코드 리뷰

### 리뷰어 가이드라인
- 코드 품질과 가독성 확인
- 보안 이슈 검토
- 성능 영향 평가
- 문서화 완성도 확인

### 리뷰이 가이드라인
- 피드백에 대해 열린 마음으로 수용
- 변경사항에 대한 명확한 설명 제공
- 테스트 결과 공유

## 🚀 릴리스 프로세스

### 버전 관리
- Semantic Versioning (SemVer) 사용
- MAJOR.MINOR.PATCH 형식

### 릴리스 단계
1. 기능 개발 완료
2. 테스트 통과 확인
3. 문서 업데이트
4. CHANGELOG.md 업데이트
5. 버전 태그 생성
6. GitHub Release 생성

## 📞 도움이 필요하신가요?

- GitHub Discussions에서 질문
- Issue에서 도움 요청
- 메인테이너에게 직접 연락

## 🙏 기여자 인정

모든 기여자는 README.md의 Contributors 섹션에 추가됩니다.

감사합니다! 🎉
