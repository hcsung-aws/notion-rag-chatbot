import json
import boto3
import requests
from typing import List, Dict, Any
import streamlit as st

class OpenSearchClient:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.bedrock_client = boto3.client('bedrock-runtime', region_name='ap-northeast-2')
    
    def generate_embedding(self, text: str) -> List[float]:
        """텍스트를 벡터 임베딩으로 변환"""
        try:
            response = self.bedrock_client.invoke_model(
                modelId='amazon.titan-embed-text-v1',
                body=json.dumps({
                    'inputText': text[:8000]  # Titan 모델 제한
                })
            )
            
            response_body = json.loads(response['body'].read())
            return response_body['embedding']
            
        except Exception as e:
            st.error(f"임베딩 생성 오류: {str(e)}")
            return []
    
    def semantic_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """의미 기반 벡터 검색"""
        try:
            # 쿼리를 벡터로 변환
            query_embedding = self.generate_embedding(query)
            
            if not query_embedding:
                return []
            
            # OpenSearch KNN 검색 쿼리
            search_body = {
                "size": limit,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": query_embedding,
                            "k": limit
                        }
                    }
                },
                "_source": ["id", "title", "content", "url", "metadata"]
            }
            
            # OpenSearch에 검색 요청
            response = requests.post(
                f"{self.endpoint}/notion-index/_search",
                json=search_body,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                results = response.json()
                documents = []
                
                for hit in results.get('hits', {}).get('hits', []):
                    source = hit['_source']
                    score = hit['_score']
                    
                    documents.append({
                        'id': source.get('id'),
                        'title': source.get('title', '제목 없음'),
                        'content': source.get('content', ''),
                        'url': source.get('url', ''),
                        'metadata': source.get('metadata', {}),
                        'similarity_score': score
                    })
                
                return documents
            else:
                st.error(f"OpenSearch 검색 오류: {response.status_code}")
                return []
                
        except Exception as e:
            st.error(f"의미 검색 오류: {str(e)}")
            return []
    
    def hybrid_search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """하이브리드 검색 (키워드 + 의미 검색)"""
        try:
            query_embedding = self.generate_embedding(query)
            
            if not query_embedding:
                return []
            
            # 하이브리드 검색 쿼리
            search_body = {
                "size": limit,
                "query": {
                    "bool": {
                        "should": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title^2", "content"],
                                    "type": "best_fields",
                                    "boost": 1.0
                                }
                            },
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": limit,
                                        "boost": 2.0
                                    }
                                }
                            }
                        ]
                    }
                },
                "_source": ["id", "title", "content", "url", "metadata"]
            }
            
            response = requests.post(
                f"{self.endpoint}/notion-index/_search",
                json=search_body,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                results = response.json()
                documents = []
                
                for hit in results.get('hits', {}).get('hits', []):
                    source = hit['_source']
                    score = hit['_score']
                    
                    documents.append({
                        'id': source.get('id'),
                        'title': source.get('title', '제목 없음'),
                        'content': source.get('content', ''),
                        'url': source.get('url', ''),
                        'metadata': source.get('metadata', {}),
                        'similarity_score': score
                    })
                
                return documents
            else:
                st.error(f"하이브리드 검색 오류: {response.status_code}")
                return []
                
        except Exception as e:
            st.error(f"하이브리드 검색 오류: {str(e)}")
            return []
