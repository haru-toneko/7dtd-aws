# ─── Discord Bot Lambda ──────────────────────────────────────────────────────

resource "aws_lambda_function" "discord_bot" {
  function_name    = "${var.project_name}-discord-bot"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.discord_bot.output_path
  source_code_hash = data.archive_file.discord_bot.output_base64sha256
  timeout          = 10
  memory_size      = 1769

  environment {
    variables = {
      DISCORD_PUBLIC_KEY       = var.discord_public_key
      DISCORD_APPLICATION_ID   = var.discord_application_id
      WORKER_LAMBDA_ARN        = aws_lambda_function.discord_worker.arn
      ALLOWED_DISCORD_USER_IDS = join(",", var.allowed_discord_user_ids)
    }
  }

  depends_on = [data.archive_file.discord_bot]
}

# ─── Discord Worker Lambda (非同期処理) ─────────────────────────────────────

resource "aws_lambda_function" "discord_worker" {
  function_name    = "${var.project_name}-discord-worker"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.discord_worker.output_path
  source_code_hash = data.archive_file.discord_worker.output_base64sha256
  timeout          = 300
  memory_size      = 256

  environment {
    variables = {
      INSTANCE_ID            = aws_instance.game_server.id
      AWS_ACCOUNT_REGION     = var.aws_region
      DISCORD_APPLICATION_ID = var.discord_application_id
      BOT_TOKEN_PARAM        = aws_ssm_parameter.discord_bot_token.name
      NOTIFIER_LAMBDA_ARN    = aws_lambda_function.game_ready_notifier.arn
    }
  }

  depends_on = [data.archive_file.discord_worker]
}

# ─── Auto Stop Lambda ────────────────────────────────────────────────────────

resource "aws_lambda_function" "auto_stop" {
  function_name    = "${var.project_name}-auto-stop"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.auto_stop.output_path
  source_code_hash = data.archive_file.auto_stop.output_base64sha256
  timeout          = 120
  memory_size      = 128

  environment {
    variables = {
      INSTANCE_ID             = aws_instance.game_server.id
      IDLE_THRESHOLD_MINUTES  = tostring(var.auto_stop_idle_minutes)
      CHECK_INTERVAL_MINUTES  = "5"
      IDLE_PARAM_NAME         = aws_ssm_parameter.idle_minutes.name
      TELNET_PASSWORD_PARAM   = aws_ssm_parameter.telnet_password.name
    }
  }

  depends_on = [data.archive_file.auto_stop]
}

# ─── Game Ready Notifier Lambda ─────────────────────────────────────────────

resource "aws_lambda_function" "game_ready_notifier" {
  function_name    = "${var.project_name}-game-ready-notifier"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.game_ready_notifier.output_path
  source_code_hash = data.archive_file.game_ready_notifier.output_base64sha256
  timeout          = 900
  memory_size      = 128

  environment {
    variables = {
      INSTANCE_ID            = aws_instance.game_server.id
      AWS_ACCOUNT_REGION     = var.aws_region
      DISCORD_APPLICATION_ID = var.discord_application_id
      BOT_TOKEN_PARAM        = aws_ssm_parameter.discord_bot_token.name
    }
  }

  depends_on = [data.archive_file.game_ready_notifier]
}

# ─── CloudWatch Log Groups ───────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "discord_bot" {
  name              = "/aws/lambda/${aws_lambda_function.discord_bot.function_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "discord_worker" {
  name              = "/aws/lambda/${aws_lambda_function.discord_worker.function_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "auto_stop" {
  name              = "/aws/lambda/${aws_lambda_function.auto_stop.function_name}"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "game_ready_notifier" {
  name              = "/aws/lambda/${aws_lambda_function.game_ready_notifier.function_name}"
  retention_in_days = 7
}
