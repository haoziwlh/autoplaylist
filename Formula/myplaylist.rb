class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/b2/51/409d2e07d611435984ad56c305eb2f4d8c49a45911473dbbdad057316645/myplaylist-0.3.18-py3-none-any.whl",,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "8850da5ed76818f1ff0b05f7f5fecfce4c811fddf2378a75e1df89c5fc5e64b7"
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
