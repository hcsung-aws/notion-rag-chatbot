#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.vpc_stack import VpcStack
from stacks.secrets_stack import SecretsStack
from stacks.bedrock_stack import BedrockStack
from stacks.opensearch_stack import OpenSearchStack
from stacks.aurora_knowledgebase_stack import AuroraKnowledgeBaseStack
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

# OpenSearch 스택 (벡터 검색 기반)
opensearch_stack = OpenSearchStack(
    app,
    "NotionChatbotOpenSearchStack",
    secrets=secrets_stack.secrets,
    data_bucket=bedrock_stack.data_bucket,
    env=env
)

# Aurora KnowledgeBase 스택 (S3 + Aurora PostgreSQL)
aurora_kb_stack = AuroraKnowledgeBaseStack(
    app,
    "NotionChatbotAuroraKBStack",
    vpc=vpc_stack.vpc,
    data_bucket=bedrock_stack.data_bucket,
    env=env
)

# ECS 스택 (Aurora KnowledgeBase 사용)
ecs_stack = EcsStack(
    app, 
    "NotionChatbotEcsStack",
    vpc=vpc_stack.vpc,
    secrets=secrets_stack.secrets,
    knowledge_base_id=aurora_kb_stack.knowledge_base.ref,
    data_bucket=bedrock_stack.data_bucket,
    opensearch_endpoint=opensearch_stack.vector_collection.attr_collection_endpoint,
    vector_lambda_arn=opensearch_stack.vector_lambda.function_arn,
    env=env
)

app.synth()
