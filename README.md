# 7 Days to Die AWS サーバー構築ガイド

Discord から起動/停止でき、無人時に自動停止する 7DTD 専用サーバーを AWS 上に構築する手順書。

---

## アーキテクチャ概要

```
Discord
  │  /start /stop /status /settings /set
  ▼
API Gateway (HTTP API)
  │
  ▼
Lambda: discord_bot        ← Ed25519署名検証 → deferred response (3秒以内に返答)
  │ 非同期invoke
  ▼
Lambda: discord_worker     ← EC2起動/停止/状態取得・SSM Run Commandで設定書き換え → Discordにフォローアップ送信
  
Lambda: auto_stop          ← EventBridge 5分毎に起動
  │ SSM RunCommand
  ▼
EC2 (m7i-flex.large)       ← Docker + カスタムイメージ (ubuntu:20.04 + libgcc-s1 + ca-certificates)
  │
  └─ EBS 30GB              ← ゲームデータ永続化 (インスタンス停止後も保持)
```

### コスト目安 (ap-northeast-1 / 月100時間プレイ想定)

| リソース | 単価 | 月額目安 |
|---|---|---|
| EC2 m7i-flex.large (On-Demand) | $0.1274/h | ~$12.7 |
| EBS gp3 30GB (OS) | $0.096/GB/月 | $1.9 |
| EBS gp3 30GB (ゲームデータ) | $0.096/GB/月 | $2.9 |
| Lambda / API GW | 無料枠内 | ~$0 |
| SSM / CloudWatch | 無料枠内 | ~$0 |

**停止中は EC2 課金なし。EBS のみ課金 (~$4.8/月固定)。**

> **このアカウントについて:** Free Tier 対象インスタンスのみ起動可能な制限があります。
> ap-northeast-1 で利用できる x86_64 インスタンスは `m7i-flex.large` (8GB RAM) と `c7i-flex.large` (4GB RAM) です。
> 7DTD には最低 4GB、快適には 8GB 必要なため `m7i-flex.large` を使用しています。

---

## 前提条件

### ローカル環境 (WSL)

```bash
# 確認コマンド
terraform version    # 1.5.0 以上
aws --version        # AWS CLI v2
python3 --version    # 3.8 以上
pip3 --version
```

インストールされていない場合:

```bash
# Terraform
sudo apt-get update && sudo apt-get install -y gnupg software-properties-common
wget -O- https://apt.releases.hashicorp.com/gpg | gpg --dearmor | sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install terraform

# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip /tmp/awscliv2.zip -d /tmp
sudo /tmp/aws/install
```

### AWS アカウント

- IAM ユーザーまたはロールに以下の権限が必要:
  - `ec2:*`, `iam:*`, `lambda:*`, `apigateway:*`, `ssm:*`, `cloudwatch:*`, `logs:*`, `events:*`
- 推奨: AdministratorAccess (個人用 AWS アカウントの場合)

```bash
# AWS 認証情報の設定
aws configure
# AWS Access Key ID: ...
# AWS Secret Access Key: ...
# Default region name: ap-northeast-1
# Default output format: json

# 確認
aws sts get-caller-identity
```

---

## Step 1: Discord Application の作成

### 1-1. Discord Developer Portal でアプリ作成

