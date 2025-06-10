# 아키텍처 가이드

## 📐 시스템 아키텍처 개요

이 문서는 Notion RAG Chatbot의 AWS 아키텍처에 대한 상세한 설명을 제공합니다.

## 🏗️ 아키텍처 다이어그램

![Architecture Diagram](../architecture-diagram.drawio)

> **참고**: 위 다이어그램은 draw.io에서 열어볼 수 있습니다. `architecture-diagram.drawio` 파일을 draw.io에서 직접 열거나, [app.diagrams.net](https://app.diagrams.net)에서 Import하여 확인하세요.

## 🔧 주요 컴포넌트

### 1. 프론트엔드 계층
- **Application Load Balancer (ALB)**: HTTPS 트래픽 분산 및 SSL 종료
- **ECS Fargate**: 컨테이너화된 Streamlit 애플리케이션 실행

### 2. 컴퓨팅 계층
- **ECS Cluster**: 컨테이너 오케스트레이션
- **Fargate Tasks**: 서버리스 컨테이너 실행 환경
- **Lambda Function**: Notion 데이터 동기화 처리

### 3. 데이터 계층
- **Amazon S3**: Notion 페이지 데이터 저장 (JSON 형태)
- **Amazon Bedrock**: Claude 3.5 Sonnet AI 모델 서비스

### 4. 자동화 계층
- **EventBridge**: 스케줄링 및 이벤트 관리
- **CloudWatch**: 로깅 및 모니터링

### 5. 보안 계층
- **Secrets Manager**: Notion API 토큰 안전 저장
- **IAM Roles**: 최소 권한 원칙 기반 접근 제어
- **VPC**: 네트워크 격리 및 보안

## 🔄 데이터 흐름

### 사용자 질문 처리 흐름
```
1. 사용자 → ALB → ECS Fargate (Streamlit)
2. Streamlit → S3 (문서 검색)
3. Streamlit → Bedrock (AI 답변 생성)
4. 답변 + 참고 문서 → 사용자
```

### 데이터 동기화 흐름
```
1. EventBridge → Lambda (1시간마다)
2. Lambda → Notion API (페이지 추출)
3. Lambda → S3 (JSON 저장)
```

## 🏛️ AWS 서비스별 역할

| 서비스 | 역할 | 설정 |
|--------|------|------|
| **ECS Fargate** | Streamlit 앱 실행 | 1 vCPU, 2GB RAM |
| **Application Load Balancer** | 트래픽 분산 | HTTP/HTTPS 리스너 |
| **Lambda** | 데이터 동기화 | Python 3.11, 15분 타임아웃 |
| **S3** | 문서 저장소 | 버전 관리, 암호화 |
| **EventBridge** | 스케줄러 | 1시간 간격 실행 |
| **Secrets Manager** | 토큰 관리 | 자동 로테이션 지원 |
| **CloudWatch** | 모니터링 | 로그 보존 1주 |
| **Bedrock** | AI 서비스 | Claude 3.5 Sonnet |

## 🔒 보안 아키텍처

### IAM 권한 매트릭스
| 서비스 | S3 | Lambda | Bedrock | Secrets Manager |
|--------|----|---------|---------|--------------------|
| **ECS Task** | Read | Invoke | InvokeModel | GetSecretValue |
| **Lambda** | Write | - | - | GetSecretValue |

### 네트워크 보안
- **VPC**: 기본 VPC 사용 (비용 최적화)
- **Security Groups**: 최소 필요 포트만 개방
- **HTTPS**: ALB에서 SSL 종료

## 📊 성능 및 확장성

### Auto Scaling 설정
```yaml
Min Capacity: 1
Max Capacity: 3
Target CPU: 70%
Scale Out Cooldown: 2분
Scale In Cooldown: 5분
```

### 성능 메트릭
- **응답 시간**: 2-10초
- **동시 사용자**: ~100명
- **처리량**: 초당 10-20 요청

## 💰 비용 최적화

### 주요 비용 요소
1. **ECS Fargate**: 실행 시간 기반
2. **Bedrock**: 토큰 사용량 기반
3. **Lambda**: 실행 횟수 및 시간
4. **S3**: 저장 용량 및 요청 수

### 최적화 전략
- Fargate Spot 인스턴스 사용 고려
- S3 Intelligent Tiering 적용
- CloudWatch 로그 보존 기간 조정
- 불필요한 Bedrock 호출 최소화

## 🔧 배포 전략

### Blue-Green 배포
```bash
# 새 버전 배포
cdk deploy --all

# 헬스체크 확인
aws elbv2 describe-target-health

# 트래픽 전환 (자동)
```

### 롤백 전략
```bash
# 이전 태스크 정의로 롤백
aws ecs update-service --service notion-chatbot-service \
  --task-definition previous-task-definition-arn
```

## 📈 모니터링 및 알람

### CloudWatch 메트릭
- ECS 서비스 상태
- Lambda 실행 성공률
- ALB 응답 시간
- S3 요청 수

### 알람 설정
```yaml
High CPU Usage: > 80%
High Memory Usage: > 85%
Lambda Errors: > 5%
ALB 5xx Errors: > 1%
```

## 🔍 트러블슈팅

### 일반적인 문제들

1. **ECS 태스크 시작 실패**
   - IAM 권한 확인
   - 컨테이너 이미지 상태 확인
   - 리소스 할당량 확인

2. **Lambda 타임아웃**
   - 메모리 할당량 증가
   - 타임아웃 시간 조정
   - 코드 최적화

3. **S3 접근 오류**
   - IAM 정책 확인
   - 버킷 정책 검토
   - 리전 설정 확인

### 로그 확인 방법
```bash
# ECS 로그
aws logs tail /ecs/notion-chatbot --follow

# Lambda 로그
aws logs tail /aws/lambda/notion-sync --follow
```

## 🚀 향후 개선 방안

### 단기 개선사항
- CloudFront CDN 추가
- RDS 캐시 레이어 도입
- 멀티 리전 배포

### 장기 개선사항
- Kubernetes 마이그레이션
- 마이크로서비스 아키텍처
- 실시간 스트리밍 응답

## 📚 참고 자료

- [AWS ECS Best Practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/)
- [AWS Lambda Best Practices](https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/)
- [AWS CDK Developer Guide](https://docs.aws.amazon.com/cdk/)
