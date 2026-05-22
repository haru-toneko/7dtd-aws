"""
Game Ready Notifier Lambda
discord_worker から非同期で呼び出され、7DTD の Telnet ポート (8081) が
応答するまで SSM 経由でポーリングし、準備完了を Discord に通知する。

event: {"token": "<interaction_token>", "ip": "x.x.x.x"}
Lambda timeout: 900s (最大15分)
"""
import base64
import json
import os
import time
import urllib.request
import urllib.error
import boto3
from botocore.exceptions import ClientError

INSTANCE_ID = os.environ['INSTANCE_ID']
AWS_REGION = os.environ['AWS_ACCOUNT_REGION']
DISCORD_APPLICATION_ID = os.environ['DISCORD_APPLICATION_ID']
BOT_TOKEN_PARAM = os.environ['BOT_TOKEN_PARAM']

ssm = boto3.client('ssm', region_name=AWS_REGION)

DISCORD_API = 'https://discord.com/api/v10'

# Telnet 8081 に接続してバナーを受信できるか確認するスクリプト
_TELNET_CHECK = """\
import socket
try:
    s = socket.socket()
    s.settimeout(5)
    s.connect(('127.0.0.1', 8081))
    s.recv(256)
    s.close()
    print('READY')
except Exception:
    print('NOT_READY')
"""
_TELNET_CHECK_B64 = base64.b64encode(_TELNET_CHECK.encode()).decode()

# ─── Discord API ──────────────────────────────────────────────────────────────

def get_bot_token() -> str:
    resp = ssm.get_parameter(Name=BOT_TOKEN_PARAM, WithDecryption=True)
    return resp['Parameter']['Value']


def edit_original_response(token: str, content: str) -> None:
    bot_token = get_bot_token()
    url = f"{DISCORD_API}/webhooks/{DISCORD_APPLICATION_ID}/{token}/messages/@original"
    data = json.dumps({'content': content}).encode()
    req = urllib.request.Request(
        url, data=data, method='PATCH',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bot {bot_token}',
            'User-Agent': 'DiscordBot (https://github.com/example/7dtd-bot, 1.0)',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except urllib.error.HTTPError as e:
        print(f"Discord API error: {e.code} {e.read()}")

# ─── ゲーム準備確認 ───────────────────────────────────────────────────────────

def check_game_ready() -> bool:
    """SSM Run Command で Telnet ポートが応答するか確認する。"""
    commands = [
        f"printf '%s' '{_TELNET_CHECK_B64}' | base64 -d > /tmp/_check_ready.py",
        'python3 /tmp/_check_ready.py',
        'rm -f /tmp/_check_ready.py',
    ]
    try:
        resp = ssm.send_command(
            InstanceIds=[INSTANCE_ID],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': commands},
            TimeoutSeconds=15,
        )
        command_id = resp['Command']['CommandId']
    except ClientError as e:
        print(f"send_command failed: {e}")
        return False

    deadline = time.time() + 25
    while time.time() < deadline:
        time.sleep(3)
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=INSTANCE_ID)
        except ClientError:
            continue
        status = result['Status']
        if status == 'Success':
            return 'READY' in result.get('StandardOutputContent', '')
        if status in ('Failed', 'Cancelled', 'TimedOut', 'Undeliverable'):
            return False
    return False

# ─── エントリポイント ─────────────────────────────────────────────────────────

def handler(event, context):
    token = event['token']
    ip = event['ip']

    print(f"Polling game readiness for IP={ip}")

    # 最大約10分 (15回 × ~40s) ポーリング
    for attempt in range(15):
        print(f"Attempt {attempt + 1}/15")
        if check_game_ready():
            print("Game is READY")
            edit_original_response(
                token,
                f'ゲームが起動しました！接続できます。\nIP: `{ip}:26900`'
            )
            return
        if attempt < 14:
            time.sleep(15)

    print("Polling timed out")
    edit_original_response(
        token,
        f'ゲームの起動確認がタイムアウトしました。\nIP: `{ip}:26900`\n接続できない場合はしばらく待ってから試してください。'
    )
