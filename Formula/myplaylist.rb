class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/43/89/cde8857ac50646b23be0ebbfef6a4fd2834ce4394edd5630066b45a88d23/myplaylist-0.4.2-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "dbb6d00cd8c48c1e95898ee748c9b896e5c2b6d156c094f06433cb3716684c68"
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
