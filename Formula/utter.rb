# typed: false
# frozen_string_literal: true

class Utter < Formula
  include Language::Python::Virtualenv

  desc "Local, offline, context-aware voice to desktop-action assistant"
  homepage "https://github.com/sujaisubbanna/utter-assistant"
  url "https://github.com/sujaisubbanna/utter-assistant/archive/refs/tags/v0.4.3.tar.gz"
  license "Apache-2.0"
  head "https://github.com/sujaisubbanna/utter-assistant.git", branch: "main"

  depends_on "portaudio"
  depends_on "python@3.12"
  depends_on :macos

  def install
    # Install Python package and its dependencies into libexec virtualenv
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install_and_link(buildpath)

    # Binaries linked to Homebrew's bin
    bin.install_symlink libexec/"bin/utter" if (libexec/"bin/utter").exist?
    bin.install_symlink libexec/"bin/utter-runner" if (libexec/"bin/utter-runner").exist?

    # Install launchd agent templates into share/utter
    (share/"utter").install "macos/com.utter.assistant.plist"
    (share/"utter").install "macos/com.utter.runner.plist"
  end

  service do
    run [opt_bin/"utter", "--daemon"]
    keep_alive true
    log_path var/"log/utter/utter.log"
    error_log_path var/"log/utter/utter.log"
    working_dir var/"utter"
    environment_variables PYTHONUNBUFFERED: "1"
  end

  def caveats
    <<~EOS
      Utter requires macOS privacy permissions under System Settings -> Privacy & Security:
        - Microphone (audio capture during push-to-talk)
        - Speech Recognition (on-device Speech.framework)
        - Accessibility (keystroke injection & window focus)
        - Input Monitoring (Quartz event tap for hotkeys)
        - Screen Recording (vision capture)

      To start the background voice daemon service:
        brew services start utter

      For the graphical settings interface, download utter.dmg:
        https://github.com/sujaisubbanna/utter-assistant/releases
      Or if using the tap:
        brew install --cask utter
    EOS
  end

  test do
    system "#{bin}/utter", "--version" rescue nil
  end
end
