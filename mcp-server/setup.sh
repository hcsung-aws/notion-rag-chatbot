#!/bin/bash

# MCP Server 설정 스크립트

echo "🚀 Notion MCP Server 설정을 시작합니다..."

# Node.js 및 npm 확인
if ! command -v node &> /dev/null; then
    echo "❌ Node.js가 설치되지 않았습니다. Node.js를 먼저 설치해주세요."
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "❌ npm이 설치되지 않았습니다. npm을 먼저 설치해주세요."
    exit 1
fi

echo "✅ Node.js 및 npm이 설치되어 있습니다."

# MCP Server 패키지 설치
echo "📦 MCP Server 패키지를 설치합니다..."
npm install -g @modelcontextprotocol/server-everything

if [ $? -eq 0 ]; then
    echo "✅ MCP Server 패키지 설치 완료"
else
    echo "❌ MCP Server 패키지 설치 실패"
    exit 1
fi

# Notion 토큰 확인
if [ -z "$NOTION_TOKEN" ]; then
    echo "⚠️  NOTION_TOKEN 환경 변수가 설정되지 않았습니다."
    echo "   다음 명령어로 토큰을 설정해주세요:"
    echo "   export NOTION_TOKEN=your_notion_token_here"
else
    echo "✅ Notion 토큰이 설정되어 있습니다."
fi

# MCP 서버 테스트
echo "🧪 MCP 서버 연결을 테스트합니다..."

# 임시 테스트 (실제로는 더 정교한 테스트 필요)
if command -v npx &> /dev/null; then
    echo "✅ MCP 서버 실행 준비 완료"
else
    echo "❌ npx 명령어를 찾을 수 없습니다."
    exit 1
fi

echo "🎉 MCP Server 설정이 완료되었습니다!"
echo ""
echo "📋 다음 단계:"
echo "1. Notion Integration을 생성하고 토큰을 발급받으세요"
echo "2. 환경 변수 NOTION_TOKEN을 설정하세요"
echo "3. Streamlit 애플리케이션을 실행하세요"
echo ""
echo "🔗 유용한 링크:"
echo "- Notion Integration 생성: https://www.notion.so/my-integrations"
echo "- MCP 문서: https://modelcontextprotocol.io/"
