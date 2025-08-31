# S3簡易要約システム - Bedrock Lambda構成（Simple版）

## システム概要

S3バケット（`homedata-2025-06-01`）にテキストファイル（.txt）がアップロードされた際に、Amazon BedrockのClaude LLMを使用して自動的に要約を生成する**簡易版**サーバーレスシステムです。

### 主な機能
- S3イベント駆動型の自動要約処理
- UTF-8エンコーディング固定対応
- 固定長要約設定（200文字程度）
- テキスト形式での結果保存のみ
- シンプルなエラーハンドリング

### 通常版との違い
| 項目 | 通常版 | 簡易版 |
|------|--------|--------|
| 対象ファイル | .txt, .md, .csv, .json, .log, .rtf | .txt のみ |
| エンコーディング | 自動判定（UTF-8, Shift-JIS, CP932） | UTF-8 固定 |
| 要約設定 | ファイルサイズに応じた適応的設定 | 固定設定（200文字） |
| 出力形式 | JSON + テキスト | テキストのみ |
| エラー処理 | 詳細なエラーハンドリング | 基本的なエラーハンドリング |

---

## システム構成

```
[S3バケット: homedata-2025-06-01]
  ├── document1.txt           # テキストファイルアップロード先
  ├── document2.txt
  └── summaries/              # 簡易版要約結果保存先
      ├── document1_summary_20241201_143022.txt
      └── document2_summary_20241201_143125.txt

[Lambda関数: s3-basic-summary] → [Amazon Bedrock (Claude)]
```

### 処理フロー

1. **ファイルアップロード**
   - バケットルートに.txtファイルをアップロード

2. **S3イベント発生**
   - S3がObjectCreatedイベントを発生
   - Lambda関数が自動トリガー

3. **ファイル処理**
   - .txtファイルのみ処理対象
   - UTF-8エンコーディングで読み込み
   - 50文字未満はスキップ

4. **LLM要約処理**
   - Bedrock経由でClaudeに要約リクエスト
   - 固定プロンプト使用（200文字要約）

5. **結果保存**
   - `summaries/` フォルダーにテキスト形式のみ保存

---

## Lambda関数コード

### メイン処理 (`lambda_function.py`)

```python
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
```

---

## 設定手順

### 1. Lambda関数の作成

#### 関数名
- s3-basic-summary

#### ランタイム設定
- **ランタイム:** Python 3.9以上
- **タイムアウト:** 2分 ⚠️ **重要: デフォルトの3秒では必ずタイムアウトします**
- **メモリ:** 256MB ⚠️ **重要: デフォルトの128MBでは不足する場合があります**
- **ハンドラー:** `lambda_function.lambda_handler`

### 2. IAMロール権限の設定

Lambda実行ロールに以下のポリシーを追加：

