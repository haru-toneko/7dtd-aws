# 7DTD AWS サーバー — Claude Code リファレンス

## アーキテクチャ概要

```
Discord ─► API Gateway ─► Lambda(discord_bot) ─► Lambda(discord_worker)
                                                         │
                                            SSM SendCommand / EC2 Start/Stop
                                                         │
EventBridge(5分毎) ─► Lambda(auto_stop) ──────────► EC2 (m7i-flex.large)
                                                         │
                                                   Docker コンテナ
                                                   (ubuntu:20.04 + libgcc-s1)
                                                         │
                                                   EBS 30GB /data/7dtd/
                                                   ├── server/   ← ゲームファイル
                                                   ├── config/   ← serverconfig.xml
                                                   └── userdata/ ← セーブデータ
```

**Lambda関数:** discord_bot / discord_worker / auto_stop / game_ready_notifier

**ポート:** 26900 TCP/UDP (ゲーム), 8081 TCP (Telnet/RCON)

---

## ゲームバージョン互換性マトリクス

| steam_branch | ゲームバージョン | Undead Legacy | Assembly patch | serverconfig 注意 |
|---|---|---|---|---|
| `alpha20.7` | Alpha 20.7 b1 | **2.6.17 対応** ✅ | 不要 | なし |
| `alpha21.2` | Alpha 21.2 | 未対応 | 不要 (未検証) | 未調査 |
| `public` / `v2.6` | 7DTD 2.6 | **未対応** ❌ (2.7 開発中) | **必要** | NetworkingProtocol 他 4 項目を削除 |

**現在の設定:** `steam_branch = "alpha20.7"`, `apply_assembly_patch = false`

---

## Terraformパラメータ

| 変数 | デフォルト | 説明 |
|---|---|---|
| `steam_branch` | `alpha20.7` | SteamCMD ブランチ |
| `apply_assembly_patch` | `false` | 7DTD 2.6 Linux バグ修正パッチ。alpha20.7 では不要 |
| `game_world` | `Navezgane` | ワールド名。7DTD 2.6 では RWG 不可 |
| `game_name` | `Undead-Legacy` | セーブデータフォルダ名 |

---

## ファイル・ディレクトリ構成

```
scripts/
  user_data.sh         ← EC2 初回セットアップ (SteamCMD / Docker / systemd)
  patch_assembly.py    ← Assembly-CSharp.dll バイナリパッチ (7DTD 2.6 専用)
  ULVersionFix.cs      ← ULVersionFix Mod ソース (サーバー・クライアント共通)
terraform/
  variables.tf         ← 全パラメータ定義
  ec2.tf               ← Launch Template / EBS / user_data
lambda/
  discord_bot/
  discord_worker/
  auto_stop/
  game_ready_notifier/

# サーバー上 (EBS /data/7dtd/)
server/Mods/                                ← Mod 一覧
config/serverconfig.xml
userdata/Saves/<GAME_WORLD>/<GAME_NAME>/    ← セーブデータ
server/7DaysToDieServer_Data/output_log_*.txt  ← メインログ

# クライアント (Windows)
C:\7D2D\Alpha20\Undead_Legacy\Undead_Legacy_Experimental\Mods\ULVersionFix\
  ULVersionFix.dll   ← scripts/ULVersionFix.cs をビルドしたもの
  ModInfo.xml
```

---

## ULVersionFix Mod

### 目的
Undead Legacy 2.6.17 を Alpha 20.7 専用サーバーで動かすための Harmony パッチ Mod。
**サーバーとクライアント両方に同じ DLL をインストールする必要がある。**

### パッチ内容 (scripts/ULVersionFix.cs)

| # | 対象 | 方法 | 目的 |
|---|---|---|---|
| 1 | `H_ModVersion.gameVersion` | フィールド直接書き換え | UL バージョン文字列を設定 |
| 2 | `H_OptionsInfo.get_UndeadLegacyVersion` | Transpiler | `fUndeadLegacyVersion` が null でも key 17 を返す |
| 3 | `GameServerInfo.SetValue` | Postfix | key 17 = "2.6.17" をサーバー情報に注入 (Alpha 20.7 では IL Compile Error で失敗するが、UL 自身が patch 済みの getter 経由で SetValue を呼ぶため実害なし) |
| 4 | `NetPackageIdMapping.Setup` | Postfix | null の `data` (byte[]) を `new byte[0]` で補完。null のまま GetLength() を呼ぶと NullReferenceException でシリアライズ全体がクラッシュする |
| 5 | `NetPackageIdMapping.GetLength` | Prefix | null フィールドが残存した場合の安全網。0 を返して taskSerialize のクラッシュを防ぐ |

