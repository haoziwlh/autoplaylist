class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/19/ce/c01c7f5574ff043da9d2e6fea53b575486b24fff6ce0e2949bff581f16f7/myplaylist-0.3.23-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "7f88d63fa296ae16ec4eabaeb0c00fc356072dcf795cb46a576837beee37e24b"
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
