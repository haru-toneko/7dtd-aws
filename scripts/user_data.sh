#!/bin/bash
set -euo pipefail

# Terraform templatefile変数
SERVER_NAME="${server_name}"
MAX_PLAYERS="${max_players}"
GAME_WORLD="${game_world}"
AWS_REGION="${aws_region}"

LOG=/var/log/7dtd-setup.log
exec > >(tee -a "$LOG") 2>&1
echo "[$(date)] Starting 7DTD server setup (Docker)..."

# ─── 基本パッケージ ───────────────────────────────────────────────────────────
apt-get update -y
# libc6-i386: steamcmd_linux.tar.gz の linux32/steamcmd は 32bit ELF のため必須
dpkg --add-architecture i386
apt-get update -y
apt-get install -y ca-certificates curl awscli netcat-openbsd libc6-i386

# ─── Docker インストール ──────────────────────────────────────────────────────
echo "[INFO] Dockerをインストール..."
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io
systemctl enable docker
systemctl start docker

# ─── EBSボリューム マウント ───────────────────────────────────────────────────
EBS_DEV=""
for dev in /dev/xvdf /dev/nvme1n1; do
  if [ -b "$dev" ]; then
    EBS_DEV="$dev"
    break
  fi
done

if [ -z "$EBS_DEV" ]; then
  echo "[ERROR] EBSデバイスが見つかりません"
  exit 1
fi

if ! blkid "$EBS_DEV" | grep -q ext4; then
  echo "[INFO] EBSを初期化 (ext4)"
  mkfs -t ext4 "$EBS_DEV"
fi

mkdir -p /data
mount "$EBS_DEV" /data

if ! grep -q "$EBS_DEV" /etc/fstab; then
  echo "$EBS_DEV /data ext4 defaults,nofail 0 2" >> /etc/fstab
fi

# コンテナのマウント先
mkdir -p /data/7dtd/config
mkdir -p /data/7dtd/userdata

# ─── SSMからシークレット取得 ──────────────────────────────────────────────────
echo "[INFO] SSMからパスワード取得..."
SERVER_PASSWORD=$(aws ssm get-parameter \
  --name /7dtd/server-password \
  --with-decryption \
  --query Parameter.Value \
  --output text \
  --region "$AWS_REGION")

TELNET_PASSWORD=$(aws ssm get-parameter \
  --name /7dtd/telnet-password \
  --with-decryption \
  --query Parameter.Value \
  --output text \
  --region "$AWS_REGION")

# ─── serverconfig.xml 生成 ────────────────────────────────────────────────────
# コンテナ内のパス /config/serverconfig.xml に対応する場所に生成する
# SaveGameFolder はコンテナ内パスで指定する
if [ ! -f /data/7dtd/config/serverconfig.xml ]; then
  echo "[INFO] serverconfig.xml を生成..."
  cat > /data/7dtd/config/serverconfig.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<ServerSettings>
  <!-- サーバー基本設定 -->
  <property name="ServerName"                  value="$SERVER_NAME"/>
  <property name="ServerDescription"           value=""/>
  <property name="ServerWebsiteURL"            value=""/>
  <property name="ServerPassword"              value="$SERVER_PASSWORD"/>
  <property name="ServerLoginConfirmationText" value=""/>
  <property name="Region"                      value="Worldwide"/>
  <property name="Language"                    value="Japanese"/>

  <!-- ネットワーク -->
  <property name="ServerPort"                  value="26900"/>
  <property name="ServerVisibility"            value="2"/>
  <property name="ServerDisabledNetworkProtocols" value="SteamNetworking"/>

  <!-- プレイヤー -->
  <property name="ServerMaxPlayerCount"        value="$MAX_PLAYERS"/>
  <property name="ServerReservedSlots"         value="0"/>
  <property name="ServerReservedSlotsPermission" value="100"/>
  <property name="ServerAdminSlots"            value="0"/>
  <property name="ServerAdminSlotsPermission"  value="0"/>

  <!-- ゲーム設定 -->
  <property name="GameWorld"                   value="$GAME_WORLD"/>
  <property name="GameName"                    value="Friends"/>
  <property name="GameMode"                    value="GameModeSurvival"/>
  <property name="GameDifficulty"              value="2"/>

  <!-- Telnet (自動停止用) コンテナ内ポートをホストの8081にマッピング -->
  <property name="TelnetEnabled"               value="true"/>
  <property name="TelnetPort"                  value="8081"/>
  <property name="TelnetPassword"              value="$TELNET_PASSWORD"/>

  <!-- Web管理パネル (無効) -->
  <property name="WebDashboardEnabled"         value="false"/>
  <property name="WebDashboardPort"            value="8080"/>
  <property name="WebDashboardUrl"             value=""/>
  <property name="EnableMapRendering"          value="false"/>

  <!-- 昼夜サイクル -->
  <property name="DayNightLength"              value="60"/>
  <property name="DayCount"                    value="7"/>

  <!-- 経験値 -->
  <property name="XPMultiplier"                value="100"/>
  <property name="PartySharedKillRange"        value="100"/>

  <!-- ブロックダメージ -->
  <property name="BlockDamagePlayer"           value="100"/>
  <property name="BlockDamageAI"               value="100"/>
  <property name="BlockDamageAIBM"             value="100"/>

  <!-- ルート -->
  <property name="LootAbundance"               value="100"/>
  <property name="LootRespawnDays"             value="30"/>

  <!-- ゲームプレイ調整 -->
  <property name="EnemySpawnMode"              value="true"/>
  <property name="EnemyDifficulty"             value="0"/>
  <property name="ZombieMove"                  value="0"/>
  <property name="ZombieMoveNight"             value="3"/>
  <property name="ZombieBMMove"                value="3"/>
  <property name="ZombieFeral"                 value="0"/>
  <property name="ZombieFeralSense"            value="0"/>
  <property name="BloodMoonEnemyCount"         value="8"/>
  <property name="MaxSpawnedZombies"           value="64"/>
  <property name="MaxSpawnedAnimals"           value="50"/>
  <property name="DropOnDeath"                 value="1"/>
  <property name="DropOnQuit"                  value="0"/>
  <property name="PlayerKillingMode"           value="0"/>

  <!-- エアドロップ -->
  <property name="AirDropFrequency"            value="72"/>
  <property name="AirDropMarker"               value="true"/>

  <!-- 安全ゾーン・その他 -->
  <property name="PlayerSafeZoneLevel"         value="5"/>
  <property name="PlayerSafeZoneHours"         value="5"/>
  <property name="PersistentPlayerProfiles"    value="false"/>
  <property name="ServerMaxAllowedViewDistance" value="12"/>
  <property name="BuildCreate"                 value="false"/>

