resource "aws_security_group" "game_server" {
  name        = "${var.project_name}-game-server"
  description = "7DTD game server - game ports only, no SSH"

  # 7DTD ゲームポート (TCP)
  ingress {
    description = "7DTD game TCP"
    from_port   = 26900
    to_port     = 26900
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 7DTD ゲームポート (UDP 26900-26902)
  ingress {
    description = "7DTD game UDP"
    from_port   = 26900
    to_port     = 26902
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # 全アウトバウンド (SteamCMD, SSM, CloudWatch等)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-game-server"
  }
}
