#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.vpc_stack import VpcStack
from stacks.secrets_stack import SecretsStack
from stacks.bedrock_stack import BedrockStack
from stacks.opensearch_stack import OpenSearchStack
from stacks.complete_knowledgebase_stack import CompleteKnowledgeBaseStack
from stacks.ecs_stack import EcsStack

app = cdk.App()

# 환경 설정
env = cdk.Environment(
    account=app.node.try_get_context("account") or "965037532757",
    region=app.node.try_get_context("region") or "ap-northeast-2"
)

# VPC 스택
vpc_stack = VpcStack(app, "NotionChatbotVpcStack", env=env)

# Secrets 스택
secrets_stack = SecretsStack(app, "NotionChatbotSecretsStack", env=env)

# Bedrock 스택 (S3 기반)
bedrock_stack = BedrockStack(
    app, 
    "NotionChatbotBedrockStack",
    secrets=secrets_stack.secrets,
    env=env
)

# OpenSearch 스택 (벡터 검색 기반) - 기존 유지
opensearch_stack = OpenSearchStack(
    app,
    "NotionChatbotOpenSearchStack",
    secrets=secrets_stack.secrets,
    data_bucket=bedrock_stack.data_bucket,
    env=env
)

# 완전한 KnowledgeBase 스택 (S3 + OpenSearch Serverless + KnowledgeBase)
complete_kb_stack = CompleteKnowledgeBaseStack(
    app,
    "NotionChatbotCompleteKBStack",
    data_bucket=bedrock_stack.data_bucket,
    env=env
)

# ECS 스택 (완전한 KnowledgeBase 사용)
ecs_stack = EcsStack(
    app, 
    "NotionChatbotEcsStack",
    vpc=vpc_stack.vpc,
    secrets=secrets_stack.secrets,
    knowledge_base_id="UXF2GSP5IT",  # 현재 사용 중인 KnowledgeBase ID
    data_bucket=bedrock_stack.data_bucket,
    opensearch_endpoint="https://yoo4ngz693ukb9yha288.ap-northeast-2.aoss.amazonaws.com",  # 현재 사용 중인 엔드포인트
    vector_lambda_arn=opensearch_stack.vector_lambda.function_arn,
    env=env
)

app.synth()
