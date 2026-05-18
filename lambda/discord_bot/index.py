"""
Discord Interactions エンドポイント Lambda
Ed25519署名検証: 外部ライブラリ不要のpure Python (アフィン座標系・参照実装準拠)
"""
import hashlib
import json
import logging
import os
import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

DISCORD_PUBLIC_KEY = os.environ['DISCORD_PUBLIC_KEY']
WORKER_LAMBDA_ARN = os.environ['WORKER_LAMBDA_ARN']
ALLOWED_USER_IDS = set(filter(None, os.environ.get('ALLOWED_DISCORD_USER_IDS', '').split(',')))

lambda_client = boto3.client('lambda')

INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
RESPONSE_PONG = 1
RESPONSE_DEFERRED_MESSAGE = 5

# ─── Pure Python Ed25519 (affine coords, reference impl準拠) ──────────────────
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_BY = 4 * pow(5, _Q - 2, _Q) % _Q
_BX = None  # 遅延初期化


def _xrecover(y):
    xx = (y * y - 1) * pow(_D * y * y + 1, _Q - 2, _Q) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = x * _I % _Q
    if x & 1:
        x = _Q - x
    return x


def _point_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    dxy = _D * x1 * x2 * y1 * y2 % _Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + dxy, _Q - 2, _Q) % _Q
    y3 = (y1 * y2 + x1 * x2) * pow(1 - dxy, _Q - 2, _Q) % _Q
    return (x3, y3)


def _scalarmult(P, n):
    if n == 0:
        return (0, 1)
    Q = _scalarmult(P, n >> 1)
    Q = _point_add(Q, Q)
    if n & 1:
        Q = _point_add(Q, P)
    return Q


def _encode_point(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes([sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32)])


def _decode_point(s):
    y = int.from_bytes(s, 'little') & ((1 << 255) - 1)
    x = _xrecover(y)
    if x & 1 != s[31] >> 7:
        x = _Q - x
    return (x % _Q, y % _Q)


def _get_base():
    global _BX
    if _BX is None:
        _BX = _xrecover(_BY)
    return (_BX, _BY)


def _verify_ed25519(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    try:
        pk = bytes.fromhex(public_key_hex)
        sig = bytes.fromhex(signature_hex)
        if len(sig) != 64 or len(pk) != 32:
            return False
        R = _decode_point(sig[:32])
        S = int.from_bytes(sig[32:], 'little')
        if S >= _L:
            return False
        A = _decode_point(pk)
        B = _get_base()
        k = int.from_bytes(
            hashlib.sha512(_encode_point(R) + pk + message).digest(), 'little'
        )
        return _scalarmult(B, S) == _point_add(R, _scalarmult(A, k))
    except Exception as e:
        log.error(f"Ed25519 verify error: {e}")
        return False


# ─── RFC 8032 Test Vector で実装を自己検証 ────────────────────────────────────
def _self_test() -> bool:
    pk  = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
           "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    ok = _verify_ed25519(pk, sig, b"")
    if not ok:
        log.error("Ed25519 self-test FAILED")
    else:
        log.info("Ed25519 self-test passed")
    return ok

_SELF_TEST_OK = _self_test()

# ─────────────────────────────────────────────────────────────────────────────


def handler(event, context):
    if not _SELF_TEST_OK:
        return {'statusCode': 500, 'body': 'Internal error'}

    headers = {k.lower(): v for k, v in event.get('headers', {}).items()}
    signature = headers.get('x-signature-ed25519', '')
    timestamp = headers.get('x-signature-timestamp', '')
    body = event.get('body') or ''

    if event.get('isBase64Encoded'):
        import base64
        body = base64.b64decode(body).decode('utf-8')

    log.info(f"sig={signature[:16]}... ts={timestamp!r} body={body[:80]!r}")

    if not _verify_ed25519(DISCORD_PUBLIC_KEY, signature, (timestamp + body).encode()):
        return {'statusCode': 401, 'body': 'Invalid signature'}

    interaction = json.loads(body)
    interaction_type = interaction.get('type')

    if interaction_type == INTERACTION_PING:
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'type': RESPONSE_PONG}),
        }

    if interaction_type == INTERACTION_APPLICATION_COMMAND:
        user_id = (
            interaction.get('member', {}).get('user', {}).get('id')
            or interaction.get('user', {}).get('id', '')
        )
        if ALLOWED_USER_IDS and user_id not in ALLOWED_USER_IDS:
            return {
                'statusCode': 200,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'type': 4, 'data': {'content': '権限がありません。', 'flags': 64}}),
            }

        lambda_client.invoke(
            FunctionName=WORKER_LAMBDA_ARN,
            InvocationType='Event',
            Payload=json.dumps(interaction).encode(),
        )
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'type': RESPONSE_DEFERRED_MESSAGE}),
        }

    return {'statusCode': 400, 'body': 'Unknown interaction type'}
