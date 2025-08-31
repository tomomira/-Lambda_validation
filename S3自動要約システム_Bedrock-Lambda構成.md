# S3自動要約システム - Bedrock Lambda構成

## システム概要

S3バケット（`homedata-2025-06`）にテキストファイルがアップロードされた際に、Amazon BedrockのClaude LLMを使用して自動的に要約を生成するサーバーレスシステムです。

### 主な機能
- S3イベント駆動型の自動要約処理
- 複数エンコーディング対応（UTF-8、Shift-JIS、CP932）
- ファイルサイズに応じた適応的要約設定
- 結果をJSON・テキスト両形式で保存
- 詳細なログ出力とエラーハンドリング

---

## システム構成

```
[S3バケット: homedata-2025-06]
  ├── document1.txt           # テキストファイルアップロード先
  ├── document2.md
  └── summaries/              # 要約結果保存先
      ├── document1_summary_20241201_143022.json
      ├── document1_summary_20241201_143022.txt
      ├── document2_summary_20241201_143125.json
      └── document2_summary_20241201_143125.txt

[Lambda関数] → [Amazon Bedrock (Claude)]
```

### 処理フロー

1. **ファイルアップロード**
   - バケットルートにテキストファイル（.txt, .md, .csv等）をアップロード

2. **S3イベント発生**
   - S3がObjectCreatedイベントを発生
   - Lambda関数が自動トリガー

3. **ファイル処理**
   - ファイル形式の検証（テキストファイルのみ処理）
   - エンコーディング自動判定で読み込み
   - ファイルサイズによる要約設定の決定

4. **LLM要約処理**
   - Bedrock経由でClaudeに要約リクエスト
   - 適応的なプロンプト生成

5. **結果保存**
   - `summaries/` フォルダーにJSON形式（詳細情報付き）
   - `summaries/` フォルダーにテキスト形式（要約文のみ）

---

## Lambda関数コード

### メイン処理 (`lambda_function.py`)

