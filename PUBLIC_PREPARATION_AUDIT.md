# 公開準備の確認記録（2026-10-28）

## 選定範囲

- 元の作業場所は `C:\pr\physicalai-multigauge-work`、採用した保存点は `ec611ac214c9505300d5b8913ad102dbc780bc2b`。この公開候補は別フォルダーに確認済みファイルを複製し、元のGit履歴を取り込まない。
- `multigauge/` の起動・準備・画像判定・軌道・表示・評価コードと `configs/motion.yaml`、Compose、`camera_demo/` のカメラ・学習・SDF生成コード、world、学習画像36枚、モデルとmetadata、`inspection_task` ROSパッケージを含む。
- 改訂説明PDFと実装確認済み仕様書は `docs/`、新規3試行の観測画像・推論結果・run manifest、および失敗を含む全19試行の評価は `multigauge/results/` に保存。
- 提出候補の動画、再現ZIP、旧版、生成されたbuild/install/log、個別試行の大きな画面録画は含めない。動画は元の `final_20261027_v2` に保持。

## 静的検証

|項目|結果|
|---|---|
|元ファイルと公開候補のプログラム67ファイルのSHA-256|全件一致。動作・推論コードを変更していない。|
|Python 49ファイルの構文|PASS（UTF-8 BOMを考慮してAST解析）|
|ROS package XML 2件、設定YAML 5件|構文・読み込みPASS|
|学習画像36枚|`dataset_manifest.json` 記録のSHA-256と全件一致|
|学習済みモデルとdataset manifest|モデルmetadata記録のSHA-256と一致|
|説明PDF・仕様書|各3ページ。元の改訂版からバイト列を複製。|
|ローカルPCでの新しい画像推論|未確認。ホストのOpenCV 5.0.0には `HOGDescriptor` がなく、記録された実行環境（OpenCV 4.5.4）と異なる。|
|新しいDocker環境でのbuild・Gazebo試行|今回は未実施。元の成功runと失敗記録を再実行したとは主張しない。|

元のモデルmetadataに記録された未学習角度画像の評価は12/12正解。新たなホスト推論の成功結果ではない。公開用READMEの再現手順も、新規PCでの全行程を今回検証済みと扱わない。

## 個人情報・ライセンス

- テキスト、コード、設定、JSON、PDF本文・metadataを調べ、個人の氏名・所属・連絡先、認証鍵やトークン、個人ホームパスは検出しなかった。資料の `ykumakuma777` と由来を示す `ykuma777` は提出・GitHub上の匿名IDであり、実名として扱わない。
- メール形式の文字列は、ROS package manifestとsetup metadataの計4ファイルにある非個人の例示アドレスだけ。ユーザーがこの例外を許可した。新しいGitコミットの著者・コミッターにも匿名IDと同じ非個人の例示アドレスを使う。
- Apache-2.0の `LICENSE` と出典・外部依存関係の `NOTICE.md` は保持した。講義用CRANE+ V2、ROS 2、MoveIt、Gazebo、Dockerイメージ本体は同梱せず、権利を主張しない。

## リポジトリ名と未確認事項

候補名 `physicalai-multigauge-submission-public` は、接続済みGitHubの公開検索と閲覧可能なリポジトリ一覧では見つからなかった。ただし、閲覧権限外の同名リポジトリまで不存在と証明したわけではない。リモート作成前に再確認する。

この準備ではDockerイメージのpull・build、Gazebo実行、リモート作成、push、公開、投稿、提出差し替えを行っていない。元の作業場所と既提出物は保持した。
