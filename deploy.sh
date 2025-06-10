#!/bin/bash

# Notion MCP 챗봇 배포 스크립트

set -e

echo "🚀 Notion MCP 챗봇 배포를 시작합니다..."

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 함수 정의
print_step() {
    echo -e "${BLUE}📋 $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 사전 요구사항 확인
print_step "사전 요구사항을 확인합니다..."

# AWS CLI 확인
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI가 설치되지 않았습니다."
    exit 1
fi

# CDK 확인
if ! command -v cdk &> /dev/null; then
    print_error "AWS CDK가 설치되지 않았습니다. 'npm install -g aws-cdk'로 설치해주세요."
    exit 1
fi

# Docker 확인
if ! command -v docker &> /dev/null; then
    print_error "Docker가 설치되지 않았습니다."
    exit 1
fi

print_success "모든 사전 요구사항이 충족되었습니다."

# AWS 계정 정보 확인
print_step "AWS 계정 정보를 확인합니다..."
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
AWS_REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")

if [ -z "$AWS_ACCOUNT" ]; then
    print_error "AWS 계정 정보를 가져올 수 없습니다. 'aws configure'를 실행해주세요."
    exit 1
fi

print_success "AWS 계정: $AWS_ACCOUNT, 리전: $AWS_REGION"

# Notion 토큰 확인
if [ -z "$NOTION_TOKEN" ]; then
    print_warning "NOTION_TOKEN 환경 변수가 설정되지 않았습니다."
    read -p "Notion Integration Token을 입력하세요: " NOTION_TOKEN
    
    if [ -z "$NOTION_TOKEN" ]; then
        print_error "Notion 토큰이 필요합니다."
        exit 1
    fi
fi

# Bedrock 모델 접근 권한 확인
print_step "Bedrock 모델 접근 권한을 확인합니다..."
if aws bedrock list-foundation-models --region $AWS_REGION --query 'modelSummaries[?contains(modelId, `claude-3-5-sonnet`)]' --output text &> /dev/null; then
    print_success "Bedrock Claude 3.5 Sonnet 모델에 접근할 수 있습니다."
else
    print_warning "Bedrock 모델 접근 권한을 확인할 수 없습니다. AWS 콘솔에서 모델 접근을 활성화했는지 확인해주세요."
fi

# CDK Bootstrap 확인
print_step "CDK Bootstrap 상태를 확인합니다..."
if aws cloudformation describe-stacks --stack-name CDKToolkit --region $AWS_REGION &> /dev/null; then
    print_success "CDK Bootstrap이 이미 완료되었습니다."
else
    print_step "CDK Bootstrap을 실행합니다..."
    cd cdk
    cdk bootstrap
    cd ..
    print_success "CDK Bootstrap 완료"
fi

# Python 의존성 설치
print_step "Python 의존성을 설치합니다..."
cd cdk
pip install -r requirements.txt
cd ..

cd streamlit
pip install -r requirements.txt
cd ..

print_success "의존성 설치 완료"

# CDK 배포
print_step "CDK 스택을 배포합니다..."
cd cdk

# VPC 스택 배포
print_step "VPC 스택을 배포합니다..."
cdk deploy NotionChatbotVpcStack --require-approval never

# Secrets 스택 배포
print_step "Secrets 스택을 배포합니다..."
cdk deploy NotionChatbotSecretsStack --require-approval never

# Notion 토큰을 Secrets Manager에 저장
print_step "Notion 토큰을 Secrets Manager에 저장합니다..."
aws secretsmanager put-secret-value \
    --secret-id notion-chatbot/notion-token \
    --secret-string "{\"token\":\"$NOTION_TOKEN\"}" \
    --region $AWS_REGION

print_success "Notion 토큰 저장 완료"

# ECS 스택 배포
print_step "ECS 스택을 배포합니다..."
cdk deploy NotionChatbotEcsStack --require-approval never

cd ..

# 배포 결과 확인
print_step "배포 결과를 확인합니다..."

# Load Balancer DNS 가져오기
LB_DNS=$(aws elbv2 describe-load-balancers \
    --query 'LoadBalancers[?contains(LoadBalancerName, `NotionChatbot`)].DNSName' \
    --output text \
    --region $AWS_REGION)

if [ -n "$LB_DNS" ]; then
    print_success "배포가 완료되었습니다!"
    echo ""
    echo "🌐 서비스 URL: http://$LB_DNS"
    echo ""
    echo "📋 다음 단계:"
    echo "1. 위 URL로 접속하여 서비스를 확인하세요"
    echo "2. Notion Integration에 워크스페이스 페이지 접근 권한을 부여하세요"
    echo "3. 첫 질문을 해보세요!"
    echo ""
    echo "🔧 관리 명령어:"
    echo "- 로그 확인: aws logs tail /ecs/notion-chatbot --follow"
    echo "- 서비스 상태: aws ecs describe-services --cluster notion-chatbot-cluster --services notion-chatbot-service"
    echo "- 스택 삭제: cdk destroy --all"
else
    print_error "Load Balancer를 찾을 수 없습니다. 배포를 다시 확인해주세요."
    exit 1
fi

# 헬스체크
print_step "서비스 헬스체크를 수행합니다..."
echo "서비스가 시작될 때까지 잠시 기다립니다..."
sleep 30

for i in {1..10}; do
    if curl -s -o /dev/null -w "%{http_code}" "http://$LB_DNS/_stcore/health" | grep -q "200"; then
        print_success "서비스가 정상적으로 실행 중입니다!"
        break
    else
        echo "헬스체크 시도 $i/10..."
        sleep 10
    fi
    
    if [ $i -eq 10 ]; then
        print_warning "헬스체크에 실패했습니다. 서비스가 시작되는 데 시간이 더 걸릴 수 있습니다."
        echo "수동으로 확인해보세요: http://$LB_DNS"
    fi
done

print_success "🎉 배포가 성공적으로 완료되었습니다!"
