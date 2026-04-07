class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/92/a4/51d27c70fc4b26ba8682fad9459509ddf4e5bc85ccebff8874c9d6927008/myplaylist-0.3.2-py3-none-any.whl",,,,
      using: :nounzip
  sha256 "e0ca8442d8230cdfbcec0e64b1c3e0949e1b9d6f2b46954bdf479d76023e4a80"
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
