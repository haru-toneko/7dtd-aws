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

| steam_branch | ゲームバージョン | Undead Legacy | BepInEx | Assembly patch | serverconfig 注意 |
|---|---|---|---|---|---|
| `alpha20.7` | Alpha 20.7 b1 | **2.6.17 対応** ✅ | **必要** | 不要 | なし |
| `alpha21.2` | Alpha 21.2 | 未対応 | 未検証 | 不要 | 未調査 |
| `public` / `v2.6` | 7DTD 2.6 | **未対応** ❌ | 不要 | **必要** | NetworkingProtocol 他 4 項目を削除 |

**現在の設定:**
```hcl
steam_branch         = "alpha20.7"
apply_assembly_patch = false
use_bepinex          = true
bepinex_multifolderloader_s3 = "s3://7dtd-tmp-transfer-1780123844/BepInEx.MultiFolderLoader.dll"
```

---

## Terraformパラメータ

| 変数 | デフォルト | 説明 |
|---|---|---|
| `steam_branch` | `alpha20.7` | SteamCMD ブランチ |
| `apply_assembly_patch` | `false` | 7DTD 2.6 Linux バグ修正パッチ。alpha20.7 では不要 |
| `use_bepinex` | `false` | BepInEx Doorstop を使用するか。UL 使用時に必要 |
| `bepinex_multifolderloader_s3` | `""` | `BepInEx.MultiFolderLoader.dll` の S3 パス |
| `game_world` | `Navezgane` | ワールド名。7DTD 2.6 では RWG 不可 |
| `game_name` | `Undead-Legacy` | セーブデータフォルダ名 |

---

## ファイル・ディレクトリ構成

```
scripts/
  user_data.sh              ← EC2 初回セットアップ (SteamCMD / BepInEx / Docker / systemd)
  patch_assembly.py         ← Assembly-CSharp.dll バイナリパッチ (7DTD 2.6 専用)
  ULVersionFix.cs           ← ULVersionFix Mod ソース (サーバー・クライアント共通)
  ULVersionFix_ModInfo.xml  ← クライアント配置用 ModInfo
terraform/
  variables.tf / ec2.tf / iam.tf / lambda.tf / ssm.tf ...

# サーバー上 (EBS /data/7dtd/)
server/
  Mods/                          ← UL 等の Mod
  BepInEx/core/                  ← BepInEx 5.4.18.0 DLLs
  BepInEx/patchers/              ← BepInEx.MultiFolderLoader.dll
  doorstop_libs/                 ← libdoorstop_x64.so
  doorstop_config.ini            ← MultiFolderLoader が Mods/ を認識するための必須設定
  startserver_bepinex.sh         ← BepInEx Doorstop 起動ラッパー
  7DaysToDieServer_Data/output_log_*.txt  ← メインログ
config/serverconfig.xml
userdata/Saves/<GAME_WORLD>/<GAME_NAME>/

# クライアント (Windows)
C:\7D2D\Alpha20\Undead_Legacy\Undead_Legacy_Experimental\Mods\ULVersionFix\
  ULVersionFix.dll   ← scripts/ULVersionFix.cs をビルドしたもの
  ModInfo.xml

# S3 アセット
s3://7dtd-tmp-transfer-1780123844/
  BepInEx.MultiFolderLoader.dll  ← EC2 起動時に自動配置
```

---

## BepInEx セットアップ（UL 使用時の必須作業）

### なぜ BepInEx が必要か

UL 2.6.17 は `VehicleCargoCapacity`・`StatWeightMax` 等、バニラの Alpha 20.7 DLL に存在しない enum 値を参照する。
BepInEx Doorstop が起動時に Assembly-CSharp.dll をランタイムでパッチし、これらの enum 値を追加する。

**NG（過去の失敗）:** クライアントの Assembly-CSharp.dll をサーバーにコピー → Windows 専用 Xbox SDK 参照によりクラッシュ

**正解:** BepInEx を使い、UL 内蔵の `Patcher` クラスがランタイムで DLL を修正する

### BepInEx の動作フロー

```
Docker コンテナ起動
  ↓
startserver_bepinex.sh
  LD_PRELOAD=libdl.so.2:libdoorstop_x64.so
  DOORSTOP_INVOKE_DLL_PATH=BepInEx/core/BepInEx.Preloader.dll
  ↓
7DaysToDieServer.x86_64 (Doorstop フック)
  ↓
BepInEx.Preloader → BepInEx.MultiFolderLoader
  ↓
Mods/UndeadLegacy/UndeadLegacy.dll の Patcher クラスを実行
  ↓
Assembly-CSharp に VehicleCargoCapacity 等を追加 (ランタイム)
  ↓
通常ゲーム起動 (XML ロード成功・エンティティタイプ登録済み)
```

### 重要な注意事項

