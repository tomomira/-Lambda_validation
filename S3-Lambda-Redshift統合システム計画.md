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
- **ハンドラー**: `lambda_function.lambda_handler` （ファイル名: `lambda_function.py`, 関数名: `lambda_handler`）
- **外部ライブラリ**: `redshift_connector` （デプロイパッケージに含める必要あり）
- **タイムアウト**: 5分
- **メモリ**: 512MB
- **環境変数**:
  - `REDSHIFT_HOST` (クラスターのエンドポイント)
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

本IAMロールは、Lambda関数が以下の3つの主要なアクションを実行することを許可します。
1. **S3バケットへのアクセス**: `s3:GetObject`権限により、トリガーとなったファイルをS3バケットから読み取ります。
2. **RedshiftでのSQL実行**: `redshift-data:*`権限セットにより、Redshift Data APIを介してデータの挿入やクエリの実行を行います。
3. **CloudWatchへのログ記録**: `logs:*`権限により、関数の実行ログをCloudWatch Logsに書き込み、デバッグや監視を可能にします。

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
- **重複処理防止機能**: 同一のS3オブジェクトキーを持つデータが既にテーブルに存在しないか、`INSERT`前に`SELECT`文で確認する。

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

### C. 格納データサンプル
本システムでは、S3にアップロードされたテキストファイルがデータソースとなります。具体的なサンプルデータは本計画書には含まれていませんが、以下に処理の流れの例を示します。

#### 1. S3にアップロードされるファイル例
- **バケット**: `sqldata-2025-01`
- **オブジェクトキー**: `sample-report.txt`
- **ファイル内容**:
```text
これはテストレポートです。
S3からRedshiftへのデータ連携を確認します。
```

#### 2. Redshiftに挿入されるレコード例 (`document_ingestion`テーブル)
上記のファイルがアップロードされると、以下のようなレコードがテーブルに挿入されます。

| カラム名 | 格納される値（例） |
| :--- | :--- |
| `id` | `1` (自動採番) |
| `file_name` | `'sample-report.txt'` |
| `file_path` | `'s3://sqldata-2025-01/sample-report.txt'` |
| `file_size_bytes`| `70` (概算) |
| `file_type` | `'txt'` |
| `content_text` | `'これはテストレポートです。\nS3からRedshiftへのデータ連携を確認します。'` |
| `s3_bucket` | `'sqldata-2025-01'` |
| `s3_object_key`| `'sample-report.txt'` |
| `processed_at` | `(処理時刻)` |

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
- **テストファイルのアップロード**: 以下のパターンを準備し、S3にアップロードする。
  - **正常系**:
    - 通常のテキストファイル (.txt)
    - UTF-8, Shift-JISなど、複数のエンコーディング形式のファイル
    - 空のファイル
  - **異常系**:
    - テキスト以外のファイル形式 (画像など)
    - RedshiftのVARCHAR最大長を超える可能性のある巨大なファイル
- Lambda関数の実行確認 (CloudWatch Logsでログを確認)
- Redshiftへのデータ挿入確認 (クエリエディタで`SELECT`文を実行)

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

### D. Text to SQL 実装詳細イメージ
より具体的な実装は、以下のアーキテクチャと処理フローを想定する。

#### 1. アーキテクチャ概要
```
[WebUI (Frontend)]
      │ (1. 自然言語入力)
      ↓
[API Gateway] <=> [Lambda: SQL-Generator]
      │                 │ (2. プロンプト生成)
      │                 ↓
      │            [Bedrock (Claude)]
      │                 │ (3. SQL生成)
      │                 ↓
      │       [Lambda: SQL-Executor]
      │                 │ (4. SQL実行)
      │                 ↓
      │            [Amazon Redshift]
      │                 │ (5. クエリ結果)
      └─────────────────┤ (6. 整形して返却)
                        ↓
                  [ユーザー]
```

#### 2. 詳細な処理フロー
1. **ユーザー入力**: ユーザーがWebUIから「先週アップロードされたエラー報告を一覧にして」といった自然言語で分析を要求する。

2. **プロンプト生成 (Lambda)**: `SQL-Generator` Lambda関数が、ユーザーの入力に加えて以下の情報を組み合わせ、Bedrockへの最適なプロンプトを動的に構築する。
   - **テーブルスキーマ**: `document_ingestion`テーブルのカラム名、データ型、カラム内容の説明などをプロンプトに含め、AIが構造を理解できるようにする。
   - **動的パラメータの解決**: 「昨日」「今週」「先月」といった相対的な日付表現を、Redshiftの関数（例: `GETDATE()`, `DATE_TRUNC`）を用いて解釈する方法を指示する。これにより、日付が変わっても利用可能なクエリ（キュレートクエリ）が生成される。
   - **Few-shotサンプル**: `(入力例, 出力SQL例)` のペアを数個プロンプトに含めることで、AIの出力精度を向上させる。
   - **ガードレール**: `DROP`, `DELETE`などの破壊的クエリや、個人情報に関わるような不適切なクエリを生成しないよう制約を設ける。