</ServerSettings>
XMLEOF
fi

# ─── プレイヤー数チェックスクリプト (auto_stop Lambda用) ─────────────────────
mkdir -p /opt/7dtd

cat > /opt/7dtd/check_players.py << 'PYEOF'
#!/usr/bin/env python3
"""7DTDテレネットに接続してプレイヤー数を返す。失敗時は-1を返す。"""
import socket
import sys
import time

TELNET_HOST = '127.0.0.1'
TELNET_PORT = 8081
TIMEOUT = 15

def main():
    password_file = '/opt/7dtd/.telnet_pass'
    try:
        with open(password_file) as f:
            password = f.read().strip()
    except Exception:
        sys.stderr.write("パスワードファイルが読めません\n")
        print(-1)
        sys.exit(1)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((TELNET_HOST, TELNET_PORT))

        time.sleep(0.5)
        s.recv(4096)

        s.sendall((password + '\r\n').encode())
        time.sleep(1)
        s.recv(4096)

        s.sendall(b'lp\r\n')
        time.sleep(2)

        data = b''
        s.settimeout(3)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass

        s.sendall(b'exit\r\n')
        s.close()

        text = data.decode('utf-8', errors='ignore')
        for line in text.splitlines():
            if 'Total of' in line and 'in the game' in line:
                count = int(line.split('Total of')[1].split('in')[0].strip())
                print(count)
                sys.exit(0)

        print(0)

    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        print(-1)
        sys.exit(1)

if __name__ == '__main__':
    main()
PYEOF

chmod +x /opt/7dtd/check_players.py
echo "$TELNET_PASSWORD" > /opt/7dtd/.telnet_pass
chmod 600 /opt/7dtd/.telnet_pass

# ─── SteamCMD で 7DTD ダウンロード ───────────────────────────────────────────
# apt版(i386依存で遅い)の代わりにValve公式tarballを直接取得する
echo "[INFO] SteamCMDをインストール..."
rm -rf /opt/steamcmd
mkdir -p /opt/steamcmd
curl -sqL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
  | tar zxf - -C /opt/steamcmd

# 初回実行: linux32/steamcmd のブートストラップだけ行う。
# steamcmd.sh は linux32/steamcmd をダウンロードしてから exec するが、
# ダウンロード完了前に exec が走り "No such file or directory" で失敗することがある。
# || true で失敗を無視し、ダウンロードが完了するまで待ってから本番を実行する。
/opt/steamcmd/steamcmd.sh +quit 2>/dev/null || true
sleep 10

echo "[INFO] 7DTDをダウンロード中 (初回は20〜40分かかります)..."
mkdir -p /data/7dtd/server
# SteamCMD は失敗時も exit 0 を返すため startserver.sh の存在でダウンロード成否を判定する
# "Missing configuration" は Steam 側の一時的な問題で複数回リトライすれば解消することが多い
MAX_ATTEMPTS=6
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  echo "[INFO] SteamCMD 試行 $attempt/$MAX_ATTEMPTS..."
  /opt/steamcmd/steamcmd.sh \
    +@sSteamCmdForcePlatformType linux \
    +force_install_dir /data/7dtd/server \
    +login anonymous \
    +app_update 294420 validate \
    +quit
  if [ -f /data/7dtd/server/startserver.sh ]; then
    echo "[INFO] 7DTDダウンロード成功"
    break
  fi
  echo "[WARN] SteamCMD 試行 $attempt 失敗 (startserver.sh なし)。60秒後にリトライ..."
  sleep 60
