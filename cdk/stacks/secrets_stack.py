from aws_cdk import (
    Stack,
    aws_secretsmanager as secretsmanager,
    CfnOutput
)
from constructs import Construct

class SecretsStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Notion Token Secret
        self.notion_token_secret = secretsmanager.Secret(
            self, "NotionTokenSecret",
            secret_name="notion-chatbot/notion-token",
            description="Notion Integration Token for Chatbot",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"token": ""}',
                generate_string_key="token",
                exclude_characters=' "%@/\\'
            )
        )

        # 애플리케이션 설정을 위한 Secret
        self.app_config_secret = secretsmanager.Secret(
            self, "AppConfigSecret",
            secret_name="notion-chatbot/app-config",
            description="Application configuration for Notion Chatbot",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"bedrock_model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0", "aws_region": "ap-northeast-2", "max_tokens": "4000", "temperature": "0.1"}',
                generate_string_key="dummy"
            )
        )

        # Secrets 딕셔너리로 반환 (다른 스택에서 사용)
        self.secrets = {
            "notion_token": self.notion_token_secret,
            "app_config": self.app_config_secret
        }

        # Outputs
        CfnOutput(
            self, "NotionTokenSecretArn",
            value=self.notion_token_secret.secret_arn,
            description="Notion Token Secret ARN"
        )

        CfnOutput(
            self, "AppConfigSecretArn",
            value=self.app_config_secret.secret_arn,
            description="App Config Secret ARN"
        )
