"""
Discord Worker Lambda
- start / stop / status / settings / set コマンドを処理
- EC2を起動/停止し、serverconfig.xml をSSM Run Command で書き換える
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

ec2 = boto3.client('ec2', region_name=AWS_REGION)
ssm = boto3.client('ssm', region_name=AWS_REGION)

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
    xml_settings = options_to_xml(options)
    info = get_instance_state()
    state = info['state']

    if state == 'stopping':
        edit_original_response(token, '停止処理中のため少し待ってから再度お試しください。')
        return

    if state not in ('running', 'stopped'):
        edit_original_response(token, f'起動できない状態です: `{state}`')
        return

    if state == 'running':
        if not xml_settings:
            ip = info['public_ip']
            edit_original_response(token, f'サーバーはすでに起動中です。\nIP: `{ip}:26900`')
            return
        edit_original_response(token, '設定を更新してサーバーを再起動しています...\n⚠️ 接続中のプレイヤーは切断されます。')
        ok, err = apply_settings(xml_settings)
        if ok:
            ip = info['public_ip']
            edit_original_response(token, f'設定を更新し再起動しました。\nIP: `{ip}:26900`\n※再起動完了まで1〜2分かかります。')
        else:
            edit_original_response(token, f'設定更新に失敗しました: {err}')
        return

    # stopped → 起動
    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    if xml_settings:
        edit_original_response(token, 'サーバーを起動中... 設定も適用します。')
    else:
        edit_original_response(token, 'サーバーを起動しています... (最大2分かかります)')

    ip = wait_for_state('running', timeout_sec=180)
    if not ip:
        edit_original_response(token, 'タイムアウト: 起動に時間がかかっています。少し待ってから `/status` で確認してください。')
        return

    if xml_settings:
        ok, err = apply_settings(xml_settings)
        if ok:
            edit_original_response(token, f'サーバーが起動し、設定を適用しました!\nIP: `{ip}:26900`\n※ゲームが完全に起動するまでさらに3〜5分かかります。')
        else:
            edit_original_response(token, f'サーバーは起動しましたが設定の適用に失敗しました: {err}\nIP: `{ip}:26900`')
    else:
        edit_original_response(token, f'サーバーが起動しました!\nIP: `{ip}:26900`\n\n※ゲームが完全に起動するまでさらに3〜5分かかります。')


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

    edit_original_response(token, '設定を更新しています...\n⚠️ 接続中のプレイヤーは切断されます。')
    ok, err = apply_settings(xml_settings)
    if ok:
        ip = info['public_ip']
        edit_original_response(token, f'設定を更新しました。サーバーを再起動しています。\nIP: `{ip}:26900`\n※再起動完了まで1〜2分かかります。')
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
        msg = f'状態: {state_label}\nIP: `{info["public_ip"]}:26900`'
    else:
        msg = f'状態: {state_label}'

    edit_original_response(token, msg)


def handle_help(token: str, data: dict) -> None:
    msg = """\
**設定可能なオプション一覧**

**/start** `[オプション]` — 起動時に設定を指定
`difficulty` 難易度(0-5) | `world` マップ | `game_name` セーブ名
`max_players` 最大人数 | `player_killing` PvP | `drop_on_death` / `drop_on_quit` ドロップ
`xp_multiplier` XP倍率% | `party_xp_range` 同盟XP共有範囲(ブロック数)
`block_damage_player` / `block_damage_zombie` / `block_damage_bm` ブロックダメージ%
`day_length` 1日の長さ(分) | `blood_moon_day` BM周期(日)
`loot_abundance` ルート量% | `loot_respawn_days` ルート再生成(日)
`enemy_spawn` 敵スポーン | `enemy_difficulty` 敵強度
`zombie_day` / `zombie_night` ゾンビ速度 | `blood_moon_count` BM最大数 | `max_zombies` 最大数
`server_visibility` 公開設定 | `server_name` サーバー名

**/set gameplay** `[オプション]` — 起動中に変更(7DTD再起動)
`difficulty` `xp_multiplier` `party_xp_range`
`block_damage_player` `block_damage_zombie` `block_damage_bm`
`day_length` `blood_moon_day` `loot_abundance` `loot_respawn_days`
`player_killing` `drop_on_death` `drop_on_quit`

**/set zombies** `[オプション]` — 起動中に変更(7DTD再起動)
`enemy_spawn` `enemy_difficulty`
`zombie_day` `zombie_night` `zombie_bm_speed`
`zombie_feral` `zombie_feral_sense`
`blood_moon_count` `max_zombies` `max_animals`

**/set server** `[オプション]` — 起動中に変更(7DTD再起動)
`server_name` `server_visibility` `max_players`
`airdrop_frequency` `airdrop_marker`
`view_distance` `creative_mode` `persistent_profiles`
`safe_zone_level` `safe_zone_hours`

**/settings** — 現在の全設定を表示(サーバー起動中のみ)
各オプションの詳細説明は `/` を入力してコマンドを選ぶと表示されます。"""
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

    edit_original_response(token, format_settings_message(result))


COMMAND_HANDLERS = {
    'start':    handle_start,
    'set':      handle_set,
    'stop':     handle_stop,
    'status':   handle_status,
    'settings': handle_settings,
    'help':     handle_help,
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
