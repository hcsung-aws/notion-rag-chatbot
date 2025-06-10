# 배포 가이드

## 🚀 AWS 배포 단계별 가이드

### 1. 사전 준비

#### AWS 계정 설정
```bash
# AWS CLI 설치 및 설정
aws configure
# Access Key, Secret Key, Region 설정
```

#### Bedrock 모델 접근 권한 신청
1. AWS 콘솔 → Bedrock → Model access
2. Claude 3.5 Sonnet 모델 활성화 신청
3. 승인까지 2-3일 소요 가능

#### Notion Integration 생성
1. https://www.notion.so/my-integrations 접속
2. "New integration" 클릭
3. 워크스페이스 선택 및 권한 설정
4. Integration Token 복사 (secret_으로 시작)

### 2. 로컬 테스트

#### 환경 변수 설정
```bash
export NOTION_TOKEN="your_notion_token_here"
export AWS_DEFAULT_REGION="us-east-1"
```

#### 로컬 실행
```bash
cd streamlit
pip install -r requirements.txt
streamlit run app.py
```

### 3. CDK 배포

#### CDK 설치 및 초기화
```bash
npm install -g aws-cdk
cd cdk
pip install -r requirements.txt
cdk bootstrap
```

#### 스택 배포
```bash
# 모든 스택 배포
cdk deploy --all

# 개별 스택 배포
cdk deploy NotionChatbotVpcStack
cdk deploy NotionChatbotSecretsStack
cdk deploy NotionChatbotEcsStack
```

### 4. Secrets Manager 설정

#### Notion 토큰 저장
```bash
aws secretsmanager put-secret-value \
  --secret-id notion-chatbot/notion-token \
  --secret-string '{"token":"your_notion_token_here"}'
```

#### 앱 설정 확인
```bash
aws secretsmanager get-secret-value \
  --secret-id notion-chatbot/app-config
```

### 5. 배포 확인

#### 서비스 URL 확인
```bash
# CDK 출력에서 LoadBalancer DNS 확인
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[?contains(LoadBalancerName, `notion-chatbot`)].DNSName'
```

#### 헬스체크
```bash
curl http://your-load-balancer-dns/_stcore/health
```

## 🔧 문제 해결

### 일반적인 문제들

#### 1. Bedrock 접근 권한 오류
```
AccessDeniedException: User is not authorized to perform: bedrock:InvokeModel
```

**해결방법:**
- AWS 콘솔에서 Bedrock 모델 접근 권한 확인
- IAM 역할에 Bedrock 권한 추가 확인

#### 2. ECS 서비스 시작 실패
```
Task stopped with exit code 1
```

**해결방법:**
```bash
# CloudWatch 로그 확인
aws logs describe-log-groups --log-group-name-prefix "/ecs/notion-chatbot"
aws logs get-log-events --log-group-name "/ecs/notion-chatbot" --log-stream-name "latest"
```

#### 3. Notion API 연결 실패
```
Notion API 오류: 401 Unauthorized
```

**해결방법:**
- Notion Integration 토큰 확인
- 워크스페이스 권한 설정 확인
- Secrets Manager에 토큰이 올바르게 저장되었는지 확인

### 로그 확인 방법

#### ECS 로그
```bash
aws logs tail /ecs/notion-chatbot --follow
```

#### CloudWatch 메트릭
```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=notion-chatbot-service \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-01T23:59:59Z \
  --period 300 \
  --statistics Average
```

## 💰 비용 최적화

### 권장 설정

#### ECS Fargate
- **CPU**: 512 (0.5 vCPU)
- **Memory**: 1024 MB
- **Desired Count**: 1
- **Auto Scaling**: 1-3 인스턴스

#### 예상 월 비용
```
ECS Fargate (0.5 vCPU, 1GB): ~$25
Application Load Balancer: ~$20
CloudWatch Logs: ~$5
Bedrock (Claude 3.5 Sonnet): $30-100 (사용량에 따라)
기타 AWS 서비스: ~$10

총 예상 비용: $90-160/월
```

### 비용 절약 팁

1. **Fargate Spot 사용**
```python
# ECS 스택에서 Spot 인스턴스 사용
capacity_providers=[
    ecs.CapacityProvider.FARGATE_SPOT
]
```

2. **CloudWatch 로그 보존 기간 단축**
```python
retention=logs.RetentionDays.ONE_WEEK
```

3. **Auto Scaling 최적화**
```python
min_capacity=0,  # 사용하지 않을 때 0으로 스케일 다운
max_capacity=2
```

## 🔄 업데이트 및 유지보수

### 애플리케이션 업데이트
```bash
# 새 이미지 빌드 및 배포
cd streamlit
docker build -t notion-chatbot:latest .

# ECS 서비스 업데이트
cdk deploy NotionChatbotEcsStack
```

### 모니터링 설정
```bash
# CloudWatch 알람 생성
aws cloudwatch put-metric-alarm \
  --alarm-name "NotionChatbot-HighCPU" \
  --alarm-description "High CPU utilization" \
  --metric-name CPUUtilization \
  --namespace AWS/ECS \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2
```

### 백업 및 복구
```bash
# Secrets Manager 백업
aws secretsmanager describe-secret --secret-id notion-chatbot/notion-token
aws secretsmanager describe-secret --secret-id notion-chatbot/app-config

# 설정 내보내기
cdk synth > backup/cloudformation-template.yaml
```

## 🚨 보안 고려사항

### 네트워크 보안
- VPC 내 프라이빗 서브넷 사용
- Security Group으로 필요한 포트만 개방
- ALB를 통한 HTTPS 트래픽만 허용

### 데이터 보안
- Secrets Manager를 통한 민감 정보 관리
- ECS Task Role을 통한 최소 권한 원칙
- CloudTrail을 통한 API 호출 로깅

### 접근 제어
```python
# ALB에 인증 추가 (선택사항)
listener.add_action(
    "AuthAction",
    action=elbv2.ListenerAction.authenticate_cognito(
        user_pool=user_pool,
        user_pool_client=user_pool_client,
        next=elbv2.ListenerAction.forward([target_group])
    )
)
```

이 가이드를 따라 단계별로 배포하시면 안정적인 Notion 챗봇 서비스를 운영할 수 있습니다.
