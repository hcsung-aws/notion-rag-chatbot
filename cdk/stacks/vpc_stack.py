from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput
)
from constructs import Construct

class VpcStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 기본 VPC 사용
        self.vpc = ec2.Vpc.from_lookup(
            self, "DefaultVpc",
            is_default=True
        )

        # Security Group for ECS
        self.ecs_security_group = ec2.SecurityGroup(
            self, "EcsSecurityGroup",
            vpc=self.vpc,
            description="Security group for Notion Chatbot ECS service",
            allow_all_outbound=True
        )

        # HTTP/HTTPS 인바운드 허용
        self.ecs_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(8501),  # Streamlit 기본 포트
            "Allow Streamlit access"
        )

        # ALB Security Group
        self.alb_security_group = ec2.SecurityGroup(
            self, "AlbSecurityGroup",
            vpc=self.vpc,
            description="Security group for Application Load Balancer",
            allow_all_outbound=True
        )

        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow HTTP access"
        )

        self.alb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "Allow HTTPS access"
        )

        # Outputs
        CfnOutput(
            self, "VpcId",
            value=self.vpc.vpc_id,
            description="VPC ID"
        )

        CfnOutput(
            self, "EcsSecurityGroupId",
            value=self.ecs_security_group.security_group_id,
            description="ECS Security Group ID"
        )