### ビルド・デプロイ手順

#### サーバー側

```bash
# 1. ソースをサーバーに転送してコンパイル
MANAGED=/data/7dtd/server/7DaysToDieServer_Data/Managed
mcs -target:library -out:/tmp/ULVersionFix.dll \
  -r:${MANAGED}/Assembly-CSharp.dll \
  -r:${MANAGED}/0Harmony.dll \
  -r:${MANAGED}/UnityEngine.CoreModule.dll \
  -r:${MANAGED}/UnityEngine.dll \
  /tmp/ULVersionFix.cs

# 2. デプロイ
mkdir -p /data/7dtd/server/Mods/ULVersionFix
cp /tmp/ULVersionFix.dll /data/7dtd/server/Mods/ULVersionFix/ULVersionFix.dll

# 3. サービス再起動
systemctl restart 7dtd
```

PowerShell から SSM 経由でデプロイする場合 (ローカルの .cs ファイルを使う):

```powershell
# C:\tmp\ssm_deploy.json を作成してデプロイ (過去セッション参照)
$cs = Get-Content 'scripts\ULVersionFix.cs' -Raw -Encoding UTF8
$b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($cs))
# → SSM コマンドに python3 -c "import base64; open(...).write(base64.b64decode('$b64'))" を渡す
# → mcs でコンパイル → cp でデプロイ → systemctl restart 7dtd
```

#### クライアント側 (Windows)

1. サーバーから DLL を取得:
```bash
# サーバー上で
base64 -w 0 /data/7dtd/server/Mods/ULVersionFix/ULVersionFix.dll
```

2. ローカルに保存して配置:
```powershell
# Base64 → ファイル変換
[System.IO.File]::WriteAllBytes('C:\tmp\ULVersionFix.dll', [Convert]::FromBase64String($b64))

# クライアントの Mods フォルダに配置
$dest = "C:\7D2D\Alpha20\Undead_Legacy\Undead_Legacy_Experimental\Mods\ULVersionFix"
New-Item -ItemType Directory -Force $dest
Copy-Item 'C:\tmp\ULVersionFix.dll' "$dest\ULVersionFix.dll" -Force
# ModInfo.xml も同フォルダに配置 (scripts/ フォルダ参照)
```

**注意:** ゲームが起動中は DLL がロックされるため、ゲームを閉じてから上書きする。

---

## ゲームバージョン変更手順

### Terraform 経由 (EC2 再作成時)

```hcl
# terraform.tfvars
steam_branch         = "alpha20.7"   # or "public" for 2.6
apply_assembly_patch = false          # true if steam_branch = "public"
game_world           = "Navezgane"
game_name            = "Undead-Legacy"
```

### サーバー上で直接変更する場合

```bash
systemctl stop 7dtd

# Mods をバックアップ (validate で消える可能性あり)
cp -r /data/7dtd/server/Mods /tmp/mods_backup

# バージョン変更ダウンロード
/opt/steamcmd/steamcmd.sh \
  +@sSteamCmdForcePlatformType linux \
  +force_install_dir /data/7dtd/server \
  +login anonymous \
  "+app_update 294420 -beta alpha20.7 validate" \
  +quit

# Mods 復元
mkdir -p /data/7dtd/server/Mods
cp -r /tmp/mods_backup/* /data/7dtd/server/Mods/

systemctl start 7dtd
```

**利用可能な Steam ブランチ:** alpha20.7 / alpha21.2 / v2.0 / v2.3 / v2.4 / v2.5 / v2.6 / public

---

## Mod 追加手順

```bash
# サーバー上で
systemctl stop 7dtd
# ZIP を展開して /data/7dtd/server/Mods/<ModName>/ に配置
systemctl start 7dtd
```

