# ─── EventBridge: 5分ごとにauto_stopを起動 ──────────────────────────────────

resource "aws_cloudwatch_event_rule" "auto_stop" {
  name                = "${var.project_name}-auto-stop"
  description         = "5分ごとにプレイヤー数チェック→無人なら自動停止"
  schedule_expression = "rate(5 minutes)"
  state               = "ENABLED"
}

resource "aws_cloudwatch_event_target" "auto_stop" {
  rule      = aws_cloudwatch_event_rule.auto_stop.name
  target_id = "AutoStopLambda"
  arn       = aws_lambda_function.auto_stop.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auto_stop.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.auto_stop.arn
}

# ─── CloudWatch Alarm: CPU低下フォールバック ─────────────────────────────────
# RCONが取れない場合の保険。CPU < 3% が 60分続いたらアラーム

resource "aws_cloudwatch_metric_alarm" "cpu_fallback_stop" {
  alarm_name          = "${var.project_name}-cpu-idle-fallback"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 12
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 3
  alarm_description   = "CPU < 3% が60分継続 → フォールバック自動停止"
  alarm_actions       = [aws_lambda_function.auto_stop.arn]
  ok_actions          = []

  dimensions = {
    InstanceId = aws_instance.game_server.id
  }

  treat_missing_data = "notBreaching"
}

resource "aws_lambda_permission" "allow_cloudwatch_alarm" {
  statement_id  = "AllowCloudWatchAlarmInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auto_stop.function_name
  principal     = "lambda.alarms.cloudwatch.amazonaws.com"
  source_arn    = aws_cloudwatch_metric_alarm.cpu_fallback_stop.arn
}
