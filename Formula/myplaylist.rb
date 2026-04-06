class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/0e/60/e443b771bf4920b755270c22987997e8e2c130f72068eb8551d77e7ba25a/myplaylist-0.3.0-py3-none-any.whl",,
      using: :nounzip
  sha256 "090a605079ee5aed79a53c55405f766cedcb6295e89779d6cd9012e62fd650fd"
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
