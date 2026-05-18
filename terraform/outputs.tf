output "discord_webhook_url" {
  description = "DiscordのInteractions Endpoint URLに設定するURL"
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/discord"
}

output "instance_id" {
  description = "EC2インスタンスID"
  value       = aws_instance.game_server.id
}

output "game_data_volume_id" {
  description = "ゲームデータEBSボリュームID"
  value       = aws_ebs_volume.game_data.id
}