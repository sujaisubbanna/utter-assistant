cask "utter" do
  arch arm: "aarch64", intel: "x86_64"

  version "0.2.0"
  sha256 :no_check

  url "https://github.com/sujaisubbanna/utter-assistant/releases/download/v#{version}/utter-gui_#{version}_#{arch}.dmg"
  name "Utter"
  desc "Local, offline voice to desktop-action assistant"
  homepage "https://github.com/sujaisubbanna/utter-assistant"

  auto_updates false
  depends_on macos: ">= :monterey"

  app "utter.app"

  postflight do
    system_command "/usr/bin/xattr",
                   args: ["-cr", "#{appdir}/utter.app"],
                   sudo: false
  end

  zap trash: [
    "~/.config/utter",
    "~/Library/Application Support/utter",
    "~/Library/LaunchAgents/com.utter.assistant.plist",
    "~/Library/LaunchAgents/com.utter.runner.plist",
    "~/Library/Logs/utter",
    "~/Library/Preferences/com.utter.app.plist",
  ]
end