- **startserver.sh 経由は NG**: `startserver.sh` は `/bin/sh` スクリプトであり `LD_PRELOAD` が sh プロセス自体に影響して `undefined symbol: dlopen` でクラッシュする
- **ゲームバイナリ直接 exec が正解**: `startserver_bepinex.sh` は `7DaysToDieServer.x86_64` を直接 `exec` する
- **libdl.so.2 先読みが必要**: `LD_PRELOAD="libdl.so.2:libdoorstop_x64.so"` の順序が重要
- **doorstop_config.ini が必須**: これがないと MultiFolderLoader が `Mods/` を見つけられず 0 パッチャーになる
- **BepInEx.MultiFolderLoader.dll が必須**: これがないと UL 内蔵 Patcher が呼ばれない

### サーバー上での手動セットアップ（terraform 未使用時）

```bash
BEPINEX_VER="5.4.18"
curl -sL "https://github.com/BepInEx/BepInEx/releases/download/v${BEPINEX_VER}/BepInEx_unix_${BEPINEX_VER}.0.zip" \
  -o /tmp/bepinex_unix.zip
python3 -c "import zipfile; zipfile.ZipFile('/tmp/bepinex_unix.zip').extractall('/tmp/bepinex_unix/')"

mkdir -p /data/7dtd/server/BepInEx/core /data/7dtd/server/BepInEx/patchers /data/7dtd/server/doorstop_libs
cp /tmp/bepinex_unix/BepInEx/core/*.dll /data/7dtd/server/BepInEx/core/
cp /tmp/bepinex_unix/doorstop_libs/libdoorstop_x64.so /data/7dtd/server/doorstop_libs/

# MultiFolderLoader.dll (S3から取得 or presigned URL)
URL=$(aws s3 presign s3://7dtd-tmp-transfer-1780123844/BepInEx.MultiFolderLoader.dll --expires-in 600)
curl -s -o /data/7dtd/server/BepInEx/patchers/BepInEx.MultiFolderLoader.dll "$URL"

# doorstop_config.ini
cat > /data/7dtd/server/doorstop_config.ini << 'EOF'
[UnityDoorstop]
enabled=true
targetAssembly=BepInEx/core/BepInEx.Preloader.dll
redirectOutputLog=false
ignoreDisableSwitch=false
dllSearchPathOverride=BepInEx/core

[MultiFolderLoader]
baseDir = Mods/
EOF

# systemd サービスを startserver_bepinex.sh に変更
sed -i 's|/server/startserver\.sh|/server/startserver_bepinex.sh|' /etc/systemd/system/7dtd.service
systemctl daemon-reload && systemctl restart 7dtd
```

---

## ULVersionFix Mod（サーバー + クライアント両方に必要）

### 目的
UL の `get_UndeadLegacyVersion()` が null 参照で失敗する問題を修正。バージョン検証が通らず接続できない問題を解消する。

### パッチ内容 (scripts/ULVersionFix.cs) v12

| セクション | 対象 | 目的 |
|---|---|---|
| #2 | `H_ModVersion.gameVersion` | UL バージョン文字列を設定 |
| #3 | `H_OptionsInfo.get_UndeadLegacyVersion` | Transpiler で null でも key 17 を返す |
| #4 | `GameServerInfo.SetValue` | key 17 = "2.6.17" 注入 (A20.7 では IL Compile Error で失敗するが UL 自身が代行するため実害なし) |
| #5 | `NetPackageIdMapping.Setup` | null の `data (byte[])` を `new byte[0]` で補完 |
| #5 | `NetPackageIdMapping.GetLength` | null フィールドで例外が出ても 0 を返す安全網 |

各セクションは独立した try-catch で囲まれており、1 か所が失敗しても他のパッチは適用される。

### ビルド・デプロイ

```bash
# サーバー上でコンパイル
MANAGED=/data/7dtd/server/7DaysToDieServer_Data/Managed
mcs -target:library -out:/tmp/ULVersionFix.dll \
  -r:${MANAGED}/Assembly-CSharp.dll \
  -r:${MANAGED}/0Harmony.dll \
  -r:${MANAGED}/UnityEngine.CoreModule.dll \
  -r:${MANAGED}/UnityEngine.dll \
  /tmp/ULVersionFix.cs
cp /tmp/ULVersionFix.dll /data/7dtd/server/Mods/ULVersionFix/ULVersionFix.dll
systemctl restart 7dtd
```

### クライアント側インストール

```powershell
$dest = "C:\7D2D\Alpha20\Undead_Legacy\Undead_Legacy_Experimental\Mods\ULVersionFix"
New-Item -ItemType Directory -Force $dest
Copy-Item "C:\tmp\ULVersionFix.dll" "$dest\ULVersionFix.dll" -Force
Copy-Item "C:\tmp\ModInfo.xml"      "$dest\ModInfo.xml"      -Force
# ※ ゲームを閉じてから実行すること (DLL ロック回避)
```

---

## ゲームバージョン変更手順

### terraform.tfvars の変更だけで OK (EC2 再作成時)

