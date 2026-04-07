class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/de/ad/7ecf7c7fe655bd538a22467599c80280f93e22f1b6731a42dd002cfb4991/myplaylist-0.3.12-py3-none-any.whl",,,,,,,,,,,,,
      using: :nounzip
  sha256 "e90ccaceadb77a3b6ed46d43c0029b69e89d50372cc96356a3979fc7d0a357f9"
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
