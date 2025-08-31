import json
import boto3
from datetime import datetime
from urllib.parse import unquote_plus

# AWSクライアントの初期化
bedrock_runtime = boto3.client('bedrock-runtime')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    S3オブジェクト作成イベントをトリガーとした簡易要約処理
    """
    
    try:
        # S3イベントの解析
        for record in event['Records']:
            # S3イベント情報の取得
            bucket_name = record['s3']['bucket']['name']
            object_key = unquote_plus(record['s3']['object']['key'])
            
            print(f"Processing file: s3://{bucket_name}/{object_key}")
            
            # summaries フォルダのファイルは処理しない（無限ループ防止）
            if object_key.startswith('summaries/'):
                print(f"Skipping summary file: {object_key}")
                continue
            
            # .txtファイルのみ処理
            if not object_key.lower().endswith('.txt'):
                print(f"Skipping non-txt file: {object_key}")
                continue
            
            # S3からテキストファイルを読み込み
            text_content = get_text_from_s3(bucket_name, object_key)
            
            if not text_content or len(text_content.strip()) < 50:
                print(f"File too short or empty, skipping: {object_key}")
                continue
            
            # Bedrockで要約処理
            summary = process_simple_summarization(text_content)
            
            # 要約結果をS3に保存
            save_summary_to_s3(bucket_name, object_key, summary)
            
            print(f"Successfully processed and saved summary for: {object_key}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'processed_files': len(event['Records'])
            })
        }
        
    except Exception as e:
        error_message = str(e)
        print(f"Error processing S3 event: {error_message}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'error': error_message
            })
        }

def get_text_from_s3(bucket, key):
    """
    S3からテキストファイルを取得（UTF-8固定）
    """
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        return content.decode('utf-8')
        
    except Exception as e:
        print(f"Error reading from S3: {str(e)}")
        raise e

def process_simple_summarization(text_content):
    """
    Bedrockを使用したシンプルテキスト要約処理
    """
    # 固定要約設定
    max_length = 200
    
    # シンプルな要約用プロンプト
    prompt = f"""以下のテキストを{max_length}文字以内で要約してください。

テキスト:
{text_content}

要約:"""
    
    # Bedrockモデルの呼び出し
    response = invoke_bedrock_model(prompt)
    return response['content']

def invoke_bedrock_model(prompt):
    """
    Bedrockモデル（Claude）の呼び出し - シンプル版
    """
    model_id = 'anthropic.claude-3-haiku-20240307-v1:0'
    
    try:
        # Claudeモデル用のリクエスト形式
        request_body = {
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 500,
            'temperature': 0.3,
            'top_p': 0.9,
            'messages': [
                {
                    'role': 'user',
                    'content': prompt
                }
            ]
        }
        
        # Bedrock APIの呼び出し
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body)
        )
        
        # レスポンスの解析
        response_body = json.loads(response['body'].read())
        content = response_body['content'][0]['text']
        
        return {
            'content': content,
            'model_id': model_id
        }
        
    except Exception as e:
        print(f"Error invoking Bedrock model: {str(e)}")
        raise e

def save_summary_to_s3(bucket_name, original_key, summary):
    """
    要約結果をS3に保存（テキスト形式のみ）
    """
    try:
        # 出力ファイル名の生成
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = original_key.replace('.txt', '')
        summary_key = f"summaries/{base_name}_summary_{timestamp}.txt"
        
        # 要約結果をテキスト形式で保存
        s3.put_object(
            Bucket=bucket_name,
            Key=summary_key,
            Body=summary.encode('utf-8'),
            ContentType='text/plain; charset=utf-8'
        )
        
        print(f"Summary saved to: s3://{bucket_name}/{summary_key}")
        
    except Exception as e:
        print(f"Error saving summary to S3: {str(e)}")
        raise e