3. **SQL生成 (Bedrock)**: Bedrock (Claude)は、受け取ったプロンプトに基づいてRedshiftで実行可能なSQLクエリを生成する。
   - **入力**: `「先週アップロードされたエラー報告を一覧にして」`
   - **生成SQL例**: 
     ```sql
     SELECT file_name, s3_event_time, error_message
     FROM document_ingestion
     WHERE processing_status = 'ERROR'
       AND s3_event_time >= DATE_TRUNC('week', GETDATE() - interval '1 week')
       AND s3_event_time < DATE_TRUNC('week', GETDATE())
     ORDER BY s3_event_time DESC;
     ```

4. **SQL実行と結果返却**: 生成されたSQLを `SQL-Executor` LambdaがRedshiftで実行し、結果を取得する。必要に応じて、結果をさらにBedrockに渡して要約させたり、チャート用のデータ形式に整形したりした後、WebUIに返却する。

この設計により、ユーザーはSQLを意識することなく、日々変わる状況に応じた柔軟なデータ分析を自然言語で実行できるようになる。

### E. 補足: Knowledge BaseとText to SQLの役割分担と実現方法
本計画には2つの主要なAI拡張機能（Knowledge BaseとText to SQL）が含まれており、それぞれ役割が異なります。ここではその違いと、キュレートクエリの実現方法について明確化します。

#### 1. Text to SQLの実現アプローチ：動的生成方式
本システムで採用するのは、事前に「日本語の質問」と「SQL」の固定ペアを大量に登録しておく従来の方法ではありません。AIがその場でSQLを**動的に生成**するアプローチです。

**手順の概要:**
1.  **ユーザーの質問**: 「先週エラーになったファイルは何件？」
2.  **プロンプトの動的構築 (Lambda)**: Lambda関数が、ユーザーの質問に加えて以下の「AIへの指示書（プロンプト）」をリアルタイムで組み立てます。
    - **コンテキスト**: Redshiftのテーブル定義（カラム名、データ型など）。
    - **ルール**: 「"先週"は `DATE_TRUNC('week', GETDATE() - interval '1 week')` を使って表現する」といった変換ルール。
    - **手本**: 質の高いSQLを生成させるための、少数の質問とSQLのペア例（Few-shot learning）。
3.  **SQLの動的生成 (Bedrock)**: Bedrockは、受け取ったプロンプトを解釈し、状況に最も適したSQLをその場で生成します。
4.  **実行と結果**: 生成されたSQLをRedshiftで実行し、結果を返します。

このアプローチにより、未知の質問や、「昨日」「今月」といった日々変わる条件にも柔軟に対応できる、実質的なキュレートクエリ体験が実現されます。

#### 2. 機能の役割分担
`Knowledge Base`と`Text to SQL`は、回答の元となるデータソースが異なります。

- **AWS Knowledge Base (RAG)**
    - **目的**: S3にある**文書の中身（非構造化データ）**に関する質問に答える。
    - **質問例**: 「`report-A.txt`に書かれている問題点を要約して。」
    - **データソース**: S3のテキストファイル群。

- **Text to SQL**
    - **目的**: Redshiftテーブルの**データ（構造化データ）**を集計・検索する。
    - **質問例**: 「ステータスが'SUCCESS'のファイルは、全部で何件ありますか？」
    - **データソース**: Redshiftの`document_ingestion`テーブル。

このように、2つの機能を適切に使い分けることで、ユーザーは多角的なデータ分析を自然言語だけで実行できるようになります。

### F. 補足: Text to SQLの実現アプローチ比較と本計画の方針
Text to SQLを実現するには、主に2つのアプローチが存在します。本計画では、それぞれの特徴を理解し、両者を組み合わせた**ハイブリッドアプローチ**を採用することで、柔軟性と信頼性を両立させます。

#### アプローチ1：事前登録リスト方式（静的なキュレーション）
従来から「キュレートクエリ」と呼ばれてきた堅実な方法で、Amazon Bedrock Agentsにもシステムの信頼性を高めるための主要機能として組み込まれています。開発者が事前に「質問テンプレート」と「実行すべきSQL」のペアをリストとしてシステムに設定します。

