#!/bin/bash
set -euo pipefail

# Terraform templatefile変数
SERVER_NAME="${server_name}"
MAX_PLAYERS="${max_players}"
GAME_WORLD="${game_world}"
AWS_REGION="${aws_region}"

LOG=/var/log/7dtd-setup.log
exec > >(tee -a "$LOG") 2>&1
echo "[$(date)] Starting 7DTD server setup..."

# ─── 基本パッケージ ───────────────────────────────────────────────────────────
apt-get update -y
apt-get install -y ca-certificates curl awscli netcat-openbsd

# ─── SteamCMD インストール ────────────────────────────────────────────────────
echo "[INFO] SteamCMDをインストール..."
add-apt-repository multiverse -y
dpkg --add-architecture i386
apt-get update -y
# Steam EULA を事前承認（非対話インストールに必要）
echo "steamcmd steam/question select I AGREE" | debconf-set-selections
echo "steamcmd steam/license note ''" | debconf-set-selections
DEBIAN_FRONTEND=noninteractive apt-get install -y steamcmd

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

mkdir -p /data/7dtd/saves

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
if [ ! -f /data/7dtd/serverconfig.xml ]; then
  echo "[INFO] serverconfig.xml を生成..."
  cat > /data/7dtd/serverconfig.xml << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<ServerSettings>
  <!-- サーバー基本設定 -->
  <property name="ServerName"                  value="$SERVER_NAME"/>
  <property name="ServerDescription"           value=""/>
  <property name="ServerWebsiteURL"            value=""/>
  <property name="ServerPassword"              value="$SERVER_PASSWORD"/>
  <property name="ServerLoginConfirmationText" value=""/>
  <property name="Region"                      value="Worldwide"/>
  <property name="Language"                    value="English"/>

  <!-- ネットワーク -->
  <property name="ServerPort"                  value="26900"/>
  <property name="ServerVisibility"            value="2"/>
  <property name="NetworkingProtocol"          value="LiteNetLib"/>
  <property name="ServerDisabledNetworkProtocols" value="SteamNetworking"/>
  <property name="MaxUncoveredMapChunks"       value="131072"/>

  <!-- プレイヤー -->
  <property name="ServerMaxPlayerCount"        value="$MAX_PLAYERS"/>
  <property name="ServerReservedSlots"         value="0"/>
  <property name="ServerReservedSlotsPermission" value="100"/>
  <property name="ServerAdminSlots"            value="0"/>
  <property name="ServerAdminSlotsPermission"  value="0"/>

  <!-- ゲーム設定 -->
  <property name="GameWorld"                   value="$GAME_WORLD"/>
  <property name="WorldGenSeed"                value="AsphaltValleyAB3"/>
  <property name="WorldGenSize"                value="6144"/>
  <property name="GameName"                    value="Friends"/>
  <property name="GameMode"                    value="GameModeSurvival"/>
  <property name="GameDifficulty"              value="2"/>

  <!-- Telnet (自動停止用) -->
  <property name="TelnetEnabled"               value="true"/>
  <property name="TelnetPort"                  value="8081"/>
  <property name="TelnetPassword"              value="$TELNET_PASSWORD"/>
  <property name="TelnetFailedLoginLimit"      value="10"/>
  <property name="TelnetFailedLoginsBlockTime" value="10"/>

  <!-- Web管理パネル (無効) -->
  <property name="WebDashboardEnabled"         value="false"/>
  <property name="WebDashboardPort"            value="8080"/>
  <property name="WebDashboardUrl"             value=""/>
  <property name="EnableMapRendering"          value="false"/>

  <!-- ゲームプレイ調整 -->
  <property name="EnemySpawnMode"              value="true"/>
  <property name="EnemyDifficulty"             value="0"/>
  <property name="ZombieMove"                  value="0"/>
  <property name="ZombieMoveNight"             value="3"/>
  <property name="BloodMoonEnemyCount"         value="8"/>
  <property name="DropOnDeath"                 value="1"/>
  <property name="DropOnQuit"                  value="0"/>
  <property name="PlayerKillingMode"           value="0"/>

  <property name="SaveGameFolder"              value="/data/7dtd/saves"/>
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

# ─── 7DTD 専用サーバー インストール (SteamCMD) ───────────────────────────────
echo "[INFO] 7DTDサーバーをSteamCMDでダウンロード..."

# steam ユーザー作成（存在しなければ）
id steam &>/dev/null || useradd -m -s /bin/bash steam

mkdir -p /data/7dtd/server
chown -R steam:steam /data/7dtd

# SteamCMD で匿名ダウンロード (App ID 294420 = 7DTD Dedicated Server)
sudo -u steam /usr/games/steamcmd \
  +force_install_dir /data/7dtd/server \
  +login anonymous \
  +app_update 294420 validate \
  +quit

echo "[INFO] ダウンロード完了"

# ─── systemd サービス登録 ─────────────────────────────────────────────────────
cat > /etc/systemd/system/7dtd.service << 'SVCEOF'
[Unit]
Description=7 Days to Die Dedicated Server
After=network.target

[Service]
Type=simple
User=steam
WorkingDirectory=/data/7dtd/server
ExecStart=/data/7dtd/server/startserver.sh -configfile=/data/7dtd/serverconfig.xml
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable 7dtd
systemctl start 7dtd

echo "[$(date)] セットアップ完了"
