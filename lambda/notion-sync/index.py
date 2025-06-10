import json
import boto3
import urllib3
import os
from datetime import datetime

def handler(event, context):
    print("Starting Notion sync...")
    
    # AWS 클라이언트 초기화
    s3 = boto3.client('s3')
    secrets_manager = boto3.client('secretsmanager')
    
    try:
        # Notion 토큰 가져오기
        secret_response = secrets_manager.get_secret_value(
            SecretId=os.environ['NOTION_TOKEN_SECRET_ARN']
        )
        secret_data = json.loads(secret_response['SecretString'])
        notion_token = secret_data['token']
        
        # urllib3를 사용한 HTTP 요청
        http = urllib3.PoolManager()
        
        # Notion API 헤더
        headers = {
            'Authorization': f'Bearer {notion_token}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28'
        }
        
        # Notion 페이지 검색
        search_payload = {
            'filter': {
                'property': 'object',
                'value': 'page'
            },
            'page_size': 50
        }
        
        search_response = http.request(
            'POST',
            'https://api.notion.com/v1/search',
            body=json.dumps(search_payload),
            headers=headers
        )
        
        if search_response.status != 200:
            print(f"Notion API error: {search_response.status}")
            return {'statusCode': 500, 'body': 'Notion API error'}
        
        search_data = json.loads(search_response.data.decode('utf-8'))
        pages = search_data.get('results', [])
        print(f"Found {len(pages)} pages")
        
        # 각 페이지 처리
        for page in pages:
            page_id = page['id']
            
            # 페이지 제목 추출
            title = "Untitled"
            if 'properties' in page:
                for prop_name, prop_data in page['properties'].items():
                    if prop_data.get('type') == 'title':
                        title_array = prop_data.get('title', [])
                        if title_array:
                            title = title_array[0].get('text', {}).get('content', 'Untitled')
                        break
            
            # 페이지 내용 가져오기
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
                    block_text = extract_block_text(block)
                    if block_text:
                        content_parts.append(block_text)
                
                content = '\n'.join(content_parts)
            
            # S3에 저장할 데이터 준비
            document = {
                'id': page_id,
                'title': title,
                'content': content,
                'url': page.get('url', ''),
                'last_edited_time': page.get('last_edited_time', ''),
                'created_time': page.get('created_time', ''),
                'metadata': {
                    'source': 'notion',
                    'type': 'page',
                    'title': title,
                    'url': page.get('url', '')
                }
            }
            
            # S3에 저장
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
            'body': json.dumps({
                'message': f'Successfully synced {len(pages)} pages'
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def extract_block_text(block):
    block_type = block.get('type')
    
    if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
        rich_text = block.get(block_type, {}).get('rich_text', [])
        return ''.join([text.get('text', {}).get('content', '') for text in rich_text])
    
    elif block_type == 'bulleted_list_item':
        rich_text = block.get('bulleted_list_item', {}).get('rich_text', [])
        text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
        return f"• {text}"
    
    elif block_type == 'numbered_list_item':
        rich_text = block.get('numbered_list_item', {}).get('rich_text', [])
        text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
        return f"1. {text}"
    
    elif block_type == 'to_do':
        rich_text = block.get('to_do', {}).get('rich_text', [])
        text = ''.join([text.get('text', {}).get('content', '') for text in rich_text])
        checked = block.get('to_do', {}).get('checked', False)
        checkbox = "☑" if checked else "☐"
        return f"{checkbox} {text}"
    
    return ""
