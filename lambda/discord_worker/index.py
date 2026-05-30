"""
Discord Worker Lambda
- start / stop / status / settings / set コマンドを処理
- EC2を起動/停止し、serverconfig.xml をSSM Run Command で書き換える
"""
import base64
import json
import os
import re
import time
import urllib.request
import urllib.error
import boto3
from botocore.exceptions import ClientError

INSTANCE_ID = os.environ['INSTANCE_ID']
AWS_REGION = os.environ['AWS_ACCOUNT_REGION']
DISCORD_APPLICATION_ID = os.environ['DISCORD_APPLICATION_ID']
BOT_TOKEN_PARAM = os.environ['BOT_TOKEN_PARAM']
NOTIFIER_LAMBDA_ARN = os.environ.get('NOTIFIER_LAMBDA_ARN', '')
IDLE_PARAM_NAME = os.environ.get('IDLE_PARAM_NAME', '')

ec2 = boto3.client('ec2', region_name=AWS_REGION)
ssm = boto3.client('ssm', region_name=AWS_REGION)
lambda_client = boto3.client('lambda', region_name=AWS_REGION)

MODS_DIR = '/data/7dtd/server/Mods'
MODS_DISABLED_DIR = '/data/7dtd/server/Mods.disabled'
PATCH_SCRIPT = '/opt/7dtd/patch_assembly.py'
INSTALLED_VERSION_FILE = '/data/7dtd/installed_version'

VERSION_STEAMCMD_ARGS = {
    'latest':       '+app_update 294420 validate',
    'experimental': '+app_update 294420 -beta latest_experimental validate',
    'alpha20.7':    '+app_update 294420 -beta alpha20.7 validate',
}

DISCORD_API = 'https://discord.com/api/v10'

# Discord オプション名 → serverconfig.xml プロパティ名
SETTING_MAP = {
    # ─── ゲーム基本 ───────────────────────────────────────────────────────────
    'difficulty':           'GameDifficulty',
    'world':                'GameWorld',
    'game_name':            'GameName',
    # ─── プレイヤー ───────────────────────────────────────────────────────────
    'max_players':          'ServerMaxPlayerCount',
    'player_killing':       'PlayerKillingMode',
    'drop_on_death':        'DropOnDeath',
    'drop_on_quit':         'DropOnQuit',
    # ─── 経験値 ───────────────────────────────────────────────────────────────
    'xp_multiplier':        'XPMultiplier',
    'party_xp_range':       'PartySharedKillRange',
    # ─── ブロックダメージ ─────────────────────────────────────────────────────
    'block_damage_player':  'BlockDamagePlayer',
    'block_damage_zombie':  'BlockDamageAI',
    'block_damage_bm':      'BlockDamageAIBM',
    # ─── 昼夜サイクル ─────────────────────────────────────────────────────────
    'day_length':           'DayNightLength',
    'blood_moon_day':       'DayCount',
    # ─── ルート ───────────────────────────────────────────────────────────────
    'loot_abundance':       'LootAbundance',
    'loot_respawn_days':    'LootRespawnDays',
    # ─── ゾンビ ───────────────────────────────────────────────────────────────
    'enemy_spawn':          'EnemySpawnMode',
    'enemy_difficulty':     'EnemyDifficulty',
    'zombie_day':           'ZombieMove',
    'zombie_night':         'ZombieMoveNight',
    'zombie_bm_speed':      'ZombieBMMove',
    'zombie_feral':         'ZombieFeral',
    'zombie_feral_sense':   'ZombieFeralSense',
    'blood_moon_count':     'BloodMoonEnemyCount',
    'max_zombies':          'MaxSpawnedZombies',
    'max_animals':          'MaxSpawnedAnimals',
    # ─── エアドロップ ─────────────────────────────────────────────────────────
    'airdrop_frequency':    'AirDropFrequency',
    'airdrop_marker':       'AirDropMarker',
    # ─── サーバー表示・その他 ─────────────────────────────────────────────────
    'server_name':          'ServerName',
    'server_visibility':    'ServerVisibility',
    'view_distance':        'ServerMaxAllowedViewDistance',
    'creative_mode':        'BuildCreate',
    'persistent_profiles':  'PersistentPlayerProfiles',
    'safe_zone_level':      'PlayerSafeZoneLevel',
    'safe_zone_hours':      'PlayerSafeZoneHours',
}