- **位置づけ**: **ガバナンスと信頼性の担保**。AI(LLM)の使用を補完する。
- **例えるなら**: **パラメータ変更可能な報告書テンプレート**。決まった型の報告書を、誰でも安全かつ正確に作成できる。
- **特徴**:
    - **テンプレート型**: 質問文の一部を`{支店名}`のようにパラメータ化することで、「A支店の売上」「B支店の売上」といった柔軟な問い合わせに対応できる。
- **メリット**:
    - **精度・パフォーマンスの保証**: 専門家が最適化したSQLの実行を保証し、回答の信頼性と速度を担保する。
    - **セキュリティとガバナンス**: 「実行を許可するSQLのホワイトリスト」として機能し、機密データへの意図しないアクセスや危険な操作を完全に防ぐ。
    - **利用者の拡大**: SQLを書けないユーザーでも、テンプレートのパラメータを変えるだけで安全にデータを引き出せるようになる。
- **デメリット**:
    - **柔軟性の限界**: テンプレートに合致しない、全く新しい非定型な質問には対応できない。

#### アプローチ2：AIによる動的生成方式（動的なキュレーション）
本計画で採用する先進的な方法です。Lambda関数が司令塔となり、LLM（Bedrock）の能力を最大限に引き出すためのプロンプトエンジニアリングを駆使します。

- **位置づけ**: **探索的・非定型な分析への対応**。
- **例えるなら**: **優秀なデータアナリスト**。曖昧な依頼からでも意図を汲み取り、最適な分析をその場で実行してくれる。
- **メリット**:
    - **非常に高い柔軟性**: 未知の質問や多様な言い回しにも、文脈を理解して柔軟に対応できる。
    - **優れたユーザー体験**: ユーザーはAIアシスタントと対話するように、自然な言葉で分析を依頼できる。
- **デメリット**:
    - **予測不可能性**: AIが意図を誤解し、不正確なSQLを生成するリスク（ハルシネーション）がある。
    - **セキュリティ対策が必須**: `DELETE`等の危険なSQLを生成させないためのガードレール設計が重要。
    - **コスト**: AIモデルの利用料が発生する。

#### まとめと本計画における採用方針
本計画では、どちらか一方に偏るのではなく、両者の長所を組み合わせた**ハイブリッドアプローチ**を採用します。

| 項目 | アプローチ1：事前登録（キュレートクエリ） | アプローチ2：AIによる動的生成 |
| :--- | :--- | :--- |
| **主な役割** | **ガバナンス、信頼性保証、定型分析** | **柔軟性、探索的分析** |
| **ユースケース** | 高頻度で実行される定点観測クエリ<br>セキュリティ要件が特に厳しいクエリ | 非定型でアドホックな分析クエリ<br>対話形式でのデータ探索 |

**実行フローの想定:**
1.  ユーザーからの質問を、まず**キュレートクエリのテンプレートに合致するか判定**する。
2.  **合致した場合**: 対応する最適化済みSQLを安全に実行する（アプローチ1）。
3.  **合致しない場合**: AIによる動的SQL生成のフローに処理を移す（アプローチ2）。

この方針により、頻繁に使われる重要なクエリの**信頼性・セキュリティ・コスト効率**を確保しつつ、非定型な分析要求にも応えられる**高い柔軟性**を両立した、実用的なデータ分析プラットフォームを構築します。

#### 補足：「高性能」の二つの側面
Text-to-SQLにおける「高性能」は、二つの側面で捉えることができます。

*   **汎用性と柔軟性の性能**: 生成AIの能力を最大限に活かす**アプローチ2（動的生成）**は、未知の質問にも対応できるため、この側面で非常に高性能です。
*   **実行速度と信頼性の性能**: 専門家が事前に最適化したSQLを登録する**アプローチ1（キュレートクエリ）**は、SQLの実行パフォーマンスや回答の正確性において、極めて高性能です。

本計画のハイブリッドアプローチは、これら二種類の「高性能」をユースケースに応じて適切に使い分けることで、システム全体の価値を最大化する戦略です。

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

---

## 12. データ確認方法

Redshiftにデータが正しく挿入されたかを確認するための代表的な方法を以下に示します。どの方法でも、基本的にはSQLクエリを実行してデータを閲覧します。

### A. 基本的な確認用SQLクエリ
```sql
-- 最近挿入された10件のレコードを確認
SELECT *
FROM document_ingestion
ORDER BY processed_at DESC
LIMIT 10;
```