ULVersionFix を含む Mod を追加した場合は、**クライアントにも同 Mod が必要か確認すること。**

---

## 既知の問題と対策

### 7DTD 2.6 Linux MonoBehaviour バグ
- **症状:** `[EOS] Created RFS Request` で永久ハング
- **対策:** `scripts/patch_assembly.py` で `ValidateFoV` / `ValidateFoV3P` を noop 化
- **適用条件:** `apply_assembly_patch = true` かつ `steam_branch = "public"/"v2.6"` のみ
- **注意:** `GUIWindowManager.Awake` は絶対に noop にしない

### Undead Legacy + 7DTD 2.6 非互換
- **症状:** クライアントクラッシュ / バージョンミスマッチ
- **原因:** UL 2.6.17 は Alpha 20.7 専用。`NetPackageIdMapping.Setup(string, byte[])` に null が渡される
- **対策:** `steam_branch = "alpha20.7"` に変更 + ULVersionFix Mod を導入

### ULVersionFix #4 (GameServerInfo.SetValue) が失敗する
- **症状:** ログに `[ULVersionFix] #4 failed: IL Compile Error`
- **影響なし:** UL 自身が `get_UndeadLegacyVersion()` (transpiler 修正済み) 経由で SetValue を呼ぶため、key 17 = "2.6.17" は正しく設定される
- **対策不要**

### NetPackageIdMapping null エントリ
- **症状:** `GetLength() NullReferenceException` → クライアントハング
- **原因:** UL のカスタムネットパッケージ登録が専用サーバーで失敗し、`data (byte[])` が null になる
- **対策:** ULVersionFix の `NpmSetupPostfix` が `new byte[0]` で補完

### RWG クラッシュ (7DTD 2.6 のみ)
- **症状:** 世界生成中に永久ハング
- **対策:** `game_world = "Navezgane"` 等のプリジェンマップを使用

---

## デバッグ手順

```bash
# 現在のインスタンス ID 確認
aws ec2 describe-instances --filters "Name=tag:Name,Values=*7dtd*" \
  --query "Reservations[*].Instances[*].{ID:InstanceId,IP:PublicIpAddress,State:State.Name}" --output table

# 最新ログ確認
aws ssm send-command \
  --instance-ids "<INSTANCE_ID>" \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["ls -t /data/7dtd/server/7DaysToDieServer_Data/output_log_*.txt | head -1 | xargs tail -50"]}'

# よく使う grep パターン
grep "StartGame done"             # 起動完了確認
grep "ULVersionFix"               # パッチ適用確認
grep -E "RequestToEnterGame|NCSimple|EXC|ERR"  # 接続エラー確認
grep "PlayerSpawn"                # プレイヤースポーン確認
```

### クラッシュパターン早見表

| ログキーワード | 原因 | 対策 |
|---|---|---|
| `Startup aborted` | serverconfig.xml に不正プロパティ | バージョン別の除外プロパティを確認 |
| `[EOS] Created RFS Request` で停止 | Assembly patch 不足 (2.6) | `apply_assembly_patch = true` |
| `GetLength() NullReference` | UL パッケージ登録失敗 | ULVersionFix の NpmSetupPostfix を確認 |
| `#4 failed: IL Compile Error` | SetValuePostfix が A20.7 で使えない | 無視してよい (実害なし) |
| `write: null entry skipped` | write() スキップ → カウント不一致 | NpmWritePrefix を削除し NpmSetupPostfix を使う |
| client Timeout (7 秒) | プロトコル / バージョン不一致 | ゲームバージョンと UL バージョンを揃える |

---

## インフラ運用メモ

- **インスタンス ID:** 起動のたびに変わる可能性あり。上記コマンドで確認
- **EBS:** ゲームデータは EBS に永続化。インスタンス再作成後も EBS を同 AZ にアタッチすればデータ保持
- **セーブデータ:** `/data/7dtd/userdata/Saves/<GAME_WORLD>/<GAME_NAME>/` — バージョン変更時は互換性なし
- **Telnet:** 127.0.0.1:8081 (`lp` コマンドでプレイヤー数確認)
- **Mods の validate 消滅対策:** バージョン変更時は必ず Mods を `/tmp/mods_backup` にバックアップしてから SteamCMD を実行
