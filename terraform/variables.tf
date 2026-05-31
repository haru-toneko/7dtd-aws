variable "aws_region" {
  description = "AWSリージョン"
  type        = string
  default     = "ap-northeast-1"
}

variable "instance_type" {
  description = "EC2インスタンスタイプ。t3.large(8GB)が2〜6人向け推奨"
  type        = string
  default     = "t3.large"
}

variable "use_spot_instance" {
  description = "スポットインスタンス使用 (約70%削減、まれに中断あり)"
  type        = bool
  default     = false
}

variable "ebs_size_gb" {
  description = "ゲームデータ用EBSサイズ(GB)"
  type        = number
  default     = 30
}

variable "server_name" {
  description = "7DTDサーバー表示名"
  type        = string
  default     = "Friends 7DTD Server"
}

variable "server_password" {
  description = "7DTDサーバー接続パスワード"
  type        = string
  sensitive   = true
}

variable "max_players" {
  description = "最大同時接続プレイヤー数"
  type        = number
  default     = 6
}

variable "game_world" {
  description = "ゲームワールド名 (Pregen06k01/Pregen06k02/Pregen08k01/Pregen08k02/Navezgane) ※RWGはrwgmixerバグで使用不可(7DTD 2.6のみ)"
  type        = string
  default     = "Navezgane"
}

variable "game_name" {
  description = "セーブデータフォルダ名 (UL使用時は 'Undead-Legacy' 推奨)"
  type        = string
  default     = "Undead-Legacy"
}

variable "steam_branch" {
  description = "SteamCMDブランチ。'public'=最新安定版(2.6), 'alpha20.7'=Alpha 20.7(UL 2.6.17対応), 'alpha21.2'=Alpha 21.2"
  type        = string
  default     = "alpha20.7"
}

variable "apply_assembly_patch" {
  description = "Assembly-CSharp.dllパッチを適用するか。7DTD 2.6 Linux専用サーバーのMonoBehaviourバグ対策。Alpha 20.7では不要"
  type        = bool
  default     = false
}

variable "use_bepinex" {
  description = "BepInExを使用するか。Undead Legacy等のBepInEx依存modを使う場合はtrue。BepInEx Doorstopが起動時にAssembly-CSharp.dllをランタイムパッチする"
  type        = bool
  default     = false
}

variable "bepinex_multifolderloader_s3" {
  description = "BepInEx.MultiFolderLoader.dllのS3パス。use_bepinex=trueの場合に必要。Mods/配下のプリパッチャーをロードするBepInEx拡張。例: s3://bucket/BepInEx.MultiFolderLoader.dll"
  type        = string
  default     = ""
}

variable "auto_stop_idle_minutes" {
  description = "プレイヤー0人が続いたら自動停止するまでの分数"
  type        = number
  default     = 30
}

variable "telnet_password" {
  description = "7DTDテレネット(RCON)パスワード"
  type        = string
  sensitive   = true
}

variable "discord_public_key" {
  description = "Discord Application Public Key (署名検証用・公開情報)"
  type        = string
}

variable "discord_application_id" {
  description = "Discord Application ID"
  type        = string
}

variable "discord_bot_token" {
  description = "Discord Bot Token (フォローアップメッセージ送信用)"
  type        = string
  sensitive   = true
}

variable "allowed_discord_user_ids" {
  description = "コマンド実行を許可するDiscord ユーザーID一覧。空リストで全員許可"
  type        = list(string)
  default     = []
}

variable "project_name" {
  description = "リソース命名プレフィックス"
  type        = string
  default     = "7dtd"
}
