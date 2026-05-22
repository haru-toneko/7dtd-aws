data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Lambda ZIPアーカイブ (build.sh / build.ps1 実行後に生成される)
data "archive_file" "discord_bot" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/discord_bot"
  output_path = "${path.module}/../.build/discord_bot.zip"
}

data "archive_file" "discord_worker" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/discord_worker"
  output_path = "${path.module}/../.build/discord_worker.zip"
}

data "archive_file" "auto_stop" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/auto_stop"
  output_path = "${path.module}/../.build/auto_stop.zip"
}

data "archive_file" "game_ready_notifier" {
  type        = "zip"
  source_dir  = "${path.module}/../.build/game_ready_notifier"
  output_path = "${path.module}/../.build/game_ready_notifier.zip"
}
