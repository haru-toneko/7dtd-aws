locals {
  user_data = base64encode(templatefile("${path.module}/../scripts/user_data.sh", {
    server_name          = var.server_name
    max_players          = var.max_players
    game_world           = var.game_world
    game_name            = var.game_name
    aws_region           = var.aws_region
    steam_branch         = var.steam_branch
    apply_assembly_patch = var.apply_assembly_patch
    ul_assembly_s3_path  = var.ul_assembly_s3_path
  }))
}

# ─── Launch Template (On-Demand または Spot) ────────────────────────────────

resource "aws_launch_template" "game_server" {
  name_prefix   = "${var.project_name}-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.ec2_profile.name
  }

  vpc_security_group_ids = [aws_security_group.game_server.id]

  user_data = local.user_data

  # EBSルートボリューム (OS用 最小サイズ)
  block_device_mappings {
    device_name = "/dev/sda1"
    ebs {
      volume_type           = "gp3"
      volume_size           = 20
      delete_on_termination = true
      encrypted             = true
    }
  }

  # スポットインスタンス設定
  dynamic "instance_market_options" {
    for_each = var.use_spot_instance ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = "stop"
        spot_instance_type             = "persistent"
      }
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2
    http_put_response_hop_limit = 1
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name    = "${var.project_name}-game-server"
      Project = "7dtd-server"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name    = "${var.project_name}-root"
      Project = "7dtd-server"
    }
  }
}

# ─── EC2 Instance ────────────────────────────────────────────────────────────

resource "aws_instance" "game_server" {
  launch_template {
    id      = aws_launch_template.game_server.id
    version = "$Latest"
  }

  # 初回applyは停止状態にならないため、READMEの手順でstopを実行すること

  tags = {
    Name = "${var.project_name}-game-server"
  }

  lifecycle {
    # AMI更新でインスタンスを再作成しない
    ignore_changes = [launch_template]
  }
}

# ─── EBS (ゲームデータ永続化) ────────────────────────────────────────────────

resource "aws_ebs_volume" "game_data" {
  availability_zone = aws_instance.game_server.availability_zone
  size              = var.ebs_size_gb
  type              = "gp3"
  iops              = 3000
  throughput        = 125
  encrypted         = true

  tags = {
    Name = "${var.project_name}-game-data"
  }
}

resource "aws_volume_attachment" "game_data" {
  device_name  = "/dev/sdf"
  volume_id    = aws_ebs_volume.game_data.id
  instance_id  = aws_instance.game_server.id
  force_detach = true

  # EC2停止中でもアタッチ維持（データ保護）
  stop_instance_before_detaching = true
}
