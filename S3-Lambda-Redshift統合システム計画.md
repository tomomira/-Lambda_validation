# S3-Lambda-Redshift統合システム計画

## 1. プロジェクト概要

### 目的
S3バケット（`sqldata-2025-01`）にテキストファイルが格納されたイベントをトリガーとして、その内容をRedshiftに自動インサートするシステムを構築する。将来的にはAWS Bedrock Knowledge BaseとText to SQLクエリを活用したキュレート分析機能への拡張を目指す。

### 主要技術スタック
- **イベント処理**: S3 Event Notifications
- **コンピューティング**: AWS Lambda (Python 3.12)
- **データウェアハウス**: Amazon Redshift
- **認証**: IAM Role-based Authentication
- **将来拡張**: AWS Bedrock, Knowledge Base, OpenSearch Serverless

---

## 2. システムアーキテクチャ

### 基本構成
```
[S3バケット: sqldata-2025-01]
  └─ テキストファイル(.txt, .csv, .json)
      ↓ (ObjectCreated Event)
[Lambda関数: s3-redshift-loader]
  ├─ IAM認証でRedshiftアクセス
  ├─ テキスト内容解析・構造化
  └─ Redshift INSERTクエリ実行
      ↓
[Redshift Cluster]
  └─ テーブル: document_ingestion
```

### データフロー
1. **S3イベント検知**: ObjectCreated時にLambda自動実行
2. **ファイル内容取得**: S3からテキスト内容を読み込み
3. **データ構造化**: ファイル名、内容、メタデータを構造化
4. **Redshift接続**: IAM認証でクラスター接続
5. **データ挿入**: 構造化データをINSERT
6. **ログ記録**: CloudWatch Logsに処理結果を記録

---

## 3. 必要なAWSリソース

### A. S3バケット
- **バケット名**: `sqldata-2025-01`
- **イベント通知**: ObjectCreatedイベントでLambdaトリガー
- **権限**: Lambda実行ロールにGetObject権限

### B. Lambda関数
- **関数名**: `s3-redshift-loader`
- **ランタイム**: Python 3.12
- **タイムアウト**: 5分
- **メモリ**: 512MB
- **環境変数**:
  - `REDSHIFT_CLUSTER_IDENTIFIER`
  - `REDSHIFT_DATABASE_NAME`
  - `REDSHIFT_USER` (IAMユーザー名)

### C. Redshift
- **クラスター**: 既存または新規作成
- **データベース**: 指定データベース
- **認証**: IAMベース認証
- **VPC設定**: Lambdaからアクセス可能な設定

