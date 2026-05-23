#!/usr/bin/env python3
"""
Discord スラッシュコマンド登録スクリプト

使い方:
  export DISCORD_APP_ID=your_app_id
  export DISCORD_BOT_TOKEN=your_bot_token
  python3 scripts/register_commands.py --guild GUILD_ID   # 即時反映
  python3 scripts/register_commands.py                    # グローバル (最大1時間)

オプション:
  --guild GUILD_ID  ギルドコマンドとして登録（即時反映）
  --list            登録済みコマンドを一覧表示
  --delete          全コマンドを削除
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

DISCORD_API = 'https://discord.com/api/v10'

# ─── 共通選択肢 ───────────────────────────────────────────────────────────────

ZOMBIE_SPEED_CHOICES = [
    {'name': '0: Walk (歩き)',      'value': 0},
    {'name': '1: Jog (小走り)',     'value': 1},
    {'name': '2: Run (走り)',       'value': 2},
    {'name': '3: Sprint (全力)',    'value': 3},
    {'name': '4: Nightmare (最速)', 'value': 4},
]

DROP_CHOICES = [
    {'name': '0: なし',             'value': 0},
    {'name': '1: 全部',             'value': 1},
    {'name': '2: ツールベルトのみ', 'value': 2},
    {'name': '3: バックパックのみ', 'value': 3},
    {'name': '4: 全削除',           'value': 4},
]

FERAL_TIMING_CHOICES = [
    {'name': '0: なし',   'value': 0},
    {'name': '1: 昼のみ', 'value': 1},
    {'name': '2: 夜のみ', 'value': 2},
    {'name': '3: 常時',   'value': 3},
]

# ─── /start オプション (最大25) ───────────────────────────────────────────────
# ゲーム起動時に指定することが多い設定を収録

START_OPTIONS = [
    # ゲーム基本
    {
        'name': 'difficulty',
        'description': 'ゲーム難易度',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: Scavenger (最易)', 'value': 0},
            {'name': '1: Adventurer',       'value': 1},
            {'name': '2: Nomad (普通)',      'value': 2},
            {'name': '3: Warrior',          'value': 3},
            {'name': '4: Survivalist',      'value': 4},
            {'name': '5: Insane (最難)',     'value': 5},
        ],
    },
    {
        'name': 'world',
        'description': 'ゲームワールド (マップ)',
        'type': 3,
        'required': False,
        'choices': [
            {'name': 'Pregen08k01 (8k 推奨)', 'value': 'Pregen08k01'},
            {'name': 'Pregen08k02 (8k)',       'value': 'Pregen08k02'},
            {'name': 'Pregen06k01 (6k)',       'value': 'Pregen06k01'},
            {'name': 'Pregen06k02 (6k)',       'value': 'Pregen06k02'},
            {'name': 'Navezgane (固定マップ)', 'value': 'Navezgane'},
        ],
    },
    {
        'name': 'game_name',
        'description': 'セーブデータ名 (変更すると別ゲームとして扱われます)',
        'type': 3,
        'required': False,
    },
    # プレイヤー設定
    {
        'name': 'max_players',
        'description': '最大プレイヤー数 (1〜8)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 8,
    },
    {
        'name': 'player_killing',
        'description': 'PvP設定',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: PvPオフ',          'value': 0},
            {'name': '1: 同陣営のみ攻撃可', 'value': 1},
            {'name': '2: 他陣営のみ攻撃可', 'value': 2},
            {'name': '3: 全員攻撃可',       'value': 3},
        ],
    },
    {
        'name': 'drop_on_death',
        'description': '死亡時のアイテムドロップ',
        'type': 4,
        'required': False,
        'choices': DROP_CHOICES,
    },
    {
        'name': 'drop_on_quit',
        'description': 'ログアウト時のアイテムドロップ',
        'type': 4,
        'required': False,
        'choices': DROP_CHOICES,
    },
    # 経験値
    {
        'name': 'xp_multiplier',
        'description': 'XP獲得量の倍率 % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'party_xp_range',
        'description': '同盟プレイヤーのキルでXPを共有する範囲 (ブロック数、0=無効、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 1000,
    },
    # ブロックダメージ
    {
        'name': 'block_damage_player',
        'description': 'プレイヤーが与えるブロックダメージ % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'block_damage_zombie',
        'description': 'ゾンビが与えるブロックダメージ % (0〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 500,
    },
    {
        'name': 'block_damage_bm',
        'description': 'ブラッドムーンゾンビのブロックダメージ % (0〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 500,
    },
    # 昼夜サイクル
    {
        'name': 'day_length',
        'description': '1日の長さ (リアル分、8〜900、デフォルト60)',
        'type': 4,
        'required': False,
        'min_value': 8,
        'max_value': 900,
    },
    {
        'name': 'blood_moon_day',
        'description': 'ブラッドムーンの間隔 (日数、1〜100、デフォルト7)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 100,
    },
    # ルート
    {
        'name': 'loot_abundance',
        'description': 'ルートの量 % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'loot_respawn_days',
        'description': 'ルート再生成までの日数 (0=なし、デフォルト30)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 365,
    },
    # ゾンビ
    {
        'name': 'enemy_spawn',
        'description': '敵(ゾンビ・動物)のスポーン有無',
        'type': 5,
        'required': False,
    },
    {
        'name': 'enemy_difficulty',
        'description': '敵の強さ',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: Normal (通常)',    'value': 0},
            {'name': '1: Feral (フェラル)', 'value': 1},
        ],
    },
    {
        'name': 'zombie_day',
        'description': '昼のゾンビ移動速度',
        'type': 4,
        'required': False,
        'choices': ZOMBIE_SPEED_CHOICES,
    },
    {
        'name': 'zombie_night',
        'description': '夜のゾンビ移動速度',
        'type': 4,
        'required': False,
        'choices': ZOMBIE_SPEED_CHOICES,
    },
    {
        'name': 'blood_moon_count',
        'description': 'ブラッドムーン中の最大ゾンビ数 (1〜64、デフォルト8)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 64,
    },
    {
        'name': 'max_zombies',
        'description': 'サーバー全体の最大同時ゾンビ数 (1〜64、デフォルト64)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 64,
    },
    # サーバー表示
    {
        'name': 'server_visibility',
        'description': 'サーバーリスト公開設定',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: 非公開',       'value': 0},
            {'name': '1: フレンドのみ', 'value': 1},
            {'name': '2: 公開',         'value': 2},
        ],
    },
    {
        'name': 'server_name',
        'description': 'サーバー表示名',
        'type': 3,
        'required': False,
    },
]

# ─── /set サブコマンドのオプション定義 ───────────────────────────────────────

SET_GAMEPLAY_OPTIONS = [
    {
        'name': 'difficulty',
        'description': 'ゲーム難易度 (0=Scavenger 〜 5=Insane)',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: Scavenger (最易)', 'value': 0},
            {'name': '1: Adventurer',       'value': 1},
            {'name': '2: Nomad (普通)',      'value': 2},
            {'name': '3: Warrior',          'value': 3},
            {'name': '4: Survivalist',      'value': 4},
            {'name': '5: Insane (最難)',     'value': 5},
        ],
    },
    {
        'name': 'xp_multiplier',
        'description': 'XP獲得量の倍率 % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'party_xp_range',
        'description': '同盟プレイヤーのキルでXPを共有する範囲 (ブロック数、0=無効、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 1000,
    },
    {
        'name': 'block_damage_player',
        'description': 'プレイヤーが与えるブロックダメージ % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'block_damage_zombie',
        'description': 'ゾンビが与えるブロックダメージ % (0〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 500,
    },
    {
        'name': 'block_damage_bm',
        'description': 'ブラッドムーンゾンビのブロックダメージ % (0〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 500,
    },
    {
        'name': 'day_length',
        'description': '1日の長さ (リアル分、8〜900、デフォルト60)',
        'type': 4,
        'required': False,
        'min_value': 8,
        'max_value': 900,
    },
    {
        'name': 'blood_moon_day',
        'description': 'ブラッドムーンの間隔 (日数、1〜100、デフォルト7)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 100,
    },
    {
        'name': 'loot_abundance',
        'description': 'ルートの量 % (25〜500、デフォルト100)',
        'type': 4,
        'required': False,
        'min_value': 25,
        'max_value': 500,
    },
    {
        'name': 'loot_respawn_days',
        'description': 'ルート再生成までの日数 (0=なし、デフォルト30)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 365,
    },
    {
        'name': 'player_killing',
        'description': 'PvP設定',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: PvPオフ',          'value': 0},
            {'name': '1: 同陣営のみ攻撃可', 'value': 1},
            {'name': '2: 他陣営のみ攻撃可', 'value': 2},
            {'name': '3: 全員攻撃可',       'value': 3},
        ],
    },
    {
        'name': 'drop_on_death',
        'description': '死亡時のアイテムドロップ',
        'type': 4,
        'required': False,
        'choices': DROP_CHOICES,
    },
    {
        'name': 'drop_on_quit',
        'description': 'ログアウト時のアイテムドロップ',
        'type': 4,
        'required': False,
        'choices': DROP_CHOICES,
    },
]

SET_ZOMBIES_OPTIONS = [
    {
        'name': 'enemy_spawn',
        'description': '敵(ゾンビ・動物)のスポーン有無',
        'type': 5,
        'required': False,
    },
    {
        'name': 'enemy_difficulty',
        'description': '敵の強さ',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: Normal (通常)',    'value': 0},
            {'name': '1: Feral (フェラル)', 'value': 1},
        ],
    },
    {
        'name': 'zombie_day',
        'description': '昼のゾンビ移動速度',
        'type': 4,
        'required': False,
        'choices': ZOMBIE_SPEED_CHOICES,
    },
    {
        'name': 'zombie_night',
        'description': '夜のゾンビ移動速度',
        'type': 4,
        'required': False,
        'choices': ZOMBIE_SPEED_CHOICES,
    },
    {
        'name': 'zombie_bm_speed',
        'description': 'ブラッドムーン中のゾンビ移動速度',
        'type': 4,
        'required': False,
        'choices': ZOMBIE_SPEED_CHOICES,
    },
    {
        'name': 'zombie_feral',
        'description': 'フェラルゾンビの出現タイミング',
        'type': 4,
        'required': False,
        'choices': FERAL_TIMING_CHOICES,
    },
    {
        'name': 'zombie_feral_sense',
        'description': 'フェラルゾンビの感知範囲強化タイミング',
        'type': 4,
        'required': False,
        'choices': FERAL_TIMING_CHOICES,
    },
    {
        'name': 'blood_moon_count',
        'description': 'ブラッドムーン中の最大ゾンビ数 (1〜64、デフォルト8)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 64,
    },
    {
        'name': 'max_zombies',
        'description': 'サーバー全体の最大同時ゾンビ数 (1〜64、デフォルト64)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 64,
    },
    {
        'name': 'max_animals',
        'description': 'サーバー全体の最大同時動物数 (1〜50、デフォルト50)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 50,
    },
]

SET_SERVER_OPTIONS = [
    {
        'name': 'server_name',
        'description': 'サーバー表示名',
        'type': 3,
        'required': False,
    },
    {
        'name': 'server_visibility',
        'description': 'サーバーリスト公開設定',
        'type': 4,
        'required': False,
        'choices': [
            {'name': '0: 非公開',       'value': 0},
            {'name': '1: フレンドのみ', 'value': 1},
            {'name': '2: 公開',         'value': 2},
        ],
    },
    {
        'name': 'max_players',
        'description': '最大プレイヤー数 (1〜8)',
        'type': 4,
        'required': False,
        'min_value': 1,
        'max_value': 8,
    },
    {
        'name': 'airdrop_frequency',
        'description': 'エアドロップの間隔 (ゲーム内時間/時間、0=無効、デフォルト72)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 720,
    },
    {
        'name': 'airdrop_marker',
        'description': 'エアドロップのマップマーカーを表示するか',
        'type': 5,
        'required': False,
    },
    {
        'name': 'view_distance',
        'description': '最大視野距離 (chunk数、6〜12、デフォルト12)',
        'type': 4,
        'required': False,
        'min_value': 6,
        'max_value': 12,
    },
    {
        'name': 'creative_mode',
        'description': 'クリエイティブモード(チートメニュー)の有効化',
        'type': 5,
        'required': False,
    },
    {
        'name': 'persistent_profiles',
        'description': 'プレイヤープロファイルをゲーム難易度に固定する',
        'type': 5,
        'required': False,
    },
    {
        'name': 'safe_zone_level',
        'description': '安全ゾーンが有効なプレイヤーレベル上限 (0=無効、デフォルト5)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 20,
    },
    {
        'name': 'safe_zone_hours',
        'description': '安全ゾーンが有効なゲーム内経過時間上限 (0=無効、デフォルト5)',
        'type': 4,
        'required': False,
        'min_value': 0,
        'max_value': 48,
    },
]

# ─── コマンド定義 ─────────────────────────────────────────────────────────────

MOD_COMMAND = {
    'name': 'mod',
    'description': 'Modの管理 (インストール・削除・有効/無効切り替え・リセット)',
    'options': [
        {
            'name': 'list',
            'description': 'インストール済みModの一覧を表示します',
            'type': 1,
        },
        {
            'name': 'add',
            'description': 'ModをURLからインストールします (ZIP直リンク、サーバー再起動)',
            'type': 1,
            'options': [
                {
                    'name': 'url',
                    'description': 'ModのダウンロードURL (ZIP直リンク)',
                    'type': 3,
                    'required': True,
                },
                {
                    'name': 'name',
                    'description': 'Mod名 (英数字・ハイフン・アンダースコア、最大50文字)',
                    'type': 3,
                    'required': True,
                },
            ],
        },
        {
            'name': 'remove',
            'description': '指定したModを削除します (サーバー再起動)',
            'type': 1,
            'options': [
                {
                    'name': 'name',
                    'description': '削除するMod名',
                    'type': 3,
                    'required': True,
                },
            ],
        },
        {
            'name': 'toggle',
            'description': '指定したModの有効/無効を切り替えます (サーバー再起動)',
            'type': 1,
            'options': [
                {
                    'name': 'name',
                    'description': '切り替えるMod名',
                    'type': 3,
                    'required': True,
                },
            ],
        },
        {
            'name': 'reset',
            'description': '全Modを削除します (サーバー再起動)',
            'type': 1,
        },
    ],
}

COMMANDS = [
    {
        'name': 'start',
        'description': '7DTDサーバーを起動します。オプションで設定を上書きできます。',
        'options': START_OPTIONS,
    },
    {
        'name': 'set',
        'description': '起動中サーバーの設定を変更します (7DTDを再起動します)。',
        'options': [
            {
                'name': 'gameplay',
                'description': 'XP・ブロックダメージ・ルート・昼夜サイクルなどゲームプレイ設定',
                'type': 1,  # SUB_COMMAND
                'options': SET_GAMEPLAY_OPTIONS,
            },
            {
                'name': 'zombies',
                'description': 'ゾンビのスポーン・速度・フェラル・ブラッドムーン関連設定',
                'type': 1,  # SUB_COMMAND
                'options': SET_ZOMBIES_OPTIONS,
            },
            {
                'name': 'server',
                'description': 'エアドロップ・安全ゾーン・視野距離・クリエイティブモードなどサーバー設定',
                'type': 1,  # SUB_COMMAND
                'options': SET_SERVER_OPTIONS,
            },
        ],
    },
    {
        'name': 'help',
        'description': '設定可能なオプションを一覧表示します。カテゴリを指定すると値とデフォルトも表示します。',
        'options': [
            {
                'name': 'category',
                'description': '詳細を表示するカテゴリ',
                'type': 3,
                'required': False,
                'choices': [
                    {'name': 'gameplay — 難易度・XP・ルート・昼夜サイクル等', 'value': 'gameplay'},
                    {'name': 'zombies — ゾンビ速度・フェラル・ブラッドムーン等', 'value': 'zombies'},
                    {'name': 'server — サーバー表示・エアドロ・安全ゾーン等',   'value': 'server'},
                    {'name': 'mod — Modインストール・削除・有効無効切り替え',   'value': 'mod'},
                ],
            },
        ],
    },
    {
        'name': 'stop',
        'description': '7DTDサーバーを停止します。',
    },
    {
        'name': 'status',
        'description': 'サーバーの起動状態とIPアドレスを表示します。',
    },
    {
        'name': 'settings',
        'description': '現在のゲーム設定を表示します (サーバー起動中のみ)。',
    },
    MOD_COMMAND,
]

# ─── Discord API ──────────────────────────────────────────────────────────────

def api_request(method: str, path: str, bot_token: str, payload=None):
    url = f'{DISCORD_API}{path}'
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            'Authorization': f'Bot {bot_token}',
            'Content-Type': 'application/json',
            'User-Agent': 'DiscordBot (https://github.com/example/7dtd-bot, 1.0)',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return e.code, json.loads(body) if body else None

# ─── 操作 ─────────────────────────────────────────────────────────────────────

def register_commands(app_id: str, bot_token: str, guild_id: str | None) -> None:
    if guild_id:
        path = f'/applications/{app_id}/guilds/{guild_id}/commands'
        scope = f'ギルド {guild_id}'
    else:
        path = f'/applications/{app_id}/commands'
        scope = 'グローバル'

    print(f'コマンドを登録中 ({scope})...')
    status, resp = api_request('PUT', path, bot_token, COMMANDS)
    if status in (200, 201):
        print(f'✓ {len(resp)} 件登録完了:')
        for cmd in resp:
            opts = cmd.get('options', [])
            sub_count = sum(1 for o in opts if o.get('type') == 1)
            opt_count = sum(1 for o in opts if o.get('type') != 1)
            if sub_count:
                print(f'  /{cmd["name"]} — {sub_count} サブコマンド')
            else:
                print(f'  /{cmd["name"]} — {opt_count} オプション')
        if not guild_id:
            print('\n注意: グローバルコマンドの反映には最大1時間かかります。')
            print('      即時確認したい場合は --guild GUILD_ID を指定してください。')
    else:
        print(f'✗ エラー ({status}):')
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        sys.exit(1)


def list_commands(app_id: str, bot_token: str, guild_id: str | None) -> None:
    if guild_id:
        path = f'/applications/{app_id}/guilds/{guild_id}/commands'
        scope = f'ギルド {guild_id}'
    else:
        path = f'/applications/{app_id}/commands'
        scope = 'グローバル'

    status, resp = api_request('GET', path, bot_token)
    if status == 200:
        print(f'登録済みコマンド ({scope}): {len(resp)} 件')
        for cmd in resp:
            print(f'\n  /{cmd["name"]} — {cmd["description"]}')
            for opt in cmd.get('options', []):
                if opt.get('type') == 1:  # SUB_COMMAND
                    print(f'    [{opt["name"]}] {opt["description"]}')
                    for sub_opt in opt.get('options', []):
                        req = ' [必須]' if sub_opt.get('required') else ''
                        print(f'      --{sub_opt["name"]}{req}: {sub_opt["description"]}')
                else:
                    req = ' [必須]' if opt.get('required') else ''
                    print(f'    --{opt["name"]}{req}: {opt["description"]}')
    else:
        print(f'エラー ({status}): {json.dumps(resp, ensure_ascii=False)}')
        sys.exit(1)


def delete_commands(app_id: str, bot_token: str, guild_id: str | None) -> None:
    if guild_id:
        path = f'/applications/{app_id}/guilds/{guild_id}/commands'
        scope = f'ギルド {guild_id}'
    else:
        path = f'/applications/{app_id}/commands'
        scope = 'グローバル'

    print(f'コマンドを削除中 ({scope})...')
    status, _ = api_request('PUT', path, bot_token, [])
    if status == 200:
        print('✓ 全コマンドを削除しました。')
    else:
        print(f'✗ エラー ({status})')
        sys.exit(1)

# ─── エントリポイント ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Discord スラッシュコマンドを登録する')
    parser.add_argument('--guild', metavar='GUILD_ID', help='ギルドIDを指定してギルドコマンドとして登録 (即時反映)')
    parser.add_argument('--list',   action='store_true', help='登録済みコマンドを一覧表示')
    parser.add_argument('--delete', action='store_true', help='全コマンドを削除')
    args = parser.parse_args()

    app_id    = os.environ.get('DISCORD_APP_ID')
    bot_token = os.environ.get('DISCORD_BOT_TOKEN')

    if not app_id or not bot_token:
        print('エラー: DISCORD_APP_ID と DISCORD_BOT_TOKEN を環境変数に設定してください。')
        print()
        print('例:')
        print('  export DISCORD_APP_ID=your_app_id')
        print('  export DISCORD_BOT_TOKEN=your_bot_token')
        print('  python3 scripts/register_commands.py --guild YOUR_GUILD_ID')
        sys.exit(1)

    if args.list:
        list_commands(app_id, bot_token, args.guild)
    elif args.delete:
        delete_commands(app_id, bot_token, args.guild)
    else:
        register_commands(app_id, bot_token, args.guild)


if __name__ == '__main__':
    main()
