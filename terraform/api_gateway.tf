# HTTP API (REST APIより安い)
resource "aws_apigatewayv2_api" "discord" {
  name          = "${var.project_name}-discord-webhook"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "discord_bot" {
  api_id                 = aws_apigatewayv2_api.discord.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.discord_bot.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "discord_post" {
  api_id    = aws_apigatewayv2_api.discord.id
  route_key = "POST /discord"
  target    = "integrations/${aws_apigatewayv2_integration.discord_bot.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.discord.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.discord_bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.discord.execution_arn}/*/*"
}
