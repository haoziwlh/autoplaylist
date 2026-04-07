class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/f1/79/135e1174dec46cd6158451ffa183129acd45b2d1c56bb2973cc5f77518c1/myplaylist-0.3.13-py3-none-any.whl",,,,,,,,,,,,,,
      using: :nounzip
  sha256 "0fc4637d79dcd37ff089e278f69c643ebdb14e75f7713d31a9148e53549f39f8"
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
