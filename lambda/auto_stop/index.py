"""
Auto Stop Lambda
- EventBridge (5分毎) または CloudWatch Alarm から起動
- EC2が動いていればSSM RunCommandでプレイヤー数を確認
- 指定分数以上0人が続いたらEC2を停止
"""
import json
import os
import time
import boto3

INSTANCE_ID = os.environ['INSTANCE_ID']
IDLE_THRESHOLD_MINUTES = int(os.environ['IDLE_THRESHOLD_MINUTES'])
CHECK_INTERVAL_MINUTES = int(os.environ['CHECK_INTERVAL_MINUTES'])
IDLE_PARAM_NAME = os.environ['IDLE_PARAM_NAME']
TELNET_PASSWORD_PARAM = os.environ['TELNET_PASSWORD_PARAM']

ec2 = boto3.client('ec2')
ssm = boto3.client('ssm')


def get_instance_state() -> str:
    resp = ec2.describe_instances(InstanceIds=[INSTANCE_ID])
    return resp['Reservations'][0]['Instances'][0]['State']['Name']


def get_telnet_password() -> str:
    resp = ssm.get_parameter(Name=TELNET_PASSWORD_PARAM, WithDecryption=True)
    return resp['Parameter']['Value']


def get_player_count() -> int:
    """SSM RunCommandでEC2上のcheck_players.pyを実行してプレイヤー数を返す。失敗時は-1。"""
    cmd_resp = ssm.send_command(
        InstanceIds=[INSTANCE_ID],
        DocumentName='AWS-RunShellScript',
        Parameters={'commands': ['python3 /opt/7dtd/check_players.py']},
        TimeoutSeconds=30,
    )
    command_id = cmd_resp['Command']['CommandId']

    # 最大30秒待機
    for _ in range(10):
        time.sleep(3)
        try:
            result = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=INSTANCE_ID,
            )
        except ssm.exceptions.InvocationDoesNotExist:
            continue

        status = result['Status']
        if status in ('Success', 'Failed', 'TimedOut', 'Cancelled'):
            if status == 'Success':
                stdout = result.get('StandardOutputContent', '').strip()
                try:
                    return int(stdout.splitlines()[-1])
                except (ValueError, IndexError):
                    return -1
            return -1

    return -1


def get_idle_minutes() -> int:
    try:
        resp = ssm.get_parameter(Name=IDLE_PARAM_NAME)
        return int(resp['Parameter']['Value'])
    except Exception:
        return 0


def set_idle_minutes(value: int) -> None:
    ssm.put_parameter(
        Name=IDLE_PARAM_NAME,
        Value=str(value),
        Type='String',
        Overwrite=True,
    )


def handler(event, context):
    state = get_instance_state()
    print(f"Instance state: {state}")

    if state != 'running':
        # 停止済みならアイドルカウンタをリセット
        set_idle_minutes(0)
        return {'status': 'skipped', 'reason': f'instance not running: {state}'}

    player_count = get_player_count()
    print(f"Player count: {player_count}")

    if player_count < 0:
        # 取得失敗 (サーバー起動中など) → アイドルカウントは進めない
        print("Failed to get player count, skipping idle check")
        return {'status': 'skipped', 'reason': 'player count unavailable'}

    if player_count > 0:
        # プレイヤーがいるのでリセット
        set_idle_minutes(0)
        print(f"Players online: {player_count}, resetting idle counter")
        return {'status': 'active', 'players': player_count}

    # プレイヤー0人 → アイドル時間を加算
    idle_minutes = get_idle_minutes() + CHECK_INTERVAL_MINUTES
    set_idle_minutes(idle_minutes)
    print(f"No players. Idle for {idle_minutes} minutes (threshold: {IDLE_THRESHOLD_MINUTES})")

    if idle_minutes >= IDLE_THRESHOLD_MINUTES:
        print(f"Idle threshold reached. Stopping instance {INSTANCE_ID}...")
        ec2.stop_instances(InstanceIds=[INSTANCE_ID])
        set_idle_minutes(0)
        return {'status': 'stopped', 'idle_minutes': idle_minutes}

    return {'status': 'idle', 'idle_minutes': idle_minutes, 'threshold': IDLE_THRESHOLD_MINUTES}
