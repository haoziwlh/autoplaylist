class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/28/b7/7b6a2176a6b967c10e64e5b1080fe30e834ff4c0a43bee8a85831e2ec82e/myplaylist-0.3.4-py3-none-any.whl",,,,,,
      using: :nounzip
  sha256 "12a8a859bca2961b4900fb4a004797a8ba662f6bc6378c41a60f9dc017f4bf95"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