```python
import json
import boto3
import os
from datetime import datetime
from urllib.parse import unquote_plus

# AWSクライアントの初期化
bedrock_runtime = boto3.client('bedrock-runtime')
s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    S3オブジェクト作成イベントをトリガーとした自動要約処理
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
            
            # ファイル拡張子をチェック（テキストファイルのみ処理）
            if not is_text_file(object_key):
                print(f"Skipping non-text file: {object_key}")
                continue
            
            # S3からテキストファイルを読み込み
            text_content = get_text_from_s3(bucket_name, object_key)
            
            if not text_content or len(text_content.strip()) < 50:
                print(f"File too short or empty, skipping: {object_key}")
                continue
            
            # Bedrockで要約処理
            summary_result = process_summarization(text_content, object_key)
            
            # 要約結果をS3に保存
            save_summary_to_s3(bucket_name, object_key, summary_result)
            
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
        
        # エラー通知（SNSやCloudWatch等に送信可能）
        # send_error_notification(error_message, event)
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'error': error_message
            })
        }

def is_text_file(object_key):
    """
    ファイル拡張子からテキストファイルかどうか判定
    """
    text_extensions = ['.txt', '.md', '.csv', '.json', '.log', '.rtf']
    return any(object_key.lower().endswith(ext) for ext in text_extensions)

def get_text_from_s3(bucket, key):
    """
    S3からテキストファイルを取得（エンコーディング自動判定）
    """
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        
        # エンコーディングの自動検出
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return content.decode('shift_jis')
            except UnicodeDecodeError:
                try:
                    return content.decode('cp932')
                except UnicodeDecodeError:
                    return content.decode('utf-8', errors='ignore')
                    
    except Exception as e:
        print(f"Error reading from S3: {str(e)}")
        raise e

def process_summarization(text_content, filename):
    """
    Bedrockを使用したテキスト要約処理
    """
    # 文書の長さに応じた要約設定
    text_length = len(text_content)
    
    if text_length < 500:
        max_length = 100
        summary_type = 'brief'
    elif text_length < 2000:
        max_length = 200
        summary_type = 'general'
    else:
        max_length = 400
        summary_type = 'detailed'
    
    # 要約用プロンプトの構築
    prompt = build_summarization_prompt(text_content, summary_type, max_length)
    
    # Bedrockモデルの呼び出し
    model_params = {
        'max_tokens': max_length * 2,  # 余裕を持たせる
        'temperature': 0.3,  # 要約は一貫性重視
        'top_p': 0.9
    }
    
    response = invoke_bedrock_model(prompt, model_params)
    
    return {
        'summary': response['content'],
        'original_filename': filename,
        'original_length': text_length,
        'summary_length': len(response['content']),
        'compression_ratio': len(response['content']) / text_length,
        'summary_type': summary_type,
        'model_used': response.get('model_id', 'unknown'),
        'processed_at': datetime.now().isoformat()
    }

def build_summarization_prompt(text, summary_type, max_length):
    """
    要約用プロンプトの構築
    """
    if summary_type == 'brief':
        instruction = f"以下のテキストの要点を{max_length}文字以内で簡潔にまとめてください。"
    elif summary_type == 'detailed':
        instruction = f"以下のテキストを{max_length}文字以内で詳細に要約し、重要なポイントを漏らさないようにしてください。"
    else:
        instruction = f"以下のテキストを{max_length}文字以内で要約してください。"
    
    return f"""{instruction}

テキスト:
{text}

要約:"""

def invoke_bedrock_model(prompt, model_params=None):
    """
    Bedrockモデル（Claude）の呼び出し
    """
    # 環境変数からモデルIDを取得（デフォルト：Claude Haiku）
    model_id = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-haiku-20240307-v1:0')
    
    # デフォルトパラメータ
    default_params = {
        'max_tokens': 4000,
        'temperature': 0.3,
        'top_p': 0.9
    }
    
    if model_params:
        default_params.update(model_params)
    
    try:
        # Claudeモデル用のリクエスト形式
        request_body = {
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': default_params['max_tokens'],
            'temperature': default_params['temperature'],
            'top_p': default_params['top_p'],
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
        usage = response_body.get('usage', {})
        
        return {
            'content': content,
            'model_id': model_id,
            'usage': usage
        }
        
    except Exception as e:
        print(f"Error invoking Bedrock model: {str(e)}")
        raise e

def save_summary_to_s3(bucket_name, original_key, summary_result):
    """
    要約結果をS3に保存
    """
    try:
        # 出力ファイル名の生成
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = os.path.splitext(original_key)[0]
        summary_key = f"summaries/{base_name}_summary_{timestamp}.json"
        
        # 要約結果をJSON形式で保存
        summary_content = json.dumps(summary_result, ensure_ascii=False, indent=2)
        
        s3.put_object(
            Bucket=bucket_name,
            Key=summary_key,
            Body=summary_content.encode('utf-8'),
            ContentType='application/json; charset=utf-8',
            Metadata={
                'original-file': original_key,
                'processing-type': 'summary',
                'processed-at': summary_result['processed_at']
            }
        )
        
        # 要約テキストのみのファイルも保存
        text_summary_key = f"summaries/{base_name}_summary_{timestamp}.txt"
        s3.put_object(
            Bucket=bucket_name,
            Key=text_summary_key,
            Body=summary_result['summary'].encode('utf-8'),
            ContentType='text/plain; charset=utf-8',
            Metadata={
                'original-file': original_key,
                'processing-type': 'summary-text',
                'processed-at': summary_result['processed_at']
            }
        )
        
        print(f"Summary saved to: s3://{bucket_name}/{summary_key}")
        print(f"Summary text saved to: s3://{bucket_name}/{text_summary_key}")
        
        return {
            'summary_json': f"s3://{bucket_name}/{summary_key}",
            'summary_text': f"s3://{bucket_name}/{text_summary_key}"
        }
        
    except Exception as e:
        print(f"Error saving summary to S3: {str(e)}")
        raise e

def send_error_notification(error_message, event):
    """
    エラー通知の送信（オプション）
    """
    # SNS等でエラー通知を送信する場合の実装
    # sns = boto3.client('sns')
    # sns.publish(
    #     TopicArn=os.environ.get('ERROR_NOTIFICATION_TOPIC'),
    #     Message=f"S3自動要約処理でエラーが発生しました: {error_message}",
    #     Subject="Lambda要約処理エラー"
    # )
    pass
```