```hcl
# UL + BepInEx 構成 (alpha20.7)
steam_branch         = "alpha20.7"
apply_assembly_patch = false
use_bepinex          = true
bepinex_multifolderloader_s3 = "s3://7dtd-tmp-transfer-1780123844/BepInEx.MultiFolderLoader.dll"
game_world           = "Navezgane"
game_name            = "Undead-Legacy"

# 7DTD 2.6 バニラ構成
# steam_branch         = "public"
# apply_assembly_patch = true
# use_bepinex          = false
```

### 利用可能な Steam ブランチ

`alpha20.7` / `alpha21.2` / `v2.0` / `v2.3` / `v2.4` / `v2.5` / `v2.6` / `public`

### サーバー上で直接バージョン変更

```bash
systemctl stop 7dtd
cp -r /data/7dtd/server/Mods /tmp/mods_backup
/opt/steamcmd/steamcmd.sh +@sSteamCmdForcePlatformType linux \
  +force_install_dir /data/7dtd/server +login anonymous \
  "+app_update 294420 -beta alpha20.7 validate" +quit
mkdir -p /data/7dtd/server/Mods
cp -r /tmp/mods_backup/* /data/7dtd/server/Mods/
systemctl start 7dtd
```

---

## Mod 追加手順

```bash
systemctl stop 7dtd
# ZIP を展開して /data/7dtd/server/Mods/<ModName>/ に配置
systemctl start 7dtd
```

- **BepInEx 依存 mod の追加**: `BepInEx/plugins/` に DLL を配置すれば BepInEx が自動ロード
- **7DTD 標準 Mod**: `Mods/<ModName>/` に `ModInfo.xml` + DLL を配置
- **クライアント側も同 Mod が必要な場合**: 対象クライアント全員に配布必要

---

## デバッグ手順

```bash
# インスタンス確認
aws ec2 describe-instances --filters "Name=tag:Name,Values=*7dtd*" \
  --query "Reservations[*].Instances[*].{ID:InstanceId,IP:PublicIpAddress,State:State.Name}" --output table

# 最新ログ確認
aws ssm send-command --instance-ids "<ID>" --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["ls -t /data/7dtd/server/7DaysToDieServer_Data/output_log_*.txt | head -1 | xargs tail -50"]}'

# よく使う grep パターン
grep "StartGame done"            # 起動完了確認
grep "BepInEx"                   # BepInEx 動作確認
grep "Patching .Assembly-CSharp" # UL プリパッチャー確認
grep "Loading.*preloader patcher" # MultiFolderLoader確認 (0なら doorstop_config.ini 要確認)
grep "ULVersionFix"              # ULVersionFix Mod 確認
grep -E "RequestToEnterGame|NCSimple|EXC" # 接続エラー確認
grep "PlayerSpawn"               # スポーン確認
```

---

## クラッシュパターン早見表

| ログキーワード | 原因 | 対策 |
|---|---|---|
| `Startup aborted` | serverconfig.xml に不正プロパティ | バージョン別プロパティを確認 |
| `[EOS] Created RFS Request` で停止 | Assembly patch 不足 (2.6) | `apply_assembly_patch = true` |
| `Loading 0 preloader patchers` | `doorstop_config.ini` が存在しない | 上記手順で作成 |
| `Patching [Assembly-CSharp]` なし | MultiFolderLoader.dll がない | S3 から取得して配置 |
| `XML loader: items.xml failed` + `VehicleCargoCapacity` | BepInEx 未設定 | `use_bepinex = true` + 上記セットアップ |
| `EntityFactory: unknown type` | entityclasses.xml 未ロード (上記の連鎖) | 同上 |
| `GetLength() NullReference` | NetPackageIdMapping null エントリ | ULVersionFix の NpmSetupPostfix を確認 |
| `#4 failed: IL Compile Error` | SetValuePostfix が A20.7 で動かない | 無視してよい (UL が代行) |
| `undefined symbol: dlopen` | startserver.sh 経由で LD_PRELOAD した | startserver_bepinex.sh で直接 exec すること |
| ゲームバイナリ Segfault | Assembly-CSharp.dll をクライアントからコピーした | NG。BepInEx でランタイムパッチが正解 |
| ロード画面 20 分以上ハング | entityclasses.xml 未ロード → スポーン失敗 | BepInEx + ULVersionFix をセットアップ |
| `write: null entry skipped` | write() スキップ → カウント不一致 | NpmWritePrefix を削除し NpmSetupPostfix を使う |
| Timeout (7 秒) | プロトコル不一致 | game バージョンと UL バージョンを揃える |

---

## インフラ運用メモ

- **インスタンス ID:** 起動のたびに変わる可能性あり → `describe-instances` で確認
- **EBS:** ゲームデータは EBS に永続化。インスタンス再作成後も同 AZ にアタッチすればデータ保持
- **セーブデータ:** `/data/7dtd/userdata/Saves/<GAME_WORLD>/<GAME_NAME>/` — バージョン変更時は互換性なし
- **Telnet:** 127.0.0.1:8081 (`lp` コマンドでプレイヤー数確認)
- **Mods の validate 消滅対策:** バージョン変更前に必ず Mods を `/tmp/mods_backup` にバックアップ
