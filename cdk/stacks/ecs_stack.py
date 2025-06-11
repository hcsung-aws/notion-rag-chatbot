from aws_cdk import (
    Stack,
    Duration,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_logs as logs,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct

class EcsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc, secrets, knowledge_base_id, data_bucket, opensearch_endpoint, vector_lambda_arn, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ECS Cluster
        cluster = ecs.Cluster(
            self, "NotionChatbotCluster",
            vpc=vpc,
            cluster_name="notion-chatbot-cluster",
            enable_fargate_capacity_providers=True
        )

        # Task Role - Bedrock 및 Secrets Manager 접근 권한
        task_role = iam.Role(
            self, "NotionChatbotTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonECSTaskExecutionRolePolicy")
            ]
        )

        # S3 접근 권한 추가
        data_bucket.grant_read(task_role)
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:ListBucket"
                ],
                resources=[data_bucket.bucket_arn]
            )
        )

        # OpenSearch 접근 권한 추가
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "aoss:APIAccessAll"
                ],
                resources=["*"]
            )
        )

        # Bedrock Titan Embedding 모델 접근 권한 추가
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel"
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                ]
            )
        )

        # Lambda 호출 권한 추가 (기존 + 벡터 Lambda)
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "lambda:InvokeFunction"
                ],
                resources=[
                    f"arn:aws:lambda:{self.region}:{self.account}:function:NotionChatbotBedrockStack-NotionSyncFunction*",
                    vector_lambda_arn
                ]
            )
        )

        # Bedrock 접근 권한 추가
        task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                    f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/*"
                ]
            )
        )

        # Secrets Manager 접근 권한 추가
        for secret in secrets.values():
            secret.grant_read(task_role)

        # Task Definition
        task_definition = ecs.FargateTaskDefinition(
            self, "NotionChatbotTaskDef",
            memory_limit_mib=1024,
            cpu=512,
            task_role=task_role
        )

        # Container Definition
        container = task_definition.add_container(
            "NotionChatbotContainer",
            image=ecs.ContainerImage.from_registry("python:3.11-slim"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="notion-chatbot",
                log_group=logs.LogGroup(
                    self, "NotionChatbotLogGroup",
                    log_group_name="/ecs/notion-chatbot",
                    retention=logs.RetentionDays.ONE_WEEK
                )
            ),
            environment={
                "AWS_DEFAULT_REGION": self.region,
                "STREAMLIT_SERVER_PORT": "8501",
                "STREAMLIT_SERVER_ADDRESS": "0.0.0.0",
                "NOTION_TOKEN": "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",
                "KNOWLEDGE_BASE_ID": knowledge_base_id,
                "OPENSEARCH_ENDPOINT": opensearch_endpoint,
                "VECTOR_LAMBDA_ARN": vector_lambda_arn
            },
            secrets={
                "NOTION_TOKEN_SECRET_ARN": ecs.Secret.from_secrets_manager(secrets["notion_token"]),
                "APP_CONFIG_SECRET_ARN": ecs.Secret.from_secrets_manager(secrets["app_config"])
            },
            command=[
                "bash", "-c", 
                f"""
                pip install streamlit boto3 requests notion-client opensearch-py &&
                mkdir -p /app && cd /app &&
                cat > app.py << 'STREAMLIT_EOF'
{open('/home/hcsung/work/notion-rag-chatbot/streamlit/app_knowledgebase.py').read()}
STREAMLIT_EOF
                streamlit run app.py --server.port=8501 --server.address=0.0.0.0
                """
            ]
        )

        # Port Mapping
        container.add_port_mappings(
            ecs.PortMapping(
                container_port=8501,
                protocol=ecs.Protocol.TCP
            )
        )

        # Application Load Balanced Fargate Service
        self.fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "NotionChatbotService",
            cluster=cluster,
            task_definition=task_definition,
            public_load_balancer=True,
            listener_port=80,
            desired_count=1,  # 비용 절약을 위해 1개 인스턴스
            platform_version=ecs.FargatePlatformVersion.LATEST,
            assign_public_ip=True,
            service_name="notion-chatbot-service"
        )

        # Health Check 설정
        self.fargate_service.target_group.configure_health_check(
            path="/",
            healthy_http_codes="200",
            timeout=Duration.seconds(10),
            interval=Duration.seconds(30),
            healthy_threshold_count=2,
            unhealthy_threshold_count=5
        )

        # Auto Scaling 설정 (선택사항)
        scaling = self.fargate_service.service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=3
        )

        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.minutes(5),
            scale_out_cooldown=Duration.minutes(2)
        )

        # Outputs
        CfnOutput(
            self, "LoadBalancerDNS",
            value=self.fargate_service.load_balancer.load_balancer_dns_name,
            description="Load Balancer DNS Name"
        )

        CfnOutput(
            self, "ServiceURL",
            value=f"http://{self.fargate_service.load_balancer.load_balancer_dns_name}",
            description="Notion Chatbot Service URL"
        )
