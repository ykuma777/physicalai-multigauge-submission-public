# 3台のゲージを画像で点検し、異常対象を指し示すロボット

CRANE+ V2の手先カメラで、Gazebo内の既知位置に置いたゲージA・B・Cを順番に撮影します。各観測姿勢への到達を確認してから新しいROS 2画像を取得し、HOG特徴量と学習済み線形SVMで針の見え方を正常／異常に分類します。3台の判定が揃った後、異常と判断したゲージだけをA→B→C順に非接触姿勢で指し示し、homeへ戻ります。すべて正常なら指示せずにhomeへ戻ります。針の準備条件・正解ラベルは対象の準備と実行後の採点専用で、画像推論や指示対象の選択へ渡しません。

これは既知位置・限定照明・合成ゲージを使ったGazebo実験です。実設備の故障診断、実機制御、未知位置の探索、完全な物理接触保証は含みません。追加の日本語画面付き3試行は3/3成功。開発中の中断・失敗5試行も含む全19試行では14/19成功です。詳細は [結果](multigauge/results/finalization_20261027/RESULTS_FINAL.md) を参照してください。

## ファイルの場所

|内容|場所|
|---|---|
|点検・指示の実行コードと設定|`multigauge/`、`multigauge/configs/motion.yaml`|
|カメラ・学習・Gazeboモデル生成|`camera_demo/scripts/`、`camera_demo/ros2_ws/src/camera_inspection/`、`camera_demo/worlds/`|
|学習画像・ラベル・モデル|`camera_demo/data/`、`camera_demo/configs/dataset.yaml`、`camera_demo/artifacts/`|
|ROS軌道publisher|`final_project/ros2_ws/src/inspection_task/`|
|提出候補の説明PDF・詳細仕様書|`docs/`|
|3例の観測画像・実行記録|`multigauge/results/runs/`|
|ソース・モデル・文書のSHA-256|`PUBLIC_SOURCE_MANIFEST.json`|

提出候補の動画はこの公開準備フォルダーには含めていません。元の動画と旧提出物は元の作業場所で保持しています。

## 環境と依存関係

- Windows PowerShell、Docker Desktop、ROS 2 Humble・Ignition Gazebo Fortress・MoveIt・CRANE+ V2を含む講義用イメージ。
- Composeは `airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63` に固定。`pull_policy: never` なので、初回は事前に同digestを取得する必要があります。取得可否をこの公開準備作業では再検証していません。
- 記録された画像AI環境は NumPy 1.24.4、OpenCV 4.5.4。Pythonパッケージには `numpy`、`cv2`、`PyYAML`、ROS側には `rclpy`、`cv_bridge`、`ros_gz_bridge` などが必要です。詳細なROS依存関係は各 `package.xml` を参照してください。
- 固定の専用環境はコンテナ `physicalai-multigauge`、ROS domain 46、Gazebo partition `physicalai_multigauge_46`、VNC `http://localhost:6084/` です。既存環境が同じ名前・ポート・domainを使う場合は起動しないでください。

## cloneから実行まで

公開先が作成された後、Windows PowerShellで次を行います。`<公開リポジトリURL>` は公開後のURLに置き換えてください。既存の同名コンテナを勝手に流用しない起動ガードがあります。

```powershell
git clone <公開リポジトリURL> physicalai-multigauge-submission-public
Set-Location .\physicalai-multigauge-submission-public
docker image inspect airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63
```

`docker image inspect` が失敗し、イメージがない場合のみ次を実行します。公開準備作業ではpullを実行していません。

```powershell
docker pull airobotbook/ros2-desktop-ai-robot-book-humble@sha256:b58ec74c019aacd9ce4818fa25fc5a9e0a1f22f8c9cd1f5260994bf15cd9eb63
```

イメージが用意できたら起動します。起動スクリプトは必要に応じて `inspection_task` と `camera_inspection` をビルドし、ROS・Gazeboの準備を確認します。`http://localhost:6084/` で画面を開きます。

```powershell
powershell -ExecutionPolicy Bypass -File .\multigauge\start.ps1
```

```powershell
# A正常・B異常・C正常
docker exec physicalai-multigauge bash /home/ubuntu/multigauge/run.sh --combination NAN --campaign review --record

# A正常・B異常・C異常
docker exec physicalai-multigauge bash /home/ubuntu/multigauge/run.sh --combination NAA --campaign review --record

# 全台正常
docker exec physicalai-multigauge bash /home/ubuntu/multigauge/run.sh --combination NNN --campaign review --record
```

1回の試行が完了してから次を開始します。`--record` を外せば画面録画を省略できます。`N` は準備した正常例、`A` は準備した異常例を意味します。各試行は新しいrun IDで `multigauge/results/runs/<run_id>/` に保存されます。`observation_A/B/C.png` は実際の画像入力、`inference_A/B/C.json` は画像判定、`run_manifest.json` は到達・動作・結果の対応です。画面の緑／赤橙はAI判定、到達確認と画像一致は処理上の確認であり、正解を示す色ではありません。画面表示と撮影画像・推論入力の対応はhashとACKで監査します。

終了するときは、試行が終わったことを確認してから `powershell -ExecutionPolicy Bypass -File .\multigauge\stop.ps1` を実行します。コンテナ・volumeは削除しません。

## 学習データとモデル

収録した36枚は、Gazeboの手先カメラで撮影した合成ゲージ画像です。角度群単位で学習24枚・未学習検証12枚に分け、同じ角度群を両方に入れません。`camera_demo/data/dataset_manifest.json` に画像hash、ラベル、角度、分割を記録しました。学習側だけをseed `20261001` で拡張し、HOGで針と輪郭の方向を数値化して線形SVMを学習します。保存済みモデルは `camera_demo/artifacts/gauge_hog_svm.yml` です。未学習角度12枚は12/12正解でしたが、この盤面・照明・角度群に限った結果です。

既存モデルを使う標準実行では再学習しません。再学習を試す場合は別のcloneで、コンテナ内から `python3 /home/ubuntu/camera_demo/ros2_ws/src/camera_inspection/camera_inspection/vision_model.py train` を実行します。この操作はモデルとmetadataを上書きするため、元モデルのSHA-256を保存してから行ってください。データ収集コードは `camera_demo/scripts/collect_dataset.py`、針のSDF生成コードは `camera_demo/scripts/target_model.py` です。収集には起動済みのGazeboとROS画像が必要で、現在の判定には同梱済みの学習画像とモデルを使用します。

## 検証範囲と公開準備

新規3試行は、NANでB、NAAでB→C、NNNで指示なしを確認しました。新規9/9画像判定、15/15送信軌道到達、3/3 home復帰です。全19試行では14/19タスク成功、取得・推論できた44/44画像が準備ラベルと一致し、予定57画像に対する正しい判定完了は44/57です。44/44を一般的な分類精度、44/57を分類精度とは呼びません。失敗試行の記録は削除していません。

元の作業ツリーと旧提出物はこの公開準備作業で変更していません。このフォルダーは新規のローカルGit履歴用です。リモートリポジトリの作成、公開、push、Gazeboの再試行は行っていません。第三者による新しいPCでの全行程再現は、今回の静的準備だけでは確認済みとしません。