done
if [ ! -f /data/7dtd/server/startserver.sh ]; then
  echo "[ERROR] 7DTDダウンロードが$${MAX_ATTEMPTS}回とも失敗しました"
  exit 1
fi
echo "[INFO] 7DTDダウンロード完了"

# ─── Docker カスタムイメージビルド ───────────────────────────────────────────
# ubuntu:20.04 + libgcc-s1 + ca-certificates (ca-certificates がないと Steam SDK が SSL 接続できず
# GameServer.LogOn timed out になり Steam 認証が通らない)
mkdir -p /opt/7dtd
cat > /opt/7dtd/Dockerfile << 'DOCKEREOF'
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y libgcc-s1 ca-certificates && rm -rf /var/lib/apt/lists/*
DOCKEREOF
docker build -t 7dtd-local:latest /opt/7dtd/

# ─── Assembly-CSharp.dll パッチ ───────────────────────────────────────────────
# 7DTD 2.6 の Unity MonoBehaviour 初期化順序バグを修正する
# GameOptionsManager の静的コンストラクタから呼ばれる ValidateFoV/ValidateFoV3P が
# GamePrefs 未初期化時にクラッシュするため、この2メソッドのみ noop に差し替える。
# GUIWindowManager.Awake は noop にしてはいけない（シングルトン未初期化で
# GameManager.Awake が NullRef を起こしてサーバーが起動しなくなる）。
pip3 install dnfile 2>/dev/null || true
cat > /opt/7dtd/patch_assembly.py << 'PYEOF2'
import dnfile, shutil, struct, sys
path = '/data/7dtd/server/7DaysToDieServer_Data/Managed/Assembly-CSharp.dll'
dn = dnfile.dnPE(path)
with open(path, 'rb') as f:
    data = bytearray(f.read())
def rva2off(rva):
    for s in dn.sections:
        va = s.VirtualAddress
        if va <= rva < va + s.SizeOfRawData:
            return rva - va + s.PointerToRawData
    return None
TARGETS = {
    'GameOptionsManager': ['ValidateFoV', 'ValidateFoV3P'],
}
typedefs = dn.net.mdtables.TypeDef.rows
methoddefs = dn.net.mdtables.MethodDef.rows
patched = []
for i, trow in enumerate(typedefs):
    tname = str(trow.TypeName)
    if tname not in TARGETS: continue
    method_refs = trow.MethodList
    target_methods = TARGETS[tname]
    for mref in method_refs:
        try: mrow = mref.row
        except AttributeError:
            try:
                idx = mref.row_index - 1
                mrow = methoddefs[idx]
            except: continue
        mname = str(mrow.Name)
        if mname not in target_methods: continue
        rva = mrow.Rva
        if not isinstance(rva, int): rva = int(rva)
        if rva == 0: continue
        off = rva2off(rva)
        if off is None: continue
        hdr = data[off]; fmt = hdr & 0x3
        if fmt == 0x2:
            data[off] = 0x06; data[off + 1] = 0x2A
            print(f'PATCH-TINY {tname}.{mname} @ {off:#x}')
        elif fmt == 0x3:
            data[off] = 0x06; data[off + 1] = 0x2A
            print(f'PATCH-FAT->TINY {tname}.{mname} @ {off:#x}')
        else: continue
        patched.append(f'{tname}.{mname}')
print(f'Patched {len(patched)}: {patched}')
if not patched: sys.exit(1)
shutil.copy(path, path + '.bak')
with open(path, 'wb') as f: f.write(data)
print('Done.')
PYEOF2

if [ -f /data/7dtd/server/7DaysToDieServer_Data/Managed/Assembly-CSharp.dll ]; then
  python3 /opt/7dtd/patch_assembly.py
fi

# ─── systemd サービス登録 (Docker コンテナ管理) ──────────────────────────────
cat > /etc/systemd/system/7dtd.service << 'SVCEOF'
[Unit]
Description=7 Days to Die Dedicated Server (Docker ubuntu:20.04)
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=simple
Restart=on-failure
RestartSec=30
ExecStartPre=-/usr/bin/docker stop 7dtd
ExecStartPre=-/usr/bin/docker rm 7dtd
ExecStart=/usr/bin/docker run --name 7dtd --rm \
  --network=host \
  -v /data/7dtd/server:/server \
  -v /data/7dtd/config:/config \
  -v /data/7dtd/userdata:/root/.local/share/7DaysToDie \
  -w /server 7dtd-local:latest \
  /server/startserver.sh -configfile=/config/serverconfig.xml
ExecStop=/usr/bin/docker stop 7dtd
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable 7dtd
systemctl start 7dtd

echo "[$(date)] セットアップ完了"