---

## 設定手順

### 1. Lambda関数の作成

#### 関数名
- s3-file-summary
#### ランタイム設定
- **ランタイム:** Python 3.9以上
- **タイムアウト:** 5分
- **メモリ:** 512MB以上
- **ハンドラー:** `lambda_function.lambda_handler`

#### 環境変数
```
BEDROCK_MODEL_ID = anthropic.claude-3-haiku-20240307-v1:0
```

### 2. IAMロール権限の設定

Lambda実行ロールに以下のポリシーを追加：インラインポリシー：名前：s3-file-summary-policy

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": [
                "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject"
            ],
            "Resource": [
                "arn:aws:s3:::homedata-2025-06/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject"
            ],
            "Resource": [
                "arn:aws:s3:::homedata-2025-06/summaries/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}
```

### 3. S3イベント通知の設定

#### AWS CLIでの設定例
```bash
aws s3api put-bucket-notification-configuration \
  --bucket homedata-2025-06 \
  --notification-configuration '{
    "LambdaConfigurations": [
      {
        "Id": "TextFileUploadTrigger",
        "LambdaFunctionArn": "arn:aws:lambda:REGION:ACCOUNT:function:s3-file-summary",
        "Events": ["s3:ObjectCreated:*"]
      }
    ]
  }'
```

#### AWS Console での設定
1. S3バケット `homedata-2025-06` を開く
2. **プロパティ** タブ → **イベント通知**
3. **イベント通知を作成** をクリック
4. 以下の設定を入力：
   - **名前:** `TextFileUploadTrigger`
   - **プレフィックス:** （空欄）
   - **サフィックス:** （空欄 - 全ファイル対象）
   - **イベントタイプ:** **すべてのオブジェクト作成イベント**
   - **送信先:** **Lambda関数**
   - **Lambda関数:** `s3-file-summary`

---

## 使用方法

### 1. テストファイルのアップロード
```bash
# AWS CLIでファイルをアップロード
aws s3 cp sample-document.txt s3://homedata-2025-06/
```

### 2. 処理結果の確認
```bash
# 要約結果の確認
aws s3 ls s3://homedata-2025-06/summaries/