# 表示用: (日本語ラベル, 値→説明マップ or None)
SETTING_LABELS = {
    'GameDifficulty':               ('難易度',              {0: 'Scavenger', 1: 'Adventurer', 2: 'Nomad', 3: 'Warrior', 4: 'Survivalist', 5: 'Insane'}),
    'GameWorld':                    ('ワールド',             None),
    'GameName':                     ('セーブ名',             None),
    'ServerMaxPlayerCount':         ('最大人数',             None),
    'PlayerKillingMode':            ('PvP',                  {0: 'オフ', 1: '同陣営のみ', 2: '他陣営のみ', 3: '全員'}),
    'DropOnDeath':                  ('死亡ドロップ',         {0: 'なし', 1: '全部', 2: 'ツールベルト', 3: 'バックパック', 4: '全削除'}),
    'DropOnQuit':                   ('退出ドロップ',         {0: 'なし', 1: '全部', 2: 'ツールベルト', 3: 'バックパック', 4: '全削除'}),
    'XPMultiplier':                 ('XP倍率',               None),
    'PartySharedKillRange':         ('同盟XP共有範囲(ブロック)', None),
    'BlockDamagePlayer':            ('プレイヤーBD%',        None),
    'BlockDamageAI':                ('ゾンビBD%',            None),
    'BlockDamageAIBM':              ('BM-ゾンビBD%',         None),
    'DayNightLength':               ('1日の長さ(分)',         None),
    'DayCount':                     ('BM周期(日)',            None),
    'LootAbundance':                ('ルート量%',             None),
    'LootRespawnDays':              ('ルート再生成(日)',      None),
    'EnemySpawnMode':               ('敵スポーン',           {'true': 'あり', 'false': 'なし'}),
    'EnemyDifficulty':              ('敵の強さ',             {0: 'Normal', 1: 'Feral'}),
    'ZombieMove':                   ('昼ゾンビ速度',         {0: 'Walk', 1: 'Jog', 2: 'Run', 3: 'Sprint', 4: 'Nightmare'}),
    'ZombieMoveNight':              ('夜ゾンビ速度',         {0: 'Walk', 1: 'Jog', 2: 'Run', 3: 'Sprint', 4: 'Nightmare'}),
    'ZombieBMMove':                 ('BMゾンビ速度',         {0: 'Walk', 1: 'Jog', 2: 'Run', 3: 'Sprint', 4: 'Nightmare'}),
    'ZombieFeral':                  ('フェラル出現',         {0: 'なし', 1: '昼のみ', 2: '夜のみ', 3: '常時'}),
    'ZombieFeralSense':             ('フェラル感知',         {0: 'なし', 1: '昼のみ', 2: '夜のみ', 3: '常時'}),
    'BloodMoonEnemyCount':          ('BM最大ゾンビ数',       None),
    'MaxSpawnedZombies':            ('最大ゾンビ数',         None),
    'MaxSpawnedAnimals':            ('最大動物数',           None),
    'AirDropFrequency':             ('エアドロ間隔(時間)',   None),
    'AirDropMarker':                ('エアドロマーカー',     {'true': '表示', 'false': '非表示'}),
    'ServerName':                   ('サーバー名',           None),
    'ServerVisibility':             ('公開設定',             {0: '非公開', 1: 'フレンドのみ', 2: '公開'}),
    'ServerMaxAllowedViewDistance': ('最大視野距離(chunk)',  None),
    'BuildCreate':                  ('クリエイティブモード', {'true': '有効', 'false': '無効'}),
    'PersistentPlayerProfiles':     ('プロファイル固定',     {'true': '有効', 'false': '無効'}),
    'PlayerSafeZoneLevel':          ('安全ゾーンLv上限',     None),
    'PlayerSafeZoneHours':          ('安全ゾーン時間(h)',    None),
}

SETTINGS_ORDER = [
    'GameDifficulty', 'GameWorld', 'GameName',
    'DayNightLength', 'DayCount',
    'ServerMaxPlayerCount', 'PlayerKillingMode', 'DropOnDeath', 'DropOnQuit',
    'XPMultiplier', 'PartySharedKillRange',
    'BlockDamagePlayer', 'BlockDamageAI', 'BlockDamageAIBM',
    'LootAbundance', 'LootRespawnDays',
    'EnemySpawnMode', 'EnemyDifficulty',
    'ZombieMove', 'ZombieMoveNight', 'ZombieBMMove',
    'ZombieFeral', 'ZombieFeralSense',
    'BloodMoonEnemyCount', 'MaxSpawnedZombies', 'MaxSpawnedAnimals',
    'AirDropFrequency', 'AirDropMarker',
    'ServerName', 'ServerVisibility',
    'ServerMaxAllowedViewDistance', 'BuildCreate',
    'PersistentPlayerProfiles', 'PlayerSafeZoneLevel', 'PlayerSafeZoneHours',
]

