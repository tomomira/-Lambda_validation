# S3-Lambda連携の検証手順

## 1. 検証の目的

AWS S3バケットにファイルがアップロードされたイベントを検知し、自動的にLambda関数をトリガーして実行する基本的な連携を検証します。

具体的には、S3バケット `homedata-2025` にアップロードされたテキストファイルの内容をLambda関数が読み取り、その内容をCloudWatch Logsに出力することで、一連の動作が正しく設定されていることを確認することを目的とします。

## 2. 全体構成

シンプルなサーバーレスイベント駆動アーキテクチャを構成します。

- **S3 (イベントソース)**: `homedata-2025` バケットにファイルが作成されるとイベントが発生します。
- **Lambda (コンピューティング)**: S3からのイベントを受けてPythonコードを実行し、ファイル内容を処理します。
- **CloudWatch Logs (ログ記録)**: Lambda関数の実行ログと、処理したファイルの内容を記録・表示します。

## 3. 必要な設定の概要

この検証では、以下の3つの主要な設定を行います。詳細な手順はこの後のセクションで解説します。

1.  **IAMロールの作成**: Lambda関数に、S3バケットの読み取りとCloudWatch Logsへの書き込みを許可する権限（役割）を設定します。
2.  **Lambda関数の作成**: S3から受け取ったファイル情報を処理するPythonコードを準備し、上記IAMロールを割り当てます。
3.  **S3トリガーの設定**: `homedata-2025` バケットでのファイル作成をきっかけに、作成したLambda関数が自動実行されるように連携設定を行います。

## 4. 設定手順

### 手順1: Lambda実行用のIAMロール作成

Lambda関数が他のAWSサービス（S3, CloudWatch Logs）にアクセスするための権限（役割）を作成します。

1. IAMコンソールで「ロール」>「ロールを作成」を選択します。
2. 信頼されたエンティティとして「AWSのサービス」、ユースケースとして「Lambda」を選択します。
3. 必要な許可ポリシーとして `AmazonS3ReadOnlyAccess` （S3からファイルを読み取る権限）をアタッチします。
4. **【重要】 CloudWatch Logsへの書き込み権限の追加**
   - 通常は `AWSLambdaBasicExecutionRole` という管理ポリシーをアタッチします。
   - **もしクォータ上限エラーが出る場合:** 管理ポリシーの数が上限に達しているため、以下の**インラインポリシー**を作成して代替します。
     1. ロールの「許可を追加」>「インラインポリシーを作成」を選択します。
     2. JSONタブに以下のコードを貼り付け、`LambdaLoggingPolicy` などの名前を付けて保存します。
   ```json
   {
       "Version": "2012-10-17",
       "Statement": [
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
5. ロールに `lambda-s3-read-role` などの分かりやすい名前を付けて作成を完了します。

### 手順2: Lambda関数の作成とコード実装

1. Lambdaコンソールで「関数の作成」を選択します。
2. 以下の通り設定します。
   - **関数名**: `s3-file-reader` （任意）
   - **ランタイム**: `Python 3.12`
   - **実行ロール**: 「既存のロールを使用する」を選択し、手順1で作成したIAMロールを指定します。
3. 作成後、「コード」タブに以下のPythonコードを貼り付け、「Deploy」ボタンで保存・反映します。

```python
import json
import boto3
import urllib.parse

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # S3イベントからバケット名とオブジェクトキーを取得
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    
    try:
        # S3からオブジェクトを取得
        response = s3.get_object(Bucket=bucket, Key=key)
        
        # ファイル内容を読み込み、UTF-8でデコード
        file_content = response['Body'].read().decode('utf-8')
        
        # CloudWatch Logsにファイル内容を出力
        print("----- File Content -----")
        print(file_content)
        print("------------------------")
        
        return {
            'statusCode': 200,
            'body': json.dumps(f"Successfully processed {key} from bucket {bucket}.")
        }
    except Exception as e:
        print(e)
        raise e
```

### 手順3: S3トリガーの設定

Lambda関数を起動するきっかけ（トリガー）としてS3バケットを設定します。

1. 作成したLambda関数のデザイナー画面で「トリガーを追加」を選択します。
2. ソースとして `S3` を選択します。
3. **バケット**: `homedata-2025` を指定します。
4. **イベントタイプ**: `すべてのオブジェクト作成イベント` を選択します。
5. 設定を保存します。

## 5. 動作確認

1. S3コンソールで `homedata-2025` バケットを開きます。
2. `test.txt` という名前で、任意のテキスト（例: `S3 Lambda test`）を記述したファイルを作成し、アップロードします。
3. Lambda関数の「モニタリング」タブ > 「CloudWatchログを表示」をクリックします。
4. 最新のログストリームを開き、`test.txt` に記述した内容が `----- File Content -----` の後に出力されていることを確認します。

## 6. トラブルシューティング：発生した問題と解決策

### 問題1: ポリシーのアタッチ時に「クォータを超えています」と表示される

- **原因**: IAMユーザーまたはロールにアタッチできる**管理ポリシー**の数（最大10個）の上限に達しています。
- **解決策**: **インラインポリシー**を利用します。管理ポリシーとは別枠で管理されるため、数の上限を回避して権限を追加できます。手順1で示したように、必要な権限をJSON形式で直接ロールに埋め込みます。

### 問題2: CloudWatchログ表示時に「アクセス権限が見つかりません」と表示される

- **原因**: AWSコンソールを操作している**IAMユーザー**に、CloudWatch Logsを閲覧する権限がありません。これはLambdaの実行ロールの問題ではありません。
- **解決策**: コンソール操作中のIAMユーザーに、CloudWatch Logsの閲覧権限を付与します。`CloudWatchReadOnlyAccess` ポリシーをアタッチするか、同様にクォータ上限に達している場合は、以下のインラインポリシーをユーザーに追加します。

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams",
                "logs:GetLogEvents",
                "logs:FilterLogEvents"
            ],
            "Resource": "*"
        }
    ]
}
```
このポリシーは、AWS Lambda関数がCloudWatch Logsにログを出力するために必要な最小権限を記述したものです。[1][2]

## ポリシー内容の意味

- **logs:CreateLogGroup**  
  新しいロググループを作成する権限です。Lambda関数実行時に、対応するロググループ（例: /aws/lambda/関数名）がなければ自動生成されます。

- **logs:CreateLogStream**  
  ロググループ内に新しくログストリームを作成する権限です。Lambda関数が実行されるたびにログストリームが作成されます。

- **logs:PutLogEvents**  
  作成したログストリームに対してログ（イベント）を書き込む権限です。これにより、実際のログデータがCloudWatch Logsに記録されます。

- **"Resource": "arn:aws:logs:*:*:*"**  
  すべてのリージョン・すべてのアカウント・すべてのロググループ＆ログストリームに対する権限を許可します。

## まとめ

このポリシーをLambda実行ロールにアタッチすることで、「CloudWatch Logsへのログ出力（グループ・ストリーム作成、イベント書き込み）」が問題なく行えます。これはAWS公式の「AWSLambdaBasicExecutionRole」が付与する内容と同等です。
