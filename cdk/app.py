#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.vpc_stack import VpcStack
from stacks.secrets_stack import SecretsStack
from stacks.bedrock_stack import BedrockStack
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

# Bedrock 스택 (새로 추가)
bedrock_stack = BedrockStack(
    app, 
    "NotionChatbotBedrockStack",
    secrets=secrets_stack.secrets,
    env=env
)

# ECS 스택
ecs_stack = EcsStack(
    app, 
    "NotionChatbotEcsStack",
    vpc=vpc_stack.vpc,
    secrets=secrets_stack.secrets,
    knowledge_base_id=bedrock_stack.knowledge_base_id,
    data_bucket=bedrock_stack.data_bucket,
    env=env
)

app.synth()