1. [Discord Developer Portal](https://discord.com/developers/applications) を開く
2. **New Application** → 名前を入力 (例: `7DTD Server Bot`) → Create
3. 左メニュー **General Information** から以下をメモ:
   - **Application ID**
   - **Public Key**

### 1-2. Bot トークン取得

1. 左メニュー **Bot** をクリック
2. **Reset Token** → トークンをコピーしてメモ
3. **Privileged Gateway Intents** は全て OFF でよい

### 1-3. Bot をサーバーに招待

1. 左メニュー **OAuth2** → **URL Generator**
2. Scopes: `bot`, `applications.commands` を選択
3. Bot Permissions: `Send Messages` を選択
4. 生成された URL をブラウザで開き、目的のサーバーに招待

---

## Step 2: スラッシュコマンド登録

`scripts/register_commands.py` を使ってコマンドを登録する。

```bash
cd ~/7dtd-aws

export DISCORD_APP_ID="Step1でメモしたApplication ID"
export DISCORD_BOT_TOKEN="Step1-2でメモしたBot Token"

# ギルドコマンドとして登録（即時反映・推奨）
# GUILD_ID: Discordで 開発者モード ON → サーバーアイコン右クリック → 「サーバーIDをコピー」
python3 scripts/register_commands.py --guild YOUR_GUILD_ID

# 登録内容の確認
python3 scripts/register_commands.py --list --guild YOUR_GUILD_ID
```

> グローバルコマンドとして登録する場合は `--guild` を省略（反映まで最大1時間かかる）。

登録されるコマンド:

| コマンド | 説明 |
|---|---|
| `/start [オプション]` | サーバー起動。24個のオプションで設定を上書き可能 |
| `/set gameplay [オプション]` | 起動中にXP・ダメージ・ルート・昼夜設定を変更 (7DTD再起動) |
| `/set zombies [オプション]` | 起動中にゾンビ・スポーン設定を変更 (7DTD再起動) |
| `/set server [オプション]` | 起動中にエアドロップ・視野距離などを変更 (7DTD再起動) |
| `/settings` | 現在のゲーム設定を一覧表示 (サーバー起動中のみ) |
| `/stop` | サーバーを停止 |
| `/status` | 起動状態とIPを確認 |
| `/mod list` | インストール済みModの一覧を表示 |
| `/mod add url:<URL> name:<名前>` | ModをZIP URLからインストール (7DTD再起動) |
| `/mod remove name:<名前>` | 指定したModを削除 (7DTD再起動) |
| `/mod toggle name:<名前>` | 指定したModの有効/無効を切り替え (7DTD再起動) |
| `/mod reset` | 全Modを削除 (7DTD再起動) |

---

## Step 3: Lambda パッケージのビルド

```bash
cd ~/7dtd-aws

bash build.sh
```

完了すると `.build/` 配下に以下が生成される:

```
.build/
├── discord_bot/      ← index.py + PyNaCl ライブラリ
├── discord_worker/   ← index.py
└── auto_stop/        ← index.py
```

---

## Step 4: Terraform 変数ファイルの作成

```bash
cd ~/7dtd-aws/terraform

cat > terraform.tfvars << 'EOF'
# ── AWS ──────────────────────────────────────────────────────────────────────
aws_region    = "ap-northeast-1"

# ── EC2 ──────────────────────────────────────────────────────────────────────
instance_type       = "m7i-flex.large"  # このアカウントで使えるFree Tier対象 (8GB RAM)
use_spot_instance   = false             # このアカウントはSpot非対応のためfalse固定
ebs_size_gb         = 30

# ── ゲームサーバー設定 ────────────────────────────────────────────────────────
server_name     = "Friends 7DTD Server"
server_password = "ゲーム接続パスワード"
max_players     = 6
game_world      = "Pregen08k01"     # Pregen06k01/Pregen06k02/Pregen08k01/Pregen08k02/Navezgane
                                    # ※ "RWG" (ランダム生成) は 7DTD 2.6 で rwgmixer バグがあり使用不可

# ── 自動停止 ──────────────────────────────────────────────────────────────────
auto_stop_idle_minutes = 30         # 0人が続いたら30分後に自動停止

# ── テレネット (内部管理用) ────────────────────────────────────────────────────
telnet_password = "telnet用パスワード（ランダムな文字列推奨）"

# ── Discord ───────────────────────────────────────────────────────────────────
discord_public_key       = "Step1でメモしたPublic Key"
discord_application_id   = "Step1でメモしたApplication ID"
discord_bot_token        = "Step1-2でメモしたBot Token"

# コマンドを使えるDiscordユーザーIDの一覧 (空リストで全員許可)
# ユーザーIDは Discordで 開発者モード ON → ユーザー右クリック → IDをコピー
allowed_discord_user_ids = ["あなたのDiscordユーザーID"]
EOF
```

> **セキュリティ注意:** `terraform.tfvars` は `.gitignore` に追加してGitにコミットしないこと。

---

## Step 5: Terraform デプロイ

```bash
cd ~/7dtd-aws/terraform

# 初期化 (初回のみ)
terraform init

# 変更内容の確認
terraform plan

# デプロイ実行
terraform apply
```

`Apply complete!` が表示されたら、出力値をメモする:

```
Outputs:

discord_webhook_url = "https://xxxxxx.execute-api.ap-northeast-1.amazonaws.com/discord"
instance_id         = "i-0xxxxxxxxxxxxxxxxx"
game_data_volume_id = "vol-0xxxxxxxxxxxxxxxxx"
```

---

## Step 6: Discord に Webhook URL を設定

1. [Discord Developer Portal](https://discord.com/developers/applications) を開く
2. 作成したアプリ → **General Information**
3. **Interactions Endpoint URL** に `discord_webhook_url` の値を貼り付け
4. **Save Changes** をクリック → Discord が疎通確認を行い ✅ と表示されれば成功

---

## Step 7: EC2 の初期停止 (初回のみ)

Terraform は EC2 を起動した状態で作成する。Discord から起動できるよう、初回のみ手動で停止する。

> **重要:** terraform apply 直後に停止してはいけない。  
> EC2 初回起動時に user_data.sh が自動実行され、7DTD サーバー本体（約 16GB）を SteamCMD でダウンロードする。  
> **完了前に停止すると download が中断され、再起動しても再開されない**（cloud-init は初回のみ実行）。  
> セットアップ完了まで **30〜50 分** かかる（Docker・libc6-i386 のインストール + SteamCMD bootstrap + 7DTD ダウンロード）。

### 7-1. セットアップ完了を確認する

```bash
INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値

# セットアップログの末尾を確認（「セットアップ完了」が出たら OK）
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["tail -3 /var/log/7dtd-setup.log", "systemctl is-active 7dtd || true"]' \
  --region ap-northeast-1 \
  --query "Command.CommandId" \
  --output text)

sleep 5

aws ssm get-command-invocation \
  --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region ap-northeast-1 \
  --query "StandardOutputContent" \
  --output text
```

出力例（完了時）:
```
[Tue May 19 06:45:12 UTC 2026] セットアップ完了
active
```

まだ実行中の場合は数分待ってから再実行する。`active` が出たら次の手順へ。

### 7-2. インスタンスを停止する

```bash
# INSTANCE_ID は 7-1 で設定済みの変数をそのまま使う
aws ec2 stop-instances \
  --instance-ids "$INSTANCE_ID" \
  --region ap-northeast-1

# 停止完了を待つ
aws ec2 wait instance-stopped \
  --instance-ids "$INSTANCE_ID" \
  --region ap-northeast-1

echo "停止完了"
```

---

## 動作確認

Discord の任意のテキストチャンネルで以下を実行:

| コマンド | 動作 |
|---|---|
| `/start` | サーバーを起動。IPアドレスを返答 |
| `/start difficulty:3 xp_multiplier:200` | 難易度Warrior・XP2倍で起動 |
| `/set gameplay xp_multiplier:150 loot_abundance:200` | 起動中のサーバーの設定を即時変更 (7DTD再起動) |
| `/set zombies zombie_night:4 blood_moon_count:16` | 夜ゾンビNightmare・BM16体に変更 |
| `/help` | 設定可能な全オプションを一覧表示 |
| `/settings` | 現在の全ゲーム設定を表示 |
| `/stop` | サーバーを停止 |
| `/status` | 現在の状態とIPを返答 |
| `/mod list` | インストール済みModを一覧表示 |
| `/mod add url:https://... name:SMXCore` | ModをURLからインストール (7DTD再起動) |
| `/mod toggle name:SMXCore` | Modの有効/無効を切り替え (7DTD再起動) |
| `/mod remove name:SMXCore` | Modを削除 (7DTD再起動) |
| `/mod reset` | 全Modをまとめて削除 (7DTD再起動) |

> `/set` と `/mod` はサーバー起動中 (EC2 running) のみ使用可能。停止中は `/start` で起動してから実行する。

### ゲームへの接続方法

7 Days to Die 起動 → **マルチプレイ** → **IPで接続**

```
IP:   (Discord の /status または /start で表示されたIPアドレス)
Port: 26900
```

---

## 運用・管理

### サーバーログの確認

```bash
# SSM Session Manager でEC2に接続 (SSHキー不要)
INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --region ap-northeast-1

# 接続後
sudo journalctl -u 7dtd -f
```

### Lambda ログの確認

```bash
# discord_bot のログ
aws logs tail /aws/lambda/7dtd-discord-bot --follow --region ap-northeast-1

# auto_stop のログ
aws logs tail /aws/lambda/7dtd-auto-stop --follow --region ap-northeast-1
```

### Mod の管理

Mod ファイルは EBS 上の `/data/7dtd/server/Mods/` に永続化される。EC2 を再起動しても消えない。

#### インストール可能な Mod の形式

- **対応:** ZIP 直リンク (7daystodiemods.com、GitHub Releases 等)
- **非対応:** Nexus Mods (ログイン必須のため自動ダウンロード不可)
  - Nexus の場合は手動で ZIP をダウンロードし、`aws ssm start-session` で EC2 に入って配置する

ZIP の内部構造は自動判定される。ZIPを展開した中から `ModInfo.xml` を含むフォルダを検出してインストールするため、親フォルダの有無に関わらず動作する。

#### Mod が `Assembly-CSharp.dll` を含む場合

DLL 改変系 Mod をインストールすると `/mod add` が自動的に `patch_assembly.py` を再適用する。
7DTD 2.6 の Unity バグ修正パッチが維持されるため、通常は追加操作不要。

#### Mod の無効化と有効化

```
/mod toggle name:ModName
```

`Mods/ModName/` ↔ `Mods.disabled/ModName/` のフォルダ移動で切り替える。
ファイルは削除されないため、再度 toggle で復元できる。

#### 全 Mod をまとめてリセット

```
/mod reset
```

有効・無効問わず全 Mod を削除する。バニラ状態に戻す際に使用する。

### ゲームデータのバックアップ

```bash
# セーブデータは EBS に保存されているため、スナップショットで手動バックアップ可能
VOLUME_ID="vol-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値 (game_data_volume_id)

aws ec2 create-snapshot \
  --volume-id "$VOLUME_ID" \
  --description "7dtd-backup-$(date +%Y%m%d)" \
  --region ap-northeast-1
```

### インスタンスタイプの変更

EC2 が停止していないと変更できないため、先に `/stop` コマンドで停止する。

[terraform/terraform.tfvars](terraform/terraform.tfvars) の `instance_type` を変更:

```hcl
instance_type = "c7i-flex.large"  # 変更例 (4GB RAM、1〜2人向け)
```

```bash
terraform apply
```

---

## インスタンスタイプの選択肢 (このアカウント向け)

このアカウントは **Free Tier 対象インスタンスのみ**起動可能です。7DTD で使える選択肢:

| インスタンス | vCPU | RAM | 単価 | 用途 |
|---|---|---|---|---|
| `m7i-flex.large` | 2 | 8GB | $0.1274/h | **推奨。2〜6人で快適** |
| `c7i-flex.large` | 2 | 4GB | $0.0850/h | 1〜2人のみ。やや不安定 |

`terraform.tfvars` の `instance_type` を変更して `terraform apply` で切り替えられます。

> **Spot インスタンスについて:** このアカウントでは `use_spot_instance = true` は動作しません。`false` 固定で使用してください。

---

## トラブルシューティング

### Discord コマンドが反応しない

1. Discord Developer Portal の **Interactions Endpoint URL** が正しく設定されているか確認
2. `terraform output discord_webhook_url` で URL を再確認
3. Lambda ログを確認:
   ```bash
   aws logs tail /aws/lambda/7dtd-discord-bot --region ap-northeast-1
   ```

### `/start` 後にゲームに接続できない

- サーバー起動後、**ゲームエンジンの初期化に 3〜5 分かかる**。`/start` の返答後しばらく待ってから接続する
- プリジェネレートマップ使用時は世界生成なし。初回でも 5 分程度で接続可能

### `7dtd.service could not be found` / サービスが存在しない

terraform apply 直後に EC2 を停止した場合、user_data.sh のセットアップが完了していない可能性がある。

```bash
# セットアップログで状況を確認
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["tail -5 /var/log/7dtd-setup.log", "ls /etc/systemd/system/7dtd.service 2>/dev/null || echo NOT_FOUND"]' \
  --region ap-northeast-1 \
  --query "Command.CommandId" --output text)
sleep 5
aws ssm get-command-invocation --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" --region ap-northeast-1 \
  --query "StandardOutputContent" --output text
```

`NOT_FOUND` が出た場合 → **セットアップが中断されている**。対処法:

1. EC2 を停止・起動し直す（user_data.sh は再実行されない）
2. 代わりに SSM で手動セットアップを再実行する:

```bash
# 手動セットアップ再実行（インスタンスが起動中であること）
# libc6-i386: steamcmd の linux32/steamcmd は 32bit ELF のため必須
# SteamCMD bootstrap → +quit で自己更新 → 7DTD ダウンロード → Assembly パッチ → サービス起動
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=[
    "dpkg --add-architecture i386 && apt-get update -y -q && apt-get install -y libc6-i386",
    "rm -rf /opt/steamcmd && mkdir -p /opt/steamcmd",
    "curl -sqL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar zxf - -C /opt/steamcmd",
    "/opt/steamcmd/steamcmd.sh +quit 2>/dev/null || true",
    "mkdir -p /data/7dtd/server",
    "/opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux +force_install_dir /data/7dtd/server +login anonymous +app_update 294420 validate +quit",
    "pip3 install dnfile -q",
    "python3 /opt/7dtd/patch_assembly.py",
    "systemctl daemon-reload && systemctl enable 7dtd && systemctl start 7dtd",
    "systemctl status 7dtd --no-pager"
  ]' \
  --timeout-seconds 3600 \
  --region ap-northeast-1 \
  --query "Command.CommandId" --output text)

echo "CommandId: $CMD_ID"
echo "20〜40分後に以下で結果確認:"
echo "aws ssm get-command-invocation --command-id $CMD_ID --instance-id $INSTANCE_ID --region ap-northeast-1 --query StandardOutputContent --output text"
```

> **注意:** SteamCMD は `+quit` 実行後でも "Missing configuration" で失敗することがある。  
> その場合は最後の `+app_update` コマンドをもう一度実行すると成功する。

### サーバーが起動直後にクラッシュする / ログが少ない行数で止まる

7DTD 2.6 は Linux 専用サーバーで Unity MonoBehaviour の初期化順序バグがある。
`user_data.sh` が自動的に `Assembly-CSharp.dll` へバイナリパッチを適用するが、
DLL が更新 (ゲームアップデート) されるとパッチが無効になる。

```bash
# パッチ再適用
INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"

CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["systemctl stop 7dtd", "python3 /opt/7dtd/patch_assembly.py", "systemctl start 7dtd"]' \
  --region ap-northeast-1 \
  --query "Command.CommandId" --output text)

sleep 20
aws ssm get-command-invocation --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" --region ap-northeast-1 \
  --query "StandardOutputContent" --output text
```

**パッチ対象:** `GameOptionsManager.ValidateFoV` / `GameOptionsManager.ValidateFoV3P`  
(GamePrefs 未初期化時のクラッシュを防ぐため noop に差し替え)

---

### 自動停止が効かない

1. auto_stop Lambda のログを確認:
   ```bash
   aws logs tail /aws/lambda/7dtd-auto-stop --region ap-northeast-1
   ```
2. EC2 上でプレイヤーチェックスクリプトを手動実行:
   ```bash
   INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値

   CMD_ID=$(aws ssm send-command \
     --instance-ids "$INSTANCE_ID" \
     --document-name AWS-RunShellScript \
     --parameters 'commands=["python3 /opt/7dtd/check_players.py"]' \
     --region ap-northeast-1 \
     --query "Command.CommandId" \
     --output text)

   sleep 5

   aws ssm get-command-invocation \
     --command-id "$CMD_ID" \
     --instance-id "$INSTANCE_ID" \
     --region ap-northeast-1 \
     --query '[Status,StandardOutputContent,StandardErrorContent]' \
     --output text
   ```

### EC2 への直接接続 (デバッグ用)

SSH キー不要で SSM Session Manager から接続できる:

```bash
INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --region ap-northeast-1
```

---

## インフラの削除

全リソースを削除する場合:

```bash
INSTANCE_ID="i-0xxxxxxxxxxxxxxxxx"  # Step5 の出力値

# まず EC2 を停止
aws ec2 stop-instances --instance-ids "$INSTANCE_ID" --region ap-northeast-1
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID" --region ap-northeast-1

cd ~/7dtd-aws/terraform
terraform destroy
```

> **注意:** `terraform destroy` を実行すると EBS (ゲームデータ) も削除される。セーブデータを残したい場合は事前にスナップショットを取ること。

---

## ファイル構成

```
7dtd-aws/
├── README.md                        ← このファイル
├── build.sh                         ← Lambda パッケージビルドスクリプト
├── terraform/
│   ├── main.tf                      ← プロバイダー設定
│   ├── variables.tf                 ← 変数定義
│   ├── terraform.tfvars             ← 【要作成】実際の値 (Gitにコミット禁止)
│   ├── outputs.tf                   ← 出力値 (Webhook URL等)
│   ├── data.tf                      ← AMI取得・Lambdaアーカイブ
│   ├── ec2.tf                       ← EC2 Launch Template・EBS
│   ├── iam.tf                       ← EC2/Lambda IAMロール
│   ├── security_groups.tf           ← ゲームポート開放
│   ├── ssm.tf                       ← SSM Parameter Store (パスワード等)
│   ├── lambda.tf                    ← 3つの Lambda 関数
│   ├── api_gateway.tf               ← HTTP API Gateway
│   └── cloudwatch.tf                ← EventBridge・CloudWatch Alarm
├── scripts/
│   ├── user_data.sh                 ← EC2 起動時スクリプト (Docker + 7DTD + Assembly パッチ)
│   ├── patch_assembly.py            ← 7DTD 2.6 Unity バグ修正パッチ (user_data.sh から自動実行)
│   └── register_commands.py         ← Discord スラッシュコマンド登録スクリプト
└── lambda/
    ├── discord_bot/index.py         ← 署名検証・deferred response
    ├── discord_worker/index.py      ← start/stop/status/settings/set/mod 処理・SSM設定書き換え
    └── auto_stop/index.py           ← プレイヤー確認・自動停止
```
