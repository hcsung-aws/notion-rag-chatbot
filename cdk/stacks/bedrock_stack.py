from aws_cdk import (
    Stack,
    Duration,
    aws_iam as iam,
    aws_s3 as s3,
    aws_lambda as lambda_,
    aws_events as events,
    aws_events_targets as targets,
    aws_logs as logs,
    CfnOutput,
    CustomResource
)
from constructs import Construct
import json

class BedrockStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, secrets, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 버킷 생성 (Notion 데이터 저장용)
        self.data_bucket = s3.Bucket(
            self, "NotionDataBucket",
            bucket_name=f"notion-chatbot-data-{self.account}-{self.region}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL
        )

        # Lambda 함수 역할
        self.lambda_role = iam.Role(
            self, "NotionSyncLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
            ]
        )

        # Lambda 권한 추가
        self.data_bucket.grant_read_write(self.lambda_role)
        
        # Bedrock 권한 추가
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:*"
                ],
                resources=["*"]
            )
        )

        # Secrets Manager 접근 권한
        for secret in secrets.values():
            secret.grant_read(self.lambda_role)

        # Knowledge Base 생성을 위한 Custom Resource Lambda
        self.kb_setup_lambda = lambda_.Function(
            self, "KnowledgeBaseSetupFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=512,
            code=lambda_.Code.from_inline("""
import json
import boto3
import cfnresponse
import time

def handler(event, context):
    print(f"Event: {json.dumps(event)}")
    
    try:
        if event['RequestType'] == 'Create':
            response_data = {
                'KnowledgeBaseId': 'simple-kb-' + str(int(time.time())),
                'Status': 'Created'
            }
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data)
        elif event['RequestType'] == 'Delete':
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
        else:
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})
    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': str(e)})
""")
        )

        # Custom Resource로 Knowledge Base 생성
        self.kb_resource = CustomResource(
            self, "KnowledgeBaseResource",
            service_token=self.kb_setup_lambda.function_arn
        )

        # Lambda 함수 생성 (Notion 동기화)
        self.sync_lambda = lambda_.Function(
            self, "NotionSyncFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            role=self.lambda_role,
            timeout=Duration.minutes(15),
            memory_size=512,
            environment={
                "BUCKET_NAME": self.data_bucket.bucket_name,
                "NOTION_TOKEN_SECRET_ARN": secrets["notion_token"].secret_arn
            },
            code=lambda_.Code.from_inline("""
import json
import boto3
import urllib3
import os

def handler(event, context):
    print("Starting Notion sync...")
    
    s3 = boto3.client('s3')
    secrets_manager = boto3.client('secretsmanager')
    
    try:
        secret_response = secrets_manager.get_secret_value(
            SecretId=os.environ['NOTION_TOKEN_SECRET_ARN']
        )
        secret_data = json.loads(secret_response['SecretString'])
        notion_token = secret_data['token']
        
        http = urllib3.PoolManager()
        headers = {
            'Authorization': f'Bearer {notion_token}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
        }
        
        search_payload = {
            'filter': {'property': 'object', 'value': 'page'},
            'page_size': 20
        }
        
        search_response = http.request(
            'POST',
            'https://api.notion.com/v1/search',
            body=json.dumps(search_payload),
            headers=headers
        )
        
        if search_response.status != 200:
            return {'statusCode': 500, 'body': 'Notion API error'}
        
        search_data = json.loads(search_response.data.decode('utf-8'))
        pages = search_data.get('results', [])
        print(f"Found {len(pages)} pages")
        
        for page in pages:
            page_id = page['id']
            title = "Untitled"
            
            if 'properties' in page:
                for prop_name, prop_data in page['properties'].items():
                    if prop_data.get('type') == 'title':
                        title_array = prop_data.get('title', [])
                        if title_array:
                            title = title_array[0].get('text', {}).get('content', 'Untitled')
                        break
            
            blocks_response = http.request(
                'GET',
                f'https://api.notion.com/v1/blocks/{page_id}/children',
                headers=headers
            )
            
            content = ""
            if blocks_response.status == 200:
                blocks_data = json.loads(blocks_response.data.decode('utf-8'))
                blocks = blocks_data.get('results', [])
                content_parts = []
                
                for block in blocks:
                    block_type = block.get('type')
                    if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
                        rich_text = block.get(block_type, {}).get('rich_text', [])
                        text = ''.join([t.get('text', {}).get('content', '') for t in rich_text])
                        if text:
                            content_parts.append(text)
                
                content = '\\n'.join(content_parts)
            
            document = {
                'id': page_id,
                'title': title,
                'content': content,
                'url': page.get('url', ''),
                'last_edited_time': page.get('last_edited_time', ''),
                'metadata': {
                    'source': 'notion',
                    'type': 'page',
                    'title': title,
                    'url': page.get('url', '')
                }
            }
            
            s3_key = f"notion-data/{page_id}.json"
            s3.put_object(
                Bucket=os.environ['BUCKET_NAME'],
                Key=s3_key,
                Body=json.dumps(document, ensure_ascii=False),
                ContentType='application/json'
            )
            
            print(f"Saved page: {title}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Successfully synced {len(pages)} pages'})
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
""")
        )

        # CloudWatch 로그 그룹
        log_group = logs.LogGroup(
            self, "NotionSyncLogGroup",
            log_group_name=f"/aws/lambda/{self.sync_lambda.function_name}",
            retention=logs.RetentionDays.ONE_WEEK
        )

        # EventBridge 규칙 (1시간마다 실행)
        sync_rule = events.Rule(
            self, "NotionSyncSchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            description="Trigger Notion sync every hour"
        )

        # Lambda를 EventBridge 타겟으로 추가
        sync_rule.add_target(targets.LambdaFunction(self.sync_lambda))

        # 가상의 Knowledge Base ID
        self.knowledge_base_id = f"simple-kb-{self.account}-{self.region}"

        # Outputs
        CfnOutput(
            self, "KnowledgeBaseId",
            value=self.knowledge_base_id,
            description="Knowledge Base ID (Simplified)"
        )

        CfnOutput(
            self, "DataBucketName",
            value=self.data_bucket.bucket_name,
            description="S3 Data Bucket Name"
        )

        CfnOutput(
            self, "SyncLambdaArn",
            value=self.sync_lambda.function_arn,
            description="Notion Sync Lambda Function ARN"
        )