# 具体的なファイルの内容確認
aws s3 cp s3://homedata-2025-06/summaries/sample-document_summary_20241201_143022.txt ./
```

### 3. CloudWatch Logsでの処理ログ確認
Lambda関数の実行ログはCloudWatch Logsで確認できます：
- ロググループ: `/aws/lambda/[関数名]`

---

## 出力形式

### JSON形式 (詳細情報付き)
```json
{
  "summary": "文書の要約内容がここに表示されます...",
  "original_filename": "sample-document.txt",
  "original_length": 1523,
  "summary_length": 247,
  "compression_ratio": 0.162,
  "summary_type": "general",
  "model_used": "anthropic.claude-3-haiku-20240307-v1:0",
  "processed_at": "2024-12-01T14:30:22.123456"
}
```

### テキスト形式（要約のみ）
```
文書の要約内容がここに表示されます。重要なポイントを簡潔にまとめ、
元の文書の主要な内容を理解しやすい形で提供します...
```

---

## 対応ファイル形式

- `.txt` - テキストファイル
- `.md` - Markdownファイル
- `.csv` - CSVファイル（テキスト部分）
- `.json` - JSONファイル（テキスト部分）
- `.log` - ログファイル
- `.rtf` - リッチテキストファイル

### エンコーディング対応
- UTF-8（推奨）
- Shift-JIS
- CP932
- その他（自動判定、エラー時はignore）

---

## 費用目安

### Lambda
- 実行時間: 約5-30秒/ファイル
- メモリ使用量: 512MB
- 月間1,000ファイル処理の場合: 約$0.10-0.50

### Bedrock (Claude Haiku)
- 入力トークン: $0.00025/1K tokens
- 出力トークン: $0.00125/1K tokens
- 平均的な文書（2KB）の要約: 約$0.002-0.005/ファイル

### S3
- ストレージ: 標準的な料金
- リクエスト: PUT/GETリクエスト料金

---

## トラブルシューティング

### 実際に発生した問題と解決方法

#### 1. IAM権限不足エラー
**エラー内容:**
```
AccessDenied: User is not authorized to perform: s3:GetObject on resource
```

**原因:** Lambda実行ロールにS3読み取り権限がない、または**バケット名が古い設定**のまま

**解決方法:**
1. **IAM Console** → Lambda実行ロール → **インラインポリシー編集**
2. バケット名が `homedata-2025-06` に正しく更新されているか確認
3. `s3:GetObject` 権限が `arn:aws:s3:::homedata-2025-06/*` に設定されているか確認
4. **ポリシー更新後、1-2分待機してからテスト**

#### 2. Bedrockモデルアクセスエラー
**エラー内容:**
```
AccessDeniedException: You don't have access to the model with the specified model ID
```

**原因:** Bedrockモデルへのアクセス権限が未リクエスト

**解決方法:**
1. **Amazon Bedrock Console** → **Model access**
2. **Manage model access** → **Anthropic** → **Claude 3 Haiku** にチェック
3. **Submit** で権限をリクエスト（通常1-5分で有効）
4. **Access granted** 表示を確認後テスト

#### 3. Lambda関数タイムアウト
**エラー内容:**
```
Task timed out after 3.00 seconds
```

**原因:** デフォルトタイムアウト（3秒）が短すぎる

**解決方法:**
1. **Lambda Console** → **Configuration** → **General configuration** → **Edit**
2. **Timeout:** **5 min 0 sec** に変更
3. **Memory:** **512 MB** 以上に設定
4. **Save** 後にテスト

#### 4. 無限ループ問題
**症状:** Lambda関数が連続実行され、要約結果ファイルが次々と生成される

**原因:** 要約結果を `summaries/` フォルダに保存した際、そのファイル自体が新しいS3イベントをトリガー

**解決方法:**
1. **緊急停止:** S3イベント通知のLambdaトリガーを削除
2. **コード修正:** `summaries/` フォルダのファイルをスキップするロジックを追加
```python
# summaries フォルダのファイルは処理しない（無限ループ防止）
if object_key.startswith('summaries/'):
    print(f"Skipping summary file: {object_key}")
    continue
```
3. **不要ファイル削除:** 無限ループで生成されたファイルを削除
4. **S3イベント通知を再設定**

#### 5. Lambda関数構文エラー
**エラー内容:**
```
Syntax error in module 'lambda_function': unexpected indent (lambda_function.py, line 1)
```

**原因:** コードの先頭や行の前に不要な空白・タブが混入

**解決方法:**
1. **Lambda Console** で既存コードを**完全削除**
2. **新しいコードを一行ずつ慎重にコピー**
3. **コードブロックの先頭に余計な空白がないことを確認**
4. **Deploy** ボタンでコードを保存

#### 6. S3イベント通知の設定競合
**エラー内容:**
```
Configuration is ambiguously defined. Cannot have overlapping suffixes in two rules if the prefixes are overlapping
```

**原因:** 既存のS3イベント通知と新しい設定でプレフィックス・サフィックスが競合

**解決方法:**
1. **S3 Console** → バケット → **プロパティ** → **イベント通知**
2. **既存の通知設定を確認・削除**
3. **新しい設定を作成**（プレフィックス・サフィックス空欄で全ファイル対象）

### よくある問題

#### 7. Lambda関数がトリガーされない
- S3イベント通知の設定を確認
- Lambda関数のリソースベースポリシーを確認
- バケットとLambda関数が同じリージョンにあることを確認

#### 8. エンコーディングエラー
- サポートしているエンコーディングか確認
- バイナリファイルではないか確認

### ログの確認方法
```bash
# CloudWatch Logsの確認
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/"
aws logs describe-log-streams --log-group-name "/aws/lambda/s3-file-summary"
aws logs get-log-events --log-group-name "/aws/lambda/s3-file-summary" --log-stream-name "[ログストリーム名]"
```

### 正常動作時のログ例
```
2025-08-30T03:08:42.884Z INIT_START Runtime Version: python:3.13.v60
2025-08-30T03:08:43.347Z START RequestId: xxx
2025-08-30T03:08:43.347Z Processing file: s3://homedata-2025-06/test.txt
2025-08-30T03:08:44.123Z Successfully processed and saved summary for: test.txt
2025-08-30T03:08:44.123Z Summary saved to: s3://homedata-2025-06/summaries/test_summary_20250830_030844.json
2025-08-30T03:08:44.140Z END RequestId: xxx
```

### 緊急時の対応手順

#### 無限ループ発生時
1. **即座にS3イベント通知を削除**（Lambda Console → Configuration → Triggers → Delete）
2. CloudWatchログで実行が停止したことを確認
3. `aws s3 rm s3://homedata-2025-06/summaries/ --recursive` で不要ファイルを削除
4. コードを修正してからイベント通知を再設定

#### 高コスト発生時
1. Lambda関数を無効化またはイベント通知を削除
2. CloudWatch Logsで実行回数を確認
3. Bedrock使用量を確認（コンソールまたは請求情報）
4. 原因特定後に設定を修正して再開

---

## 拡張・カスタマイズ

### 1. 要約品質の向上
- より高性能なモデル（Claude Sonnet/Opus）の使用
- プロンプトの最適化
- ファイル種別に応じた専用プロンプト

### 2. 通知機能の追加
```python
# SNS通知の実装例
def send_completion_notification(summary_result):
    sns = boto3.client('sns')
    sns.publish(
        TopicArn=os.environ.get('COMPLETION_NOTIFICATION_TOPIC'),
        Message=f"要約処理が完了しました: {summary_result['original_filename']}",
        Subject="要約処理完了通知"
    )
```

### 3. バッチ処理機能
- 複数ファイルの一括処理
- SQSを使用した処理キューの実装

### 4. Web UI の追加
- S3 + CloudFrontでの静的ウェブホスティング
- API Gatewayを追加したRESTful API化
- リアルタイム処理状況の表示

---

## セキュリティ考慮事項

### 1. アクセス制御
- 最小権限の原則でIAMポリシーを設定
- S3バケットポリシーでアクセス制限
- VPC内でのBedrock通信（必要に応じて）

### 2. データ保護
- 機密情報を含むファイルの処理時は注意
- CloudTrailでの操作ログ記録
- 要約結果の適切な保管期間設定

### 3. コスト制御
- CloudWatch Alarmsでの使用量監視
- 予算アラートの設定
- 不要な処理の防止（ファイルサイズ制限等）
- **重要:** 無限ループによる課金を防ぐため、必ず `summaries/` フォルダ除外ロジックを実装

---

## まとめ

このS3自動要約システムは、アップロードされたテキストファイルを自動的にAIで要約し、構造化された形で保存するサーバーレスソリューションです。シンプルな設定で高度なAI機能を活用できる、スケーラブルで費用効率の良いシステムとなっています。

運用開始後は、CloudWatch Logsでの動作確認と、実際のファイルでのテスト実行を推奨します。