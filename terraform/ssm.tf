# ─── Secrets (SecureString) ─────────────────────────────────────────────────

resource "aws_ssm_parameter" "server_password" {
  name  = "/7dtd/server-password"
  type  = "SecureString"
  value = var.server_password

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "telnet_password" {
  name  = "/7dtd/telnet-password"
  type  = "SecureString"
  value = var.telnet_password

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "discord_bot_token" {
  name  = "/7dtd/discord-bot-token"
  type  = "SecureString"
  value = var.discord_bot_token

  lifecycle {
    ignore_changes = [value]
  }
}

# ─── Runtime State ──────────────────────────────────────────────────────────

resource "aws_ssm_parameter" "idle_minutes" {
  name  = "/7dtd/idle-minutes"
  type  = "String"
  value = "0"

  lifecycle {
    ignore_changes = [value]
  }
}
