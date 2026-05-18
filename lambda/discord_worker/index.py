"""
Discord Worker Lambda
- start / stop / status コマンドを処理
- EC2を起動/停止してDiscordにフォローアップメッセージを送信
"""
import json
import os
import time
import urllib.request
import urllib.error
import boto3

INSTANCE_ID = os.environ['INSTANCE_ID']
AWS_REGION = os.environ['AWS_ACCOUNT_REGION']
DISCORD_APPLICATION_ID = os.environ['DISCORD_APPLICATION_ID']
BOT_TOKEN_PARAM = os.environ['BOT_TOKEN_PARAM']

ec2 = boto3.client('ec2', region_name=AWS_REGION)
ssm = boto3.client('ssm', region_name=AWS_REGION)

DISCORD_API = 'https://discord.com/api/v10'


def get_bot_token() -> str:
    resp = ssm.get_parameter(Name=BOT_TOKEN_PARAM, WithDecryption=True)
    return resp['Parameter']['Value']


def edit_original_response(token: str, content: str) -> None:
    bot_token = get_bot_token()
    url = f"{DISCORD_API}/webhooks/{DISCORD_APPLICATION_ID}/{token}/messages/@original"
    data = json.dumps({'content': content}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method='PATCH',
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


def get_instance_state() -> dict:
    resp = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    instance = resp['Reservations'][0]['Instances'][0]
    return {
        'state': instance['State']['Name'],
        'public_ip': instance.get('PublicIpAddress', ''),
    }


def wait_for_state(target_state: str, timeout_sec: int = 120) -> str:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        info = get_instance_state()
        if info['state'] == target_state:
            return info.get('public_ip', '')
        time.sleep(8)
    return ''


def handle_start(token: str) -> None:
    info = get_instance_state()
    state = info['state']

    if state == 'running':
        ip = info['public_ip']
        edit_original_response(token, f'サーバーはすでに起動中です。\nIP: `{ip}:26900`')
        return

    if state not in ('stopped', 'stopping'):
        edit_original_response(token, f'起動できない状態です: `{state}`')
        return

    if state == 'stopping':
        edit_original_response(token, '停止処理中のため少し待ってから再度お試しください。')
        return

    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    edit_original_response(token, 'サーバーを起動しています... (最大2分かかります)')

    ip = wait_for_state('running', timeout_sec=180)
    if ip:
        edit_original_response(token, f'サーバーが起動しました!\nIP: `{ip}:26900`\n\n※ゲームが完全に起動するまでさらに3〜5分かかります。')
    else:
        edit_original_response(token, 'タイムアウト: 起動に時間がかかっています。少し待ってから `/status` で確認してください。')


def handle_stop(token: str) -> None:
    info = get_instance_state()
    state = info['state']

    if state == 'stopped':
        edit_original_response(token, 'サーバーはすでに停止しています。')
        return

    if state != 'running':
        edit_original_response(token, f'停止できない状態です: `{state}`')
        return

    ec2.stop_instances(InstanceIds=[INSTANCE_ID])
    edit_original_response(token, 'サーバーを停止しています...')

    wait_for_state('stopped', timeout_sec=120)
    edit_original_response(token, 'サーバーを停止しました。')


def handle_status(token: str) -> None:
    info = get_instance_state()
    state = info['state']

    state_label = {
        'running': '起動中',
        'stopped': '停止中',
        'pending': '起動処理中',
        'stopping': '停止処理中',
    }.get(state, state)

    if state == 'running' and info['public_ip']:
        msg = f'状態: {state_label}\nIP: `{info["public_ip"]}:26900`'
    else:
        msg = f'状態: {state_label}'

    edit_original_response(token, msg)


COMMAND_HANDLERS = {
    'start': handle_start,
    'stop': handle_stop,
    'status': handle_status,
}


def handler(event, context):
    token = event.get('token', '')
    command_name = event.get('data', {}).get('name', '')

    fn = COMMAND_HANDLERS.get(command_name)
    if fn is None:
        edit_original_response(token, f'不明なコマンド: `{command_name}`')
        return

    try:
        fn(token)
    except Exception as e:
        print(f"Error handling command '{command_name}': {e}")
        try:
            edit_original_response(token, f'エラーが発生しました: {e}')
        except Exception:
            pass