**インラインポリシー名:** `s3-basic-summary-policy`

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
                "arn:aws:s3:::homedata-2025-06-01/*"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:PutObject"
            ],
            "Resource": [
                "arn:aws:s3:::homedata-2025-06-01/summaries/*"
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

#### AWS Console での設定
1. S3バケット `homedata-2025-06-01` を開く
2. **プロパティ** タブ → **イベント通知**
3. **イベント通知を作成** をクリック
4. 以下の設定を入力：
   - **名前:** `BasicSummaryTrigger`
   - **プレフィックス:** （空欄）
   - **サフィックス:** `.txt`
   - **イベントタイプ:** **すべてのオブジェクト作成イベント**
   - **送信先:** **Lambda関数**
   - **Lambda関数:** `s3-basic-summary`

---

## 使用方法

### 1. テストファイルのアップロード
```bash
# AWS CLIでファイルをアップロード
aws s3 cp test-document.txt s3://homedata-2025-06-01/
```

### 2. 処理結果の確認
```bash
# 要約結果の確認
aws s3 ls s3://homedata-2025-06-01/summaries/

# 具体的なファイルの内容確認
aws s3 cp s3://homedata-2025-06-01/summaries/test-document_summary_20241201_143022.txt ./
```

---

## 出力形式

### テキスト形式（要約のみ）
```
文書の要約内容がここに表示されます。重要なポイントを簡潔にまとめ、
元の文書の主要な内容を理解しやすい形で提供します。
```

---

## 対応ファイル形式

- `.txt` - テキストファイルのみ

### エンコーディング対応
- UTF-8のみ

---

## 費用目安

### Lambda
- 実行時間: 約3-10秒/ファイル
- メモリ使用量: 256MB
- 月間1,000ファイル処理の場合: 約$0.05-0.20

### Bedrock (Claude Haiku)
- 入力トークン: $0.00025/1K tokens
- 出力トークン: $0.00125/1K tokens
- 平均的な文書（2KB）の要約: 約$0.001-0.003/ファイル

### S3
- ストレージ: 標準的な料金
- リクエスト: PUT/GETリクエスト料金

---

## トラブルシューティング

### よくある問題と解決方法

#### 1. Lambda関数がタイムアウトする（最も多い問題）
**エラー内容:**
```
REPORT RequestId: xxx Duration: 3000.00 ms Status: timeout
```

**原因:** デフォルトタイムアウト（3秒）が短すぎる

**解決方法:**
1. **Lambda Console** → **Configuration** → **General configuration** → **Edit**
2. **Timeout:** **2 min 0 sec** に変更
3. **Memory:** **256 MB** 以上に変更（推奨）
4. **Save** 後にテスト

**重要:** Bedrock API呼び出しには通常10-30秒かかるため、3秒では必ずタイムアウトします。

#### 2. Lambda関数がメモリ不足で失敗
**エラー内容:**
```
REPORT RequestId: xxx Max Memory Used: 128 MB Memory Size: 128 MB Status: error
```

**原因:** メモリ設定（128MB）が不足

**解決方法:**
1. **Lambda Console** → **Configuration** → **General configuration** → **Edit**
2. **Memory:** **256 MB** 以上に変更
3. 大きなファイル処理の場合は **512 MB** を推奨

#### 3. Lambda関数がトリガーされない
- S3イベント通知でサフィックスが `.txt` に設定されているか確認
- Lambda関数のリソースベースポリシーを確認
- バケット名が `homedata-2025-06-01` に正しく設定されているか確認

#### 4. UTF-8エンコーディングエラー
```
UnicodeDecodeError: 'utf-8' codec can't decode
```
- ファイルがUTF-8エンコーディングか確認
- 必要に応じて事前にファイルをUTF-8に変換

#### 5. 無限ループ発生（最も深刻な問題）
**症状:** Lambda関数が連続実行され、要約結果ファイルが次々と生成される

**エラーログ例:**
```
2025-08-31T01:13:59.298Z START RequestId: xxx
2025-08-31T01:13:59.300Z Processing file: s3://homedata-2025-06-01/summaries/test4_summary_20250831_011358.txt
2025-08-31T01:13:59.300Z Skipping summary file: summaries/test4_summary_20250831_011358.txt
```
↑ この「Skipping summary file」が正常。これが出ないと無限ループ

**原因:** 
- `summaries/` フォルダ除外ロジックが正しく動作していない
- S3イベント通知設定でフィルターが不適切

**緊急停止方法:**
1. **即座にS3イベント通知を削除**（Lambda Console → Configuration → Triggers → Delete）
2. CloudWatchログで実行が停止したことを確認
3. 不要な要約ファイルを削除: `aws s3 rm s3://homedata-2025-06-01/summaries/ --recursive`

**根本解決:**
```python
# このコードが正しく含まれているか確認
if object_key.startswith('summaries/'):
    print(f"Skipping summary file: {object_key}")
    continue
```

**予防策:**
- CloudWatch Alarmsで実行回数の監視設定
- S3イベント通知はテスト後に慎重に設定

#### 6. Bedrockモデルアクセスエラー
**エラー内容:**
```
AccessDeniedException: You don't have access to the model with the specified model ID
```

**原因:** Bedrockモデルへのアクセス権限が未リクエスト

**解決方法:**
1. **Amazon Bedrock Console** → **Model access**
2. **Manage model access** → **Anthropic** → **Claude 3 Haiku** にチェック
3. **Submit** で権限をリクエスト（通常1-5分で有効）

### 正常動作時のログ例

#### 成功パターン
```
2025-08-31T01:13:55.813Z START RequestId: 4f8d1746-094f-40d5-af8f-f1ef5da5c0e7
2025-08-31T01:13:55.814Z Processing file: s3://homedata-2025-06-01/test4.txt
2025-08-31T01:13:58.577Z Summary saved to: s3://homedata-2025-06-01/summaries/test4_summary_20250831_011358.txt
2025-08-31T01:13:58.577Z Successfully processed and saved summary for: test4.txt
2025-08-31T01:13:58.598Z END RequestId: 4f8d1746-094f-40d5-af8f-f1ef5da5c0e7
2025-08-31T01:13:58.598Z REPORT Duration: 2783.76 ms Memory Size: 128 MB Max Memory Used: 93 MB
```

#### 無限ループ防止の正常動作
```
2025-08-31T01:13:59.298Z START RequestId: 6bccabc2-be9e-4615-8096-56e88ccfd303
2025-08-31T01:13:59.300Z Processing file: s3://homedata-2025-06-01/summaries/test4_summary_20250831_011358.txt
2025-08-31T01:13:59.300Z Skipping summary file: summaries/test4_summary_20250831_011358.txt
2025-08-31T01:13:59.302Z END RequestId: 6bccabc2-be9e-4615-8096-56e88ccfd303
2025-08-31T01:13:59.302Z REPORT Duration: 2.38 ms
```
↑ **重要:** 「Skipping summary file」が出力されることで無限ループを防いでいる

### 緊急時の対応手順

#### 無限ループ発生時（最優先）
1. **即座にS3イベント通知を削除**
   - Lambda Console → s3-basic-summary → Configuration → Triggers
   - S3トリガーを削除
2. **実行停止の確認**
   - CloudWatch Logs で新しいログが停止したことを確認
3. **不要ファイルの削除**
   ```bash
   aws s3 rm s3://homedata-2025-06-01/summaries/ --recursive
   ```
4. **コード修正後に再設定**

#### 高コスト発生時
1. Lambda関数を無効化またはイベント通知を削除
2. CloudWatch Logsで実行回数を確認
3. Bedrock使用量を確認（コンソールまたは請求情報）
4. 原因特定後に設定を修正して再開

#### タイムアウト頻発時
1. CloudWatch Logs で Duration を確認
2. 3000ms（3秒）近くならタイムアウト設定を確認
3. **Configuration** → **General configuration** でタイムアウトを2分に変更

#### メモリ不足時
1. CloudWatch Logs で Max Memory Used vs Memory Size を比較
2. 使用量が設定値に近い場合、メモリを256MB以上に増量

---

## 通常版との違いについて

### システム分離の仕組み

このS3簡易要約システムは、通常版とは**完全に独立したS3バケット**（`homedata-2025-06-01`）を使用し、混乱を避けるために分離された構成となっています。

#### なぜ独立したバケットを使うのか？
1. **混乱防止**: 通常版と簡易版で完全に分離
2. **権限の明確化**: 各システム専用の権限設定
3. **管理の簡単さ**: 独立したシステムとして管理
4. **学習目的**: 簡易版を学習用として独立して使用可能

#### バケット構造の比較
```
# 通常版システム
homedata-2025-06/                    # 通常版専用バケット
├── document.txt                     # アップロードファイル
└── summaries/                       # 通常版出力
    ├── document_summary_xxx.json    # 詳細なJSON
    └── document_summary_xxx.txt     # テキスト形式

# 簡易版システム（この資料）
homedata-2025-06-01/                 # 簡易版専用バケット
├── document.txt                     # アップロードファイル
└── summaries/                       # 簡易版出力
    └── document_summary_xxx.txt     # テキスト形式のみ
```

#### 処理の流れ（独立システム）

**ファイルアップロード時**
```
# 通常版
homedata-2025-06 にアップロード → s3-file-summary が処理

# 簡易版  
homedata-2025-06-01 にアップロード → s3-basic-summary が処理

# 完全に独立して動作（同時実行なし）
```

### Lambda関数の住み分け

| 項目 | 通常版 | 簡易版 |
|------|--------|--------|
| **S3バケット** | `homedata-2025-06` | `homedata-2025-06-01` |
| **Lambda関数名** | `s3-file-summary` | `s3-basic-summary` |
| **トリガー対象** | 全ファイル形式 | .txt ファイルのみ |
| **出力先フォルダ** | `summaries/` | `summaries/` |
| **IAM権限範囲** | `homedata-2025-06/summaries/*` | `homedata-2025-06-01/summaries/*` |
| **実行ロール** | 独立したロール | 独立したロール |

### 実際の動作例

**アップロード:** `test-document.txt`

**結果:**
```
# 通常版（別システム）
homedata-2025-06/
├── test-document.txt                
├── summaries/
│   ├── test-document_summary_20250831_120000.json  
│   └── test-document_summary_20250831_120000.txt   

# 簡易版（このシステム）
homedata-2025-06-01/
├── test-document.txt                # アップロード先
└── summaries/
    └── test-document_summary_20250831_120001.txt   # 簡易版結果
```

### 設定時の注意点

#### S3イベント通知の設定

**簡易版のイベント通知:**（このシステム）
- バケット: `homedata-2025-06-01`
- 名前: `BasicSummaryTrigger`  
- 対象: `.txt` ファイルのみ（サフィックス `.txt`）
- Lambda: `s3-basic-summary`

**通常版のイベント通知:**（参考）
- バケット: `homedata-2025-06`
- 名前: `TextFileUploadTrigger`
- 対象: 全ファイル（プレフィックス・サフィックス空欄）
- Lambda: `s3-file-summary`

#### 独立システムの利点

- **競合なし**: 異なるバケットのため設定競合が発生しない
- **独立テスト**: 簡易版を自由にテスト可能
- **段階的学習**: 簡易版で学習後、通常版へ移行可能

### どちらを使うべきか？

#### 簡易版がおすすめの場合
- **学習目的**: Lambda/Bedrockを理解したい
- **プロトタイプ作成**: とりあえず動かしてみたい  
- **コスト重視**: できるだけ安く運用したい
- **シンプルな要約**: テキストファイルの要約だけで十分

#### 通常版がおすすめの場合
- **本格運用**: 業務で継続的に使用する
- **多様なファイル**: Markdown, CSV等も処理したい
- **詳細な管理**: 要約の統計情報も保存したい
- **カスタマイズ**: 要約の長さを文書に応じて調整したい

### 両方を同時に使うメリット・デメリット

**メリット:**
- **比較可能**: 同じファイルで2つの要約方式を比較できる
- **段階的移行**: 簡易版から通常版への移行が簡単
- **バックアップ**: 一方に問題があってももう一方で要約可能

**デメリット:**
- **コスト2倍**: 両方のLambdaが実行されるため処理コストが2倍
- **ストレージ増加**: 要約ファイルが2組保存される
- **管理複雑性**: 2つのシステムを監視する必要

### 運用開始時の推奨手順

1. **まず簡易版から開始** - 理解しやすく設定も簡単
2. **動作確認** - テストファイルで正常処理を確認  
3. **必要に応じて通常版を追加** - より高機能が必要になったら
4. **最終的にどちらか一方に統一** - コスト最適化のため

---

## まとめ

このS3簡易要約システムは、最小限の設定でテキストファイルの自動要約を実現する入門向けのサーバーレスシステムです。通常版と比較して：

**メリット:**
- シンプルな構成で理解しやすい
- 設定項目が少ない
- 低コストで運用可能

**制限事項:**
- .txtファイルのみ対応
- UTF-8エンコーディング固定
- 要約設定のカスタマイズ不可

学習目的や基本的な要約ニーズには十分な機能を提供します。