### D. IAMロール設計
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::sqldata-2025-01/*"
    },
    {
      "Effect": "Allow", 
      "Action": [
        "redshift-data:ExecuteStatement",
        "redshift-data:DescribeStatement",
        "redshift-data:GetStatementResult"
      ],
      "Resource": "*"
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

---

## 4. Lambda関数の設計

### A. 主要処理フロー
1. **S3イベント解析**: バケット名・オブジェクトキー取得
2. **ファイル検証**: テキストファイル判定、最小サイズ確認
3. **内容取得**: エンコーディング自動判定（UTF-8, Shift-JIS, CP932）
4. **メタデータ抽出**: ファイルサイズ、作成日時、ファイル形式
5. **Redshift接続**: IAM認証を使用したRedshift Data API実行
6. **INSERT実行**: 構造化データの挿入

### B. エラーハンドリング
- S3アクセス失敗時の再試行機能
- Redshift接続失敗時のログ記録とエラー通知
- 大容量ファイル処理時のメモリ制限対応
- 重複処理防止機能

### C. 監視・ログ機能
- CloudWatch Logsへの詳細な処理ログ出力
- 処理時間、レコード件数の記録
- エラー発生時の詳細エラー情報記録

---

## 5. Redshiftテーブル設計

### A. メインテーブル: `document_ingestion`
```sql
CREATE TABLE document_ingestion (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    file_name VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size_bytes BIGINT,
    file_type VARCHAR(50),
    content_text VARCHAR(65535),  -- Redshift VARCHAR最大長
    content_encoding VARCHAR(20),
    s3_bucket VARCHAR(100) NOT NULL,
    s3_object_key VARCHAR(1000) NOT NULL,
    s3_event_time TIMESTAMP,
    processed_at TIMESTAMP DEFAULT GETDATE(),
    processing_status VARCHAR(20) DEFAULT 'SUCCESS',
    error_message VARCHAR(1000),
    lambda_request_id VARCHAR(100)
)
DISTKEY(s3_bucket)
SORTKEY(processed_at, s3_object_key);
```

### B. 将来拡張用テーブル: `document_analysis`
```sql
CREATE TABLE document_analysis (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    document_id BIGINT REFERENCES document_ingestion(id),
    analysis_type VARCHAR(50), -- 'summary', 'keywords', 'sentiment' 
    analysis_result JSON,
    bedrock_model_id VARCHAR(100),
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT GETDATE()
)
DISTKEY(analysis_type)
SORTKEY(created_at, document_id);
```

---

## 6. 実装フェーズ計画

### Phase 1: 基本システム構築（今回実装）

#### 1.1 Redshiftクラスターの準備
- 既存クラスター確認または新規作成
- IAM認証設定の有効化
- テーブル作成（`document_ingestion`）

#### 1.2 Lambda関数の作成
- IAM実行ロールの作成と権限付与
- Python 3.12環境でのコード実装
- 環境変数設定とテスト

#### 1.3 S3イベント通知設定
- バケット`sqldata-2025-01`の作成
- ObjectCreatedイベントとLambdaの連携

#### 1.4 動作確認とテスト
- テストファイルのアップロード
- Lambda関数の実行確認
- Redshiftへのデータ挿入確認

### Phase 2以降: 拡張機能（将来実装）

#### 2.1 Bedrock Knowledge Base統合
- OpenSearch Serverlessクラスター構築
- 文書のベクトル化とインデックス作成
- RAG（Retrieval-Augmented Generation）による高度な分析

#### 2.2 Text to SQLインターフェース
- 自然言語入力のWebUI作成
- Claude Sonnetによる高精度なSQL生成
- リアルタイムクエリ実行とビジュアル化

---

## 7. Bedrock Knowledge Base拡張への準備計画

### A. 段階的拡張ロードマップ
1. **フェーズ1**: 基本的なS3→Redshift連携確立（今回）
2. **フェーズ2**: Bedrock Knowledge Base作成・文書インデックス化
3. **フェーズ3**: Text to SQLクエリ生成機能の追加
4. **フェーズ4**: 自然言語クエリによるキュレート分析機能

### B. Knowledge Base連携準備項目
- **ベクトルストレージ**: OpenSearch Serverlessクラスター準備
- **エンベディング**: Titan Embeddings G1 Textモデル使用予定
- **文書管理**: S3バケット内の文書を自動インデックス化
- **メタデータ管理**: Redshiftの文書情報と連携

### C. Text to SQL機能設計
- **入力**: 自然言語でのデータ分析要求
- **処理**: Bedrock(Claude)によるSQL生成
- **実行**: 生成されたSQLをRedshiftで実行
- **出力**: 分析結果とビジュアル化データの提供

---

## 8. 実装優先順位

### 高優先度（Phase 1）
1. S3バケットの作成と設定
2. Redshiftクラスターの準備とテーブル作成
3. Lambda関数の実装と動作確認
4. IAM権限の設定と動作テスト

### 中優先度（Phase 2）
1. Bedrock Knowledge Baseの設定
2. 文書のベクトル化とインデックス作成
3. 基本的なRAG機能の実装

### 低優先度（Phase 3-4）
1. Text to SQL機能の開発
2. WebUIインターフェースの作成
3. 高度な分析機能とビジュアル化

---

## 9. 技術的考慮事項

### セキュリティ
- IAMロールの最小権限設定
- S3バケットポリシーによるアクセス制御
- VPC内でのRedshift通信（必要に応じて）

### パフォーマンス
- Lambda関数のコールドスタート対策
- Redshiftクエリの最適化
- 大容量ファイル処理時のメモリ効率

### コスト最適化
- Lambda実行時間の最小化
- Redshiftクラスターの適切なサイジング
- S3ストレージクラスの最適化

### 監視・運用
- CloudWatch Logsによる詳細ログ記録
- CloudWatch Alarmsによる異常検知
- エラー通知とアラート機能

---

## 10. 成功基準

### Phase 1完了時
- [ ] S3にファイルアップロード時のLambda自動実行
- [ ] テキストファイル内容のRedshift正常挿入
- [ ] エラー発生時の適切なログ記録
- [ ] 処理時間5分以内での完了

### Phase 2完了時
- [ ] Knowledge Baseへの文書自動インデックス化
- [ ] ベクトル検索による関連文書取得
- [ ] RAG機能による高度な文書分析

### 最終完成時
- [ ] 自然言語による直感的なデータ分析
- [ ] Text to SQLによる柔軟なクエリ生成
- [ ] WebUIによる使いやすいインターフェース

---

## 11. 参考資料とベースファイル

本計画は以下の既存検証結果を基に策定：
- `S3-Lambda連携検証手順.md` - 基本的なS3→Lambda連携ノウハウ
- `S3自動要約システム_Bedrock-Lambda構成.md` - Bedrock統合の実装経験

これらの知見を活用し、段階的に高度なAI駆動データ分析プラットフォームを構築する。