# デフォルト値 (7DTD 2.x 標準値)
SETTING_DEFAULTS = {
    'GameDifficulty':               '2',
    'GameWorld':                    'Navezgane',
    'GameName':                     'My Game',
    'ServerMaxPlayerCount':         '8',
    'PlayerKillingMode':            '0',
    'DropOnDeath':                  '1',
    'DropOnQuit':                   '0',
    'XPMultiplier':                 '100',
    'PartySharedKillRange':         '100',
    'BlockDamagePlayer':            '100',
    'BlockDamageAI':                '100',
    'BlockDamageAIBM':              '100',
    'DayNightLength':               '60',
    'DayCount':                     '7',
    'LootAbundance':                '100',
    'LootRespawnDays':              '30',
    'EnemySpawnMode':               'true',
    'EnemyDifficulty':              '0',
    'ZombieMove':                   '0',
    'ZombieMoveNight':              '3',
    'ZombieBMMove':                 '3',
    'ZombieFeral':                  '3',
    'ZombieFeralSense':             '0',
    'BloodMoonEnemyCount':          '8',
    'MaxSpawnedZombies':            '64',
    'MaxSpawnedAnimals':            '50',
    'AirDropFrequency':             '72',
    'AirDropMarker':                'true',
    'ServerName':                   'My Game Host',
    'ServerVisibility':             '2',
    'ServerMaxAllowedViewDistance': '12',
    'BuildCreate':                  'false',
    'PersistentPlayerProfiles':     'false',
    'PlayerSafeZoneLevel':          '5',
    'PlayerSafeZoneHours':          '5',
}

# カテゴリ別 XML プロパティ名リスト
HELP_CATEGORIES = {
    'gameplay': [
        'GameDifficulty', 'DayNightLength', 'DayCount',
        'XPMultiplier', 'PartySharedKillRange',
        'BlockDamagePlayer', 'BlockDamageAI', 'BlockDamageAIBM',
        'LootAbundance', 'LootRespawnDays',
        'PlayerKillingMode', 'DropOnDeath', 'DropOnQuit',
    ],
    'zombies': [
        'EnemySpawnMode', 'EnemyDifficulty',
        'ZombieMove', 'ZombieMoveNight', 'ZombieBMMove',
        'ZombieFeral', 'ZombieFeralSense',
        'BloodMoonEnemyCount', 'MaxSpawnedZombies', 'MaxSpawnedAnimals',
    ],
    'server': [
        'ServerName', 'ServerVisibility', 'ServerMaxPlayerCount',
        'AirDropFrequency', 'AirDropMarker',
        'ServerMaxAllowedViewDistance', 'BuildCreate',
        'PersistentPlayerProfiles', 'PlayerSafeZoneLevel', 'PlayerSafeZoneHours',
    ],
}

# XML名 → Discord オプション名 (逆引き)
XML_TO_OPTION = {v: k for k, v in SETTING_MAP.items()}

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

# ─── Notifier ────────────────────────────────────────────────────────────────

def reset_idle_counter() -> None:
    """起動時に auto_stop のアイドルカウンターをリセットする。"""
    if not IDLE_PARAM_NAME:
        return
    try:
        ssm.put_parameter(Name=IDLE_PARAM_NAME, Value='0', Type='String', Overwrite=True)
    except Exception as e:
        print(f"reset_idle_counter failed: {e}")


def invoke_notifier(token: str, ip: str) -> None:
    """game_ready_notifier Lambda を非同期で呼び出す。"""
    if not NOTIFIER_LAMBDA_ARN:
        return
    try:
        lambda_client.invoke(
            FunctionName=NOTIFIER_LAMBDA_ARN,
            InvocationType='Event',
            Payload=json.dumps({'token': token, 'ip': ip}).encode(),
        )
    except Exception as e:
        print(f"invoke_notifier failed: {e}")

# ─── EC2 ─────────────────────────────────────────────────────────────────────

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

# ─── SSM Run Command ──────────────────────────────────────────────────────────

def ssm_run(commands: list, timeout_sec: int = 90) -> tuple:
    """SSM Run Commandを実行。SSMエージェント未起動時は最大60秒リトライ。"""
    command_id = None
    for attempt in range(7):
        try:
            resp = ssm.send_command(
                InstanceIds=[INSTANCE_ID],
                DocumentName='AWS-RunShellScript',
                Parameters={'commands': commands},
                TimeoutSeconds=60,
            )
            command_id = resp['Command']['CommandId']
            break
        except ClientError as e:
            code = e.response['Error']['Code']
            if code == 'InvalidInstanceId' and attempt < 6:
                time.sleep(10)
                continue
            return False, f'SSM Error: {code}'

    if command_id is None:
        return False, 'SSMエージェントが起動しませんでした'

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(5)
        try:
            result = ssm.get_command_invocation(CommandId=command_id, InstanceId=INSTANCE_ID)
        except ClientError:
            continue
        status = result['Status']
        if status == 'Success':
            return True, result.get('StandardOutputContent', '').strip()
        if status in ('Failed', 'Cancelled', 'TimedOut', 'Undeliverable'):
            err = result.get('StandardErrorContent', '').strip()
            out = result.get('StandardOutputContent', '').strip()
            return False, err or out
    return False, 'タイムアウト'

# ─── 設定操作 ─────────────────────────────────────────────────────────────────

def apply_settings(xml_settings: dict, restart: bool = True) -> tuple:
    """serverconfig.xml を更新する。プロパティが存在しなければ末尾に追記する。"""
    settings_b64 = base64.b64encode(json.dumps(xml_settings).encode()).decode()
    script = f"""\
import re, json, base64
settings = json.loads(base64.b64decode('{settings_b64}').decode())
path = '/data/7dtd/config/serverconfig.xml'
content = open(path).read()
for name, value in settings.items():
    if re.search(r'<property name="' + name + r'"', content):
        content = re.sub(
            r'(<property name="' + name + r'"[^>]*value=")[^"]*(")',
            lambda m, v=value: m.group(1) + v + m.group(2),
            content
        )
    else:
        line = '  <property name="' + name + '" value="' + value + '"/>\\n'
        content = content.replace('</ServerSettings>', line + '</ServerSettings>')
open(path, 'w').write(content)
print('OK: ' + str(list(settings.keys())))
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_update.py",
        'python3 /tmp/_7dtd_update.py',
        'rm -f /tmp/_7dtd_update.py',
    ]
    if restart:
        commands.append('systemctl restart 7dtd')
    return ssm_run(commands, timeout_sec=90)


def read_settings() -> tuple:
    """現在の serverconfig.xml から設定値を読み取り dict で返す。"""
    names_b64 = base64.b64encode(json.dumps(SETTINGS_ORDER).encode()).decode()
    script = f"""\
import re, json, base64
names = json.loads(base64.b64decode('{names_b64}').decode())
content = open('/data/7dtd/config/serverconfig.xml').read()
result = {{}}
for name in names:
    m = re.search(r'<property name="' + name + r'"[^>]*value="([^"]*)"', content)
    if m:
        result[name] = m.group(1)
print(json.dumps(result))
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_read.py",
        'python3 /tmp/_7dtd_read.py',
        'rm -f /tmp/_7dtd_read.py',
    ]
    ok, output = ssm_run(commands, timeout_sec=60)
    if not ok:
        return False, output
    try:
        return True, json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return False, f'パースエラー: {output!r}'

# ─── 表示フォーマット ─────────────────────────────────────────────────────────

def format_value(xml_name: str, xml_value: str) -> str:
    if xml_name not in SETTING_LABELS:
        return xml_value
    _, choices = SETTING_LABELS[xml_name]
    if choices is None:
        return xml_value
    try:
        key = int(xml_value)
    except ValueError:
        key = xml_value
    return f'{choices.get(key, xml_value)} ({xml_value})'


def format_settings_message(settings: dict) -> str:
    lines = ['**現在のゲーム設定**']
    for xml_name in SETTINGS_ORDER:
        if xml_name not in settings:
            continue
        label, _ = SETTING_LABELS.get(xml_name, (xml_name, None))
        lines.append(f'**{label}**: {format_value(xml_name, settings[xml_name])}')
    return '\n'.join(lines)

# ─── オプション変換 ───────────────────────────────────────────────────────────

def parse_options(data: dict) -> dict:
    """flat optionsとsubcommand optionsの両方を処理する。"""
    raw = data.get('options', [])
    if not raw:
        return {}
    # SUB_COMMAND (type=1) の場合はその中の options を取得
    if raw[0].get('type') == 1:
        return {opt['name']: opt['value'] for opt in raw[0].get('options', [])}
    return {opt['name']: opt['value'] for opt in raw}


def options_to_xml(options: dict) -> dict:
    result = {}
    for opt_name, value in options.items():
        xml_name = SETTING_MAP.get(opt_name)
        if xml_name is None:
            continue
        if isinstance(value, bool):
            result[xml_name] = 'true' if value else 'false'
        else:
            result[xml_name] = str(value)
    return result

# ─── コマンドハンドラ ─────────────────────────────────────────────────────────

def handle_start(token: str, data: dict) -> None:
    options = parse_options(data)
    version = options.get('version')
    xml_settings = options_to_xml(options)  # 'version' は SETTING_MAP に無いので自動スキップ

    if version and version not in VERSION_STEAMCMD_ARGS:
        edit_original_response(token, f'不明なバージョン: `{version}`\n利用可能: {", ".join(VERSION_STEAMCMD_ARGS.keys())}')
        return

    info = get_instance_state()
    state = info['state']

    if state == 'stopping':
        edit_original_response(token, '停止処理中のため少し待ってから再度お試しください。')
        return

    if state not in ('running', 'stopped'):
        edit_original_response(token, f'起動できない状態です: `{state}`')
        return

    # EC2が停止中なら起動する
    if state == 'stopped':
        reset_idle_counter()
        ec2.start_instances(InstanceIds=[INSTANCE_ID])
        parts = ['サーバーを起動しています...']
        if version:
            parts.append(f'バージョン: `{version}`')
        if xml_settings:
            parts.append('設定も適用します。')
        edit_original_response(token, ' '.join(parts))
        ip = wait_for_state('running', timeout_sec=180)
        if not ip:
            edit_original_response(token, 'タイムアウト: 起動に時間がかかっています。少し待ってから `/status` で確認してください。')
            return
    else:
        ip = info['public_ip']

    # バージョン変更の確認 (指定時のみ)
    needs_version_update = False
    if version:
        ok, installed = ssm_run(
            [f'cat {INSTALLED_VERSION_FILE} 2>/dev/null || echo unknown'],
            timeout_sec=30,
        )
        installed_ver = installed.strip() if ok else 'unknown'
        needs_version_update = (installed_ver != version)

    # バージョン変更あり
    if needs_version_update:
        if xml_settings:
            ok, err = apply_settings(xml_settings, restart=False)
            if not ok:
                edit_original_response(token, f'設定の適用に失敗しました: {err}')
                return
        if state == 'stopped':
            msg = (f'EC2が起動しました。バージョンを `{version}` に切り替え中...\n'
                   f'完了したら通知します。(20〜40分かかる場合があります)\nIP: `{ip}:26900`')
        else:
            msg = (f'バージョンを `{version}` に切り替え中... 完了したら通知します。\n'
                   f'(20〜40分かかる場合があります)\nIP: `{ip}:26900`')
        edit_original_response(token, msg)
        ok, err = launch_version_update(version)
        if not ok:
            edit_original_response(token, f'バージョン切り替えの開始に失敗しました: {err}')
            return
        invoke_notifier(token, ip)
        return

    # バージョン変更なし・EC2起動中・設定変更なし
    if state == 'running' and not xml_settings:
        suffix = f'\n(`{version}` は既にインストール済みです)' if version else ''
        edit_original_response(token, f'サーバーはすでに起動中です。\nIP: `{ip}:26900`{suffix}')
        return

    # 設定変更あり
    if xml_settings:
        if state == 'running':
            edit_original_response(token, '設定を更新してサーバーを再起動しています...\n⚠️ 接続中のプレイヤーは切断されます。')
        ok, err = apply_settings(xml_settings)
        if ok:
            edit_original_response(token, f'再起動しました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
            invoke_notifier(token, ip)
        else:
            edit_original_response(token, f'設定更新に失敗しました: {err}')
        return

    # EC2を起動したが設定変更もバージョン変更もなし
    edit_original_response(token, f'EC2が起動しました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
    invoke_notifier(token, ip)


def handle_set(token: str, data: dict) -> None:
    """起動中のサーバーの設定を即時変更する。"""
    options = parse_options(data)
    xml_settings = options_to_xml(options)

    if not xml_settings:
        edit_original_response(token, '設定オプションを指定してください。\n例: `/set gameplay xp_multiplier:200`')
        return

    info = get_instance_state()
    state = info['state']

    if state != 'running':
        state_label = {'stopped': '停止中', 'pending': '起動処理中', 'stopping': '停止処理中'}.get(state, state)
        edit_original_response(
            token,
            f'サーバーが{state_label}のため変更できません。\n'
            '起動中のときに `/set` を使うか、`/start` のオプションで設定を指定してください。'
        )
        return

    ip = info['public_ip']
    edit_original_response(token, '設定を更新しています...\n⚠️ 接続中のプレイヤーは切断されます。')
    ok, err = apply_settings(xml_settings)
    if ok:
        edit_original_response(token, f'再起動しました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
        invoke_notifier(token, ip)
    else:
        edit_original_response(token, f'設定更新に失敗しました: {err}')


def handle_stop(token: str, data: dict) -> None:
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


def handle_status(token: str, data: dict) -> None:
    info = get_instance_state()
    state = info['state']

    state_label = {
        'running':  '起動中',
        'stopped':  '停止中',
        'pending':  '起動処理中',
        'stopping': '停止処理中',
    }.get(state, state)

    if state == 'running' and info['public_ip']:
        ok_v, ver_out = ssm_run(
            [f'cat {INSTALLED_VERSION_FILE} 2>/dev/null || echo unknown'],
            timeout_sec=30,
        )
        installed_ver = ver_out.strip() if ok_v else 'unknown'
        msg = (f'状態: {state_label}\n'
               f'IP: `{info["public_ip"]}:26900`\n'
               f'バージョン: `{installed_ver}`')
    else:
        msg = f'状態: {state_label}'

    edit_original_response(token, msg)


def _format_help_category(title: str, xml_names: list) -> str:
    lines = [f'**{title}**']
    for xml_name in xml_names:
        label, choices = SETTING_LABELS.get(xml_name, (xml_name, None))
        opt_name = XML_TO_OPTION.get(xml_name, xml_name)
        default = SETTING_DEFAULTS.get(xml_name, '?')
        if choices:
            parts = []
            for k, v in choices.items():
                parts.append(f'**{k}={v}**' if str(k) == default else f'{k}={v}')
            lines.append(f'`{opt_name}` {label}: {", ".join(parts)}')
        else:
            lines.append(f'`{opt_name}` {label}: デフォルト **{default}**')
    return '\n'.join(lines)


def handle_help(token: str, data: dict) -> None:
    options = parse_options(data)
    category = options.get('category')

    if category == 'gameplay':
        msg = _format_help_category(
            'ゲームプレイ設定 (`/start` または `/set gameplay`)',
            HELP_CATEGORIES['gameplay'],
        )
    elif category == 'zombies':
        msg = _format_help_category(
            'ゾンビ設定 (`/start` または `/set zombies`)',
            HELP_CATEGORIES['zombies'],
        )
    elif category == 'server':
        msg = _format_help_category(
            'サーバー設定 (`/start` または `/set server`)',
            HELP_CATEGORIES['server'],
        )
    elif category == 'mod':
        msg = """\
**Mod管理コマンド (`/mod`)**

`/mod list`
インストール済みModを有効・無効別に一覧表示。

`/mod add url:<URL> name:<名前>`
ZIP直リンクURLからModをインストールし、サーバーを再起動。
・`url`: ZIPのダウンロードURL (7daystodiemods.com、GitHub Releases 等)
・`name`: Mod名 (英数字・ハイフン・アンダースコア、最大50文字)
ZIP内のフォルダ構造は自動判定。Assembly-CSharp.dll を含む場合はパッチを自動再適用。

`/mod toggle name:<名前>`
Modの有効/無効を切り替えてサーバーを再起動。
有効→無効: ファイルを `Mods.disabled/` に退避 (削除しない)
無効→有効: `Mods/` に戻す

`/mod remove name:<名前>`
指定したModを削除してサーバーを再起動 (有効・無効どちらも可)。

`/mod reset`
全Modを削除してサーバーを再起動。バニラ状態に戻す際に使用。

> Nexus Mods はログインが必要なため URL 指定不可。\
ZIP を手動でEC2に配置 (`/data/7dtd/server/Mods/<名前>/`) してください。"""
    else:
        msg = """\
**設定可能なオプション一覧**

**/start** — 起動時に設定を指定(25オプション、`version` 含む)
**/set gameplay** — XP・BD・ルート・昼夜サイクル・PvP
**/set zombies** — ゾンビ速度・フェラル・ブラッドムーン
**/set server** — サーバー表示・エアドロ・安全ゾーン等
**/settings** — 現在の全設定を表示(サーバー起動中のみ)
**/mod** — Modのインストール・削除・有効無効切り替え

各設定の値とデフォルトを確認:
`/help category:gameplay` `/help category:zombies` `/help category:server`
Modコマンドの詳細: `/help category:mod`

**バージョン切り替え** (`/start version:<値>`)
`latest` — 最新安定版 (デフォルト)
`experimental` — 最新実験的バージョン
`alpha20.7` — Alpha 20.7 (Undead Legacy 対応バージョン)
現在と異なるバージョンを指定するとゲームファイルを再ダウンロードします (20〜40分)。"""
    edit_original_response(token, msg)


def handle_settings(token: str, data: dict) -> None:
    info = get_instance_state()
    if info['state'] != 'running':
        edit_original_response(
            token,
            'サーバーが停止中のため設定を読み取れません。\n'
            '`/start` または `/set` のオプションで設定を変更できます。'
        )
        return

    ok, result = read_settings()
    if not ok:
        edit_original_response(token, f'設定の読み取りに失敗しました: {result}')
        return

    ok_v, ver_out = ssm_run(
        [f'cat {INSTALLED_VERSION_FILE} 2>/dev/null || echo unknown'],
        timeout_sec=30,
    )
    installed_ver = ver_out.strip() if ok_v else 'unknown'
    msg = format_settings_message(result) + f'\n**ゲームバージョン**: `{installed_ver}`'
    edit_original_response(token, msg)


# ─── バージョン管理 ───────────────────────────────────────────────────────────

def launch_version_update(version: str) -> tuple:
    """SteamCMD によるバージョン切り替えをバックグラウンドで起動する。"""
    extra = VERSION_STEAMCMD_ARGS[version]
    sh_script = f"""\
#!/bin/bash
echo "[$(date)] Version update start: {version}"
systemctl stop 7dtd || true
success=false
for attempt in 1 2 3; do
  echo "[INFO] SteamCMD attempt $attempt/3..."
  /opt/steamcmd/steamcmd.sh \\
    +@sSteamCmdForcePlatformType linux \\
    +force_install_dir /data/7dtd/server \\
    +login anonymous \\
    {extra} \\
    +quit
  if [ -f /data/7dtd/server/startserver.sh ]; then
    success=true
    break
  fi
  [ "$attempt" -lt 3 ] && sleep 60
done
if [ "$success" != "true" ]; then
  echo "[ERROR] Download failed"
  exit 1
fi
python3 {PATCH_SCRIPT} || true
echo '{version}' > {INSTALLED_VERSION_FILE}
systemctl start 7dtd
echo "[$(date)] Version update complete: {version}"
"""
    sh_b64 = base64.b64encode(sh_script.encode()).decode()
    commands = [
        f"printf '%s' '{sh_b64}' | base64 -d > /tmp/_7dtd_version_update.sh",
        'chmod +x /tmp/_7dtd_version_update.sh',
        'nohup /tmp/_7dtd_version_update.sh > /var/log/7dtd-version-update.log 2>&1 &',
        'echo "Started: $!"',
    ]
    return ssm_run(commands, timeout_sec=30)


# ─── /mod ────────────────────────────────────────────────────────────────────

def handle_mod(token: str, data: dict) -> None:
    info = get_instance_state()
    if info['state'] != 'running':
        state_label = {'stopped': '停止中', 'pending': '起動処理中', 'stopping': '停止処理中'}.get(info['state'], info['state'])
        edit_original_response(token, f'EC2が{state_label}のためMod操作できません。`/start` で起動してから実行してください。')
        return

    raw = data.get('options', [])
    if not raw:
        edit_original_response(token, 'サブコマンドを指定してください。')
        return
    subcommand = raw[0].get('name')
    sub_opts = {opt['name']: opt['value'] for opt in raw[0].get('options', [])}

    if subcommand == 'list':
        handle_mod_list(token)
    elif subcommand == 'add':
        handle_mod_add(token, sub_opts.get('url', ''), sub_opts.get('name', ''))
    elif subcommand == 'remove':
        handle_mod_remove(token, sub_opts.get('name', ''))
    elif subcommand == 'toggle':
        handle_mod_toggle(token, sub_opts.get('name', ''))
    elif subcommand == 'reset':
        handle_mod_reset(token)
    else:
        edit_original_response(token, f'不明なサブコマンド: `{subcommand}`')


def handle_mod_list(token: str) -> None:
    script = """\
import os
mods = '/data/7dtd/server/Mods'
disabled = '/data/7dtd/server/Mods.disabled'
os.makedirs(mods, exist_ok=True)
os.makedirs(disabled, exist_ok=True)
enabled = sorted(d for d in os.listdir(mods) if os.path.isdir(os.path.join(mods, d)))
dis = sorted(d for d in os.listdir(disabled) if os.path.isdir(os.path.join(disabled, d)))
print('有効: ' + (', '.join(enabled) if enabled else '(なし)'))
print('無効: ' + (', '.join(dis) if dis else '(なし)'))
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_mod_list.py",
        'python3 /tmp/_7dtd_mod_list.py',
        'rm -f /tmp/_7dtd_mod_list.py',
    ]
    ok, output = ssm_run(commands, timeout_sec=30)
    if not ok:
        edit_original_response(token, f'Mod一覧の取得に失敗しました: {output}')
        return
    edit_original_response(token, f'**インストール済みMod**\n{output}')


def handle_mod_add(token: str, url: str, name: str) -> None:
    if not re.match(r'^[a-zA-Z0-9_\-]{1,50}$', name):
        edit_original_response(token, 'Mod名は英数字・ハイフン・アンダースコア(最大50文字)のみ使用できます。')
        return

    edit_original_response(token, f'`{name}` をインストール中...')

    params_b64 = base64.b64encode(json.dumps({'url': url, 'name': name}).encode()).decode()
    script = f"""\
import json, base64, os, sys, shutil, subprocess, urllib.request
p = json.loads(base64.b64decode('{params_b64}').decode())
url, name = p['url'], p['name']
tmp = '/tmp/7dtd_mod_install'
mods_dir = '/data/7dtd/server/Mods/' + name
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp + '/extracted', exist_ok=True)
os.makedirs('/data/7dtd/server/Mods', exist_ok=True)
print('Downloading ' + url)
try:
    req = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0'}})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp + '/mod.zip', 'wb') as f:
        f.write(r.read())
except Exception as e:
    print('ダウンロード失敗: ' + str(e))
    sys.exit(1)
result = subprocess.run(
    ['unzip', '-o', tmp + '/mod.zip', '-d', tmp + '/extracted'],
    capture_output=True, text=True,
)
if result.returncode != 0:
    print('展開失敗: ' + result.stderr)
    sys.exit(1)
mod_dir = None
for root, dirs, files in os.walk(tmp + '/extracted'):
    if 'ModInfo.xml' in files:
        mod_dir = root
        break
if not mod_dir:
    print('ModInfo.xmlが見つかりません (ZIPのフォルダ構造を確認してください)')
    sys.exit(1)
shutil.rmtree(mods_dir, ignore_errors=True)
shutil.copytree(mod_dir, mods_dir)
has_dll = any('Assembly-CSharp.dll' in files for _, _, files in os.walk(mods_dir))
if has_dll:
    r = subprocess.run(['python3', '{PATCH_SCRIPT}'], capture_output=True, text=True)
    if r.returncode != 0:
        print('パッチ失敗: ' + r.stderr)
        sys.exit(1)
    print('Assembly-CSharp.dll を含むModを検出 → パッチ再適用済み')
shutil.rmtree(tmp, ignore_errors=True)
print('インストール完了: ' + name)
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_mod_add.py",
        'python3 /tmp/_7dtd_mod_add.py',
        'rm -f /tmp/_7dtd_mod_add.py',
        'systemctl restart 7dtd',
    ]
    ok, output = ssm_run(commands, timeout_sec=180)
    if not ok:
        edit_original_response(token, f'インストール失敗:\n```\n{output[:1500]}\n```')
        return

    ip = get_instance_state()['public_ip']
    edit_original_response(token, f'`{name}` をインストールしました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
    invoke_notifier(token, ip)


def handle_mod_remove(token: str, name: str) -> None:
    if not re.match(r'^[a-zA-Z0-9_\-]{1,50}$', name):
        edit_original_response(token, 'Mod名は英数字・ハイフン・アンダースコア(最大50文字)のみ使用できます。')
        return

    script = f"""\
import os, sys, shutil
name = '{name}'
mods = '/data/7dtd/server/Mods/' + name
disabled = '/data/7dtd/server/Mods.disabled/' + name
if not os.path.isdir(mods) and not os.path.isdir(disabled):
    print('Modが見つかりません: ' + name)
    sys.exit(1)
shutil.rmtree(mods, ignore_errors=True)
shutil.rmtree(disabled, ignore_errors=True)
print('削除完了: ' + name)
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_mod_remove.py",
        'python3 /tmp/_7dtd_mod_remove.py',
        'rm -f /tmp/_7dtd_mod_remove.py',
        'systemctl restart 7dtd',
    ]
    ok, output = ssm_run(commands, timeout_sec=90)
    if not ok:
        edit_original_response(token, f'削除失敗: {output}')
        return

    ip = get_instance_state()['public_ip']
    edit_original_response(token, f'`{name}` を削除しました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
    invoke_notifier(token, ip)


def handle_mod_toggle(token: str, name: str) -> None:
    if not re.match(r'^[a-zA-Z0-9_\-]{1,50}$', name):
        edit_original_response(token, 'Mod名は英数字・ハイフン・アンダースコア(最大50文字)のみ使用できます。')
        return

    script = f"""\
import os, sys, shutil
name = '{name}'
mods = '/data/7dtd/server/Mods/' + name
disabled = '/data/7dtd/server/Mods.disabled/' + name
os.makedirs('/data/7dtd/server/Mods.disabled', exist_ok=True)
if os.path.isdir(mods):
    shutil.move(mods, disabled)
    print('無効化: ' + name)
elif os.path.isdir(disabled):
    shutil.move(disabled, mods)
    print('有効化: ' + name)
else:
    print('Modが見つかりません: ' + name)
    sys.exit(1)
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_mod_toggle.py",
        'python3 /tmp/_7dtd_mod_toggle.py',
        'rm -f /tmp/_7dtd_mod_toggle.py',
        'systemctl restart 7dtd',
    ]
    ok, output = ssm_run(commands, timeout_sec=90)
    if not ok:
        edit_original_response(token, f'切り替え失敗: {output}')
        return

    ip = get_instance_state()['public_ip']
    action = '無効化' if '無効化' in output else '有効化'
    edit_original_response(token, f'`{name}` を{action}しました。ゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
    invoke_notifier(token, ip)


def handle_mod_reset(token: str) -> None:
    script = """\
import os, shutil
count = 0
for d in ['/data/7dtd/server/Mods', '/data/7dtd/server/Mods.disabled']:
    if os.path.isdir(d):
        for item in os.listdir(d):
            p = os.path.join(d, item)
            if os.path.isdir(p):
                shutil.rmtree(p)
                count += 1
print('全Modを削除しました (' + str(count) + '件)')
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    commands = [
        f"printf '%s' '{script_b64}' | base64 -d > /tmp/_7dtd_mod_reset.py",
        'python3 /tmp/_7dtd_mod_reset.py',
        'rm -f /tmp/_7dtd_mod_reset.py',
        'systemctl restart 7dtd',
    ]
    ok, output = ssm_run(commands, timeout_sec=90)
    if not ok:
        edit_original_response(token, f'リセット失敗: {output}')
        return

    ip = get_instance_state()['public_ip']
    edit_original_response(token, f'{output}\nゲームの準備ができたら通知します。\nIP: `{ip}:26900`')
    invoke_notifier(token, ip)


COMMAND_HANDLERS = {
    'start':    handle_start,
    'set':      handle_set,
    'stop':     handle_stop,
    'status':   handle_status,
    'settings': handle_settings,
    'help':     handle_help,
    'mod':      handle_mod,
}


def handler(event, context):
    token = event.get('token', '')
    command_name = event.get('data', {}).get('name', '')

    fn = COMMAND_HANDLERS.get(command_name)
    if fn is None:
        edit_original_response(token, f'不明なコマンド: `{command_name}`')
        return

    try:
        fn(token, event.get('data', {}))
    except Exception as e:
        print(f"Error handling '{command_name}': {e}")
        try:
            edit_original_response(token, f'エラーが発生しました: {e}')
        except Exception:
